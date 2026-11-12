"""COLLECTOR — đọc các điểm theo Point Map khi được yêu cầu, giải mã, kiểm tra cảnh báo.

Chạy:  make collect                       (đọc khi bấm nút trên http://localhost:8080 — tiện kiểm thử)
       make collect ARGS="--interval 2"   (tự đọc mỗi 2 giây, giống edge chạy thật)
       make once                          (đọc một lượt, in bảng rồi thoát)

Mặc định KHÔNG tự đọc: mỗi lần bấm "Đọc" là đúng một lượt yêu cầu Modbus, nên khung tin và lệnh ghi bên
simulator khớp với từng thao tác. Tự đọc bật/tắt được ngay trên trang (POST /api/auto).

API cho trang web (collector.html):
  GET  /api/points    số liệu lần đọc gần nhất, cảnh báo, mô tả điểm, lịch sử
  POST /api/read      đọc ngay: {} = mọi điểm, {"device": "bess-01"}, {"point": "bess-01.muc_pin"}
  POST /api/auto      {"interval": 0} tắt tự đọc, {"interval": 5} tự đọc mỗi 5 giây (1-3600)
  POST /api/write     ghi qua cùng rào chắn với edge/write-service/write.py
  POST /api/relinquish  BACnet: nhả lệnh {"point": "crah-01.diem_dat_nhiet"} ở priority của điểm
  GET  /api/frames    khung tin collector gửi đi và nhận về; lọc ?device=&function=&errors=1&since=&limit=
  DELETE /api/frames  xóa khung tin
  POST /api/source    {"source": "telegraf", "interval": 2} Telegraf thật đọc Modbus / SNMP; {"source": "python"}
  POST /api/telegraf  Telegraf gửi số liệu về đây (outputs.http, JSON)

Hai nguồn số liệu (chọn trên trang hoặc --source):
  python    collector tự đọc bằng pymodbus / pysnmp / bacpypes3: đọc khi bấm, xem được khung tin thô — để debug
  telegraf  Telegraf thật (Docker telegraf:1.32, như edge thật và demo A04) đọc định kỳ Modbus TCP, RTU qua TCP, SNMP
            theo cấu hình sinh từ Point Map; Python vẫn đọc BACnet và bus RS-485 ở cổng serial ảo trên máy.
            Điểm Telegraf không gửi về quá 3 chu kỳ thì báo lỗi "cũ" (thiết bị không trả lời, tắt...).

Mỗi địa chỉ host:port một kết nối; thiết bị sau cùng gateway dùng chung. Một địa chỉ không kết nối
được thì chỉ các thiết bị ở địa chỉ đó báo lỗi, và lượt đó không thử lại nó cho từng điểm.
Mặc định --env auto: hỏi simulator đang chạy (SIM_URL, mặc định http://127.0.0.1:5080) thiết bị nằm ở đâu,
nên đọc được cả simulator chạy bằng make sim lẫn simulator trong Docker của demo A04; không thấy simulator
thì dùng môi trường lab. --env lab: theo environments/lab.yml; --env site: thiết bị thật.
"""
import argparse, atexit, json, logging, signal, threading, time, warnings
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from audit import DEFAULT_PATH as AUDIT_PATH, AuditLog
from frames import FrameLog, function_filter
from i18n import SCRIPT, ApiError, Translatable, by_language, t
from modbus_io import Connections, address
from point_map import DEFAULT_PATH, PointMapError, device_meta, load, load_or_exit, point_ref
from simctl import BACNET_CLIENT_PORT, SimControl, SimError
from telegraf_source import TelegrafError, TelegrafRunner, handled, ingest

warnings.filterwarnings("ignore")
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
LATEST, ALERTS, HISTORY = {}, {}, {}           # HISTORY: các giá trị gần nhất của mỗi điểm, để vẽ xu hướng
# round/at: lượt đọc gần nhất; read/ok_count/ms: kết quả lượt đó; auto: chu kỳ tự đọc (0 = chỉ đọc khi bấm)
STATUS = {"round": 0, "at": None, "read": 0, "ok_count": 0, "ms": None, "auto": 0,
          "source": "python", "telegraf": None}       # telegraf: {interval, running, last, devices, logs} khi bật
SOURCES = ("python", "telegraf")
TELEGRAF_INTERVAL_MAX = 60
RUNNER: TelegrafRunner | None = None
CLIENT_LOCK = threading.Lock()                 # kết nối pymodbus không an toàn đa luồng: lượt đọc và lệnh ghi từ web
DATA_LOCK = threading.Lock()                   # trang web đọc số liệu trong lúc vòng đọc đang cập nhật
PAGE = Path(__file__).with_name("collector.html")
WEB = Path(__file__).resolve().parents[1] / "web"     # giao diện dùng chung với trang simulator: ui.css, ui.js
AUTO_MAX = 3600


def poll_once(conns, cfg, device: str | None = None, point: str | None = None, only: set | None = None) -> dict:
    """Đọc mọi điểm, hoặc chỉ một thiết bị / một điểm. only: chỉ các thiết bị này (nguồn Telegraf: phần Python đọc).
    Trả về {read, ok_count, ms}."""
    rows, down = {}, set()                         # down: địa chỉ không kết nối được trong lượt này
    t0 = time.perf_counter()
    with CLIENT_LOCK:
        refresh_environment(cfg, conns)
        for d in cfg["devices"]:
            if (device is not None and d["name"] != device) or (only is not None and d["name"] not in only):
                continue
            targets = [p for p in d["points"] if point is None or f"{d['name']}.{p['name']}" == point]
            if not targets:
                continue
            ep = address(d)
            if ep not in down and not conns.reachable(d):
                down.add(ep)
            if ep in down:
                conns.unreachable(d)                   # một mục khung tin cho thiết bị, không lặp theo điểm
            silent = False                             # thiết bị không trả lời: bỏ qua các điểm còn lại trong lượt
            for p in targets:
                key = f"{d['name']}.{p['name']}"
                row = {"unit": p.get("unit", ""), "at": time.strftime("%H:%M:%S"), "source": "python"}
                if ep in down:
                    row.update(value=None, ok=False, **_error_row("read.unreachable", endpoint=ep))
                elif silent:
                    row.update(value=None, ok=False, **_error_row("read.skipped", device=d["name"]))
                else:
                    try:
                        row.update(value=round(conns.read(d, p), 2), ok=True)
                    except Translatable as e:      # thiết bị trả mã lỗi (có trả lời), hoặc SNMP/BACnet hết giờ
                        row.update(value=None, ok=False, **_error_row(e.code, **e.params))
                        silent = e.code.endswith("_no_answer")
                    except Exception as e:         # timeout, rớt kết nối giữa chừng
                        row.update(value=None, ok=False,
                                   **_error_row("read.failed", detail=str(e) or type(e).__name__))
                        silent = True
                rows[key] = row
    result = {"read": len(rows), "ok_count": sum(r["ok"] for r in rows.values()),
              "ms": round((time.perf_counter() - t0) * 1000, 1)}
    with DATA_LOCK:
        LATEST.update(rows)
        for k, r in rows.items():
            HISTORY.setdefault(k, deque(maxlen=60)).append(r["value"])
        STATUS.update(round=STATUS["round"] + 1, at=time.strftime("%H:%M:%S"), **result)
        check_alerts(cfg)
    return result


def refresh_environment(cfg: dict, conns) -> bool:
    """--env auto: hỏi lại simulator trước mỗi lượt đọc. Thiết bị đổi chỗ nghe (simulator chạy sau collector,
    hay khởi động lại ở chỗ khác: make sim <-> Docker demo A04) thì nạp lại Point Map ngay trong cfg, xóa số liệu
    cũ và mở lại kết nối. Simulator không trả lời thì giữ nguyên. Gọi khi đang giữ CLIENT_LOCK."""
    auto = cfg.get("auto")
    if not auto:
        return False
    try:
        env_cfg = SimControl(auto["sim_url"], timeout=1).environment(auto["bacnet_port"])
    except SimError:
        return False
    if env_cfg == auto["env_cfg"]:
        return False
    try:
        new = load(auto["path"], "sim", env_cfg)
    except PointMapError as e:
        print(f"Simulator tại {auto['sim_url']} không khớp Point Map: {'; '.join(e.errors)}")
        return False
    conns.close()
    if STATUS["source"] == "telegraf" and RUNNER is not None:     # Telegraf đọc theo địa chỉ mới
        try:
            RUNNER.start(new)
        except TelegrafError as e:
            print(f"Không chạy lại được Telegraf: {e}")
    with DATA_LOCK:
        cfg.clear()
        cfg.update(new, auto=dict(auto, env_cfg=env_cfg))
        LATEST.clear(), HISTORY.clear(), ALERTS.clear()
        if Web.frames is not None:                 # khung tin: tra thiết bị theo địa chỉ mới
            Web.frames.devices = {(address(d), d.get("device_id")): d for d in cfg["devices"]}
    print(f"Thiết bị theo simulator tại {auto['sim_url']} (vừa cập nhật địa chỉ)")
    for name, why in cfg.get("unreachable", {}).items():
        print(f"  bỏ qua {name}: {why}")
    return True


def _error_row(code: str, /, **params) -> dict:
    """Lỗi của một điểm: error tiếng Việt cho dòng lệnh, code + params để trang web dịch."""
    return {"error": t(code, **params), "code": code, "params": params}


def check_alerts(cfg):
    for a in cfg.get("alerts", []):
        v = LATEST.get(a["point"], {}).get("value")
        firing = v is not None and (("above" in a and v > a["above"]) or ("below" in a and v < a["below"]))
        if firing and not ALERTS.get(a["point"]):
            print(f"  !! CẢNH BÁO: {a['message']['vi']} — {a['point']} = {v}")
        elif not firing and ALERTS.get(a["point"]):
            print(f"  ok Hết cảnh báo: {a['point']} = {v}")
        ALERTS[a["point"]] = firing


def print_table():
    for k, r in LATEST.items():
        val = f"{r['value']} {r['unit']}" if r["ok"] else f"LỖI: {r['error']}"
        print(f"  {k:28} {val}")


def _fresh(points: dict) -> dict:
    """Điểm Telegraf không gửi về quá 3 chu kỳ: báo lỗi "cũ" thay vì hiện giá trị cũ như còn sống."""
    tg = STATUS.get("telegraf") or {}
    limit = 3 * tg.get("interval", 2) + 1
    now, out = time.time(), {}
    for k, r in points.items():
        age = now - r["ts"] if r.get("source") == "telegraf" and r.get("ts") else 0
        out[k] = dict(r, value=None, ok=False, **_error_row("telegraf.stale", s=int(age))) if age > limit else r
    return out


def telegraf_python_devices(cfg) -> set:
    """Nguồn Telegraf: thiết bị Telegraf không đọc được, Python đọc thay (BACnet, RS-485 ở cổng ảo trên máy)."""
    return {d["name"] for d in cfg["devices"]} - set(handled(cfg))


def set_source(cfg, source: str, interval: int = 2) -> None:
    """Đổi nguồn số liệu. telegraf: sinh cấu hình từ Point Map, chạy container; python: dừng container."""
    global RUNNER
    if source == "telegraf":
        if RUNNER is None or RUNNER.interval != interval:
            if RUNNER is not None:
                RUNNER.stop()
            RUNNER = TelegrafRunner(f"http://127.0.0.1:{Web.port}/api/telegraf", interval,
                                    name=f"modbus-lab-telegraf-{Web.port}")
        with CLIENT_LOCK:
            RUNNER.start(cfg)
        STATUS.update(source="telegraf", auto=0,
                      telegraf={"interval": interval, "running": True, "last": None, "devices": RUNNER.devices,
                                "python": sorted(telegraf_python_devices(cfg)), "logs": []})
        print(f"  ~~ Nguồn Telegraf ({RUNNER.name}): Telegraf đọc {', '.join(RUNNER.devices)} mỗi {interval} giây; "
              f"Python đọc {', '.join(STATUS['telegraf']['python']) or 'không thiết bị nào'}")
    else:
        if RUNNER is not None:
            RUNNER.stop()
        STATUS.update(source="python", telegraf=None)
        print("  ~~ Nguồn Python: collector tự đọc, đọc khi bấm")


def snapshot(cfg):
    """Mọi thứ trang web cần trong một lần gọi. Gọi khi đang giữ DATA_LOCK."""
    devices = [{"name": d["name"], "label": d["label"], "device_id": d.get("device_id"),
                "byte_order": d.get("byte_order"), "protocol": d.get("protocol", "modbus"), "meta": device_meta(d),
                "endpoint": address(d), "site_endpoint": d.get("site_address", address(d)),
                "points": [{"key": f"{d['name']}.{p['name']}", "name": p["name"], "label": p["label"],
                            "unit": p.get("unit", ""), "ref": point_ref(d, p),
                            "table": p.get("table"), "address": p.get("address"), "type": p.get("type"),
                            "writable": bool(p.get("writable")), "allowed": p.get("allowed"),
                            "priority": p.get("priority")}
                           for p in d["points"]]}
               for d in cfg["devices"]]
    return {"site": cfg.get("site"), "env": cfg.get("env"),
            "points": _fresh(LATEST),
            "alerts": [k for k, v in ALERTS.items() if v],
            "devices": devices,
            "alert_rules": [dict(a, firing=bool(ALERTS.get(a["point"]))) for a in cfg.get("alerts", [])],
            "history": {k: list(v) for k, v in HISTORY.items()},
            "status": STATUS}


def auto_loop(conns, cfg):
    """Tự đọc theo STATUS["auto"] giây; 0 = nằm chờ. Nguồn Telegraf: đọc phần Python (BACnet, RS-485 cổng ảo)
    theo chu kỳ của Telegraf và theo dõi container. Chạy nền suốt đời tiến trình."""
    last = checked = 0.0
    while Web.cfg is cfg:                          # serve() lần nữa với cấu hình khác: luồng cũ dừng, không đọc chồng
        tg = STATUS.get("telegraf")
        if STATUS["source"] == "telegraf" and tg:
            if time.monotonic() - last >= tg["interval"]:
                last = time.monotonic()
                only = telegraf_python_devices(cfg)
                if only:
                    poll_once(conns, cfg, only=only)
            if RUNNER is not None and time.monotonic() - checked >= 5:
                checked = time.monotonic()
                tg.update(running=RUNNER.running(), logs=RUNNER.logs())
            time.sleep(0.1)
            continue
        interval = STATUS["auto"]
        if interval and time.monotonic() - last >= interval:
            last = time.monotonic()
            r = poll_once(conns, cfg)
            print(f"Lượt {STATUS['round']} (tự đọc): {r['ok_count']}/{r['read']} điểm đọc được, {r['ms']} ms")
        time.sleep(0.1)


class Web(BaseHTTPRequestHandler):
    cfg = conns = frames = audit = port = None     # gán trong serve()

    def log_message(self, *a):
        pass

    def reply(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        """JSON gửi lên; rỗng thì {}. Sai dạng -> ValueError."""
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise ValueError
        return data

    def do_GET(self):
        path = urlparse(self.path).path           # bỏ phần ?lang=... của trang web
        if path == "/api/points":
            with DATA_LOCK:
                body = json.dumps(snapshot(self.cfg), ensure_ascii=False).encode()
            self.reply(200, body)
        elif path == "/api/frames":
            return self.get_frames()
        elif path in ("/", "/index.html"):
            self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/i18n.json":
            self.reply(200, by_language())
        elif path == "/ui.css":
            self.reply(200, (WEB / "ui.css").read_bytes(), "text/css; charset=utf-8")
        elif path in ("/ui.js", "/frames.js"):
            self.reply(200, (WEB / path[1:]).read_bytes(), "text/javascript; charset=utf-8")
        elif path == "/i18n.js":
            self.reply(200, SCRIPT.read_bytes(), "text/javascript; charset=utf-8")
        else:
            self.reply(404, {"ok": False, **ApiError("api.not_found").as_json()})

    def get_frames(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        try:
            since = int(q["since"]) if "since" in q else None
            limit = int(q["limit"]) if "limit" in q else None
            function = function_filter(q.get("function"))
        except ValueError:
            return self.reply(400, {"ok": False, **ApiError("api.bad_frames_query").as_json()})
        self.reply(200, {"frames": self.frames.query(since, limit, q.get("device"), function,
                                                     q.get("errors") in ("1", "true"))})

    def do_DELETE(self):
        if urlparse(self.path).path != "/api/frames":
            return self.reply(404, {"ok": False, **ApiError("api.not_found").as_json()})
        self.frames.clear()
        self.reply(200, {"ok": True})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/read":
            return self.read()
        if path == "/api/auto":
            return self.auto()
        if path == "/api/write":
            return self.write()
        if path == "/api/relinquish":
            return self.write(relinquish=True)
        if path == "/api/telegraf":
            return self.telegraf()
        if path == "/api/source":
            return self.source()
        self.reply(404, {"ok": False, **ApiError("api.not_found").as_json()})

    def read(self):
        try:
            req = self.body()
        except ValueError:
            return self.reply(400, {"ok": False, **ApiError("api.bad_read_request").as_json()})
        device, point = req.get("device"), req.get("point")
        names = {d["name"] for d in self.cfg["devices"]}
        keys = {f"{d['name']}.{p['name']}" for d in self.cfg["devices"] for p in d["points"]}
        target = point if point is not None else device
        if (point is not None and point not in keys) or (device is not None and device not in names):
            return self.reply(404, {"ok": False, **ApiError("api.unknown_target", target=target).as_json()})
        result = poll_once(self.conns, self.cfg, device, point)
        print(f"Lượt {STATUS['round']} ({target or 'tất cả'}): {result['ok_count']}/{result['read']} điểm, "
              f"{result['ms']} ms")
        with DATA_LOCK:
            snap = json.loads(json.dumps(snapshot(self.cfg), ensure_ascii=False))
        self.reply(200, {"ok": True, **result, "snapshot": snap})

    def telegraf(self):
        """Số liệu Telegraf gửi về (outputs.http). Đang ở nguồn Python thì bỏ qua (container cũ còn gửi nốt)."""
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw                              # JSON Lines
        try:
            rows = ingest(payload, self.cfg)
        except (ValueError, TypeError, KeyError, AttributeError):
            return self.reply(400, {"ok": False, **ApiError("api.bad_telegraf_payload").as_json()})
        with DATA_LOCK:
            LATEST.update(rows)
            for k, r in rows.items():
                HISTORY.setdefault(k, deque(maxlen=60)).append(r["value"])
            if STATUS.get("telegraf"):
                STATUS["telegraf"]["last"] = time.strftime("%H:%M:%S")
            check_alerts(self.cfg)
        self.reply(200, {"ok": True, "points": len(rows)})

    def source(self):
        try:
            req = self.body()
            source, interval = req.get("source"), req.get("interval", 2)
            ok = source in SOURCES and isinstance(interval, int) and not isinstance(interval, bool) \
                and 1 <= interval <= TELEGRAF_INTERVAL_MAX
        except ValueError:
            ok = False
        if not ok:
            return self.reply(400, {"ok": False, **ApiError("api.bad_source_request",
                                                            max=TELEGRAF_INTERVAL_MAX).as_json()})
        try:
            set_source(self.cfg, source, interval)
        except TelegrafError as e:
            print(f"  xx Không chạy được Telegraf: {e}")
            STATUS.update(source="python", telegraf=None)
            return self.reply(502, {"ok": False, **e.as_json()})
        self.reply(200, {"ok": True, "source": source, "telegraf": STATUS["telegraf"]})

    def auto(self):
        try:
            interval = self.body().get("interval")
            ok = isinstance(interval, int) and not isinstance(interval, bool) and (
                interval == 0 or 1 <= interval <= AUTO_MAX)
        except ValueError:
            ok = False
        if not ok:
            return self.reply(400, {"ok": False, **ApiError("api.bad_auto", max=AUTO_MAX).as_json()})
        STATUS["auto"] = interval
        print(f"  ~~ Tự đọc: {'tắt' if not interval else f'mỗi {interval} giây'}")
        self.reply(200, {"ok": True, "auto": interval})

    def write(self, relinquish=False):
        from write import WriteBlocked, find, relinquish_guarded, write_guarded   # nhập muộn: write.py cũng nhập collector
        try:
            req = self.body()
            key = str(req["point"])
            value = None if relinquish else float(req["value"])
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"ok": False, **ApiError("api.bad_write_request").as_json()})
        actor = f"web:{self.client_address[0]}"
        try:
            with CLIENT_LOCK:
                if relinquish:
                    before, after = None, relinquish_guarded(self.cfg, self.conns, key, self.audit, actor)
                else:
                    before, after = write_guarded(self.cfg, self.conns, key, value, self.audit, actor)
        except WriteBlocked as e:
            print(f"  xx Rào chắn từ chối lệnh ghi từ web: {key} = {value} ({e})")
            return self.reply(403, {"ok": False, "blocked": True, **e.as_json()})
        except Translatable as e:                  # thiết bị từ chối, đọc lại không khớp, mã lỗi Modbus
            return self.reply(502, {"ok": False, **e.as_json()})
        except Exception as e:                     # mất kết nối, timeout
            self.conns.no_response(find(self.cfg, key)[0])
            return self.reply(502, {"ok": False, **_error_row("read.failed", detail=str(e) or type(e).__name__)})
        if relinquish:
            priority = find(self.cfg, key)[1]["priority"]
            print(f"  >> Nhả lệnh từ web: {key} (ưu tiên {priority}) -> {after}")
            return self.reply(200, {"ok": True, "point": key, "after": after, "priority": priority})
        print(f"  >> Ghi từ web: {key}: {before} -> {after} (đã đọc lại xác nhận)")
        self.reply(200, {"ok": True, "point": key, "before": before, "after": after})


def serve(cfg, conns, host="127.0.0.1", port=8080, frames=500, audit=None):
    """Chạy web và luồng tự đọc (nằm chờ khi STATUS["auto"] = 0). port=0 để hệ điều hành chọn cổng.

    frames: số cặp khung tin gần nhất collector giữ lại để xem byte gửi và nhận.
    """
    log = FrameLog({(address(d), d.get("device_id")): d for d in cfg["devices"]}, frames)
    conns.trace(log)
    Web.cfg, Web.conns, Web.frames, Web.audit = cfg, conns, log, audit
    srv = ThreadingHTTPServer((host, port), Web)
    Web.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=auto_loop, args=(conns, cfg), daemon=True).start()
    return srv


def _exit_on_sigterm(*_) -> None:
    raise SystemExit(0)                            # để atexit chạy: dừng container Telegraf


def load_config(path: str, env: str, sim_url: str | None = None, bacnet_port: int = BACNET_CLIENT_PORT) -> dict:
    """Point Map theo môi trường. env "auto": hỏi simulator đang chạy thiết bị nằm ở đâu (make sim hay Docker
    demo A04 đều được); không kết nối được simulator thì tạm dùng môi trường lab. cfg["auto"] giữ thông tin để
    mỗi lượt đọc hỏi lại simulator (refresh_environment), nên simulator chạy sau collector vẫn đọc được."""
    if env != "auto":
        return load_or_exit(path, env)
    ctl = SimControl(sim_url)
    auto = {"path": path, "sim_url": ctl.url, "bacnet_port": bacnet_port, "env_cfg": None}
    try:
        auto["env_cfg"] = ctl.environment(bacnet_port)
    except SimError as e:
        print(f"{e}; tạm dùng môi trường lab, sẽ hỏi lại simulator ở mỗi lượt đọc")
        return dict(load_or_exit(path, "lab"), auto=auto)
    cfg = load_or_exit(path, "sim", auto["env_cfg"])
    print(f"Thiết bị theo simulator tại {ctl.url}")
    for name, why in cfg.get("unreachable", {}).items():
        print(f"  bỏ qua {name}: {why}")
    return dict(cfg, auto=auto)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--env", default="auto",
                    help="auto = theo simulator đang chạy ở SIM_URL (mặc định); lab = environments/lab.yml; "
                         "site = thiết bị thật")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=0,
                    help="tự đọc mỗi N giây (1-3600); mặc định 0 = chỉ đọc khi bấm nút trên trang")
    ap.add_argument("--web-host", default="127.0.0.1", help="0.0.0.0 để mở từ ngoài máy ảo")
    ap.add_argument("--web-port", type=int, default=8080)
    ap.add_argument("--frames", type=int, default=500, help="số cặp khung tin gần nhất giữ lại để xem")
    ap.add_argument("--audit", default=AUDIT_PATH, help=f"nhật ký kiểm toán lệnh ghi (mặc định {AUDIT_PATH})")
    ap.add_argument("--source", choices=SOURCES, default="python",
                    help="python = collector tự đọc (mặc định, đọc khi bấm, xem khung tin); "
                         "telegraf = Telegraf thật trong Docker đọc Modbus / SNMP (đổi được trên trang)")
    ap.add_argument("--telegraf-interval", type=int, default=2, help="chu kỳ đọc của Telegraf, giây (1-60)")
    args = ap.parse_args()
    if not 0 <= args.interval <= AUTO_MAX:
        ap.error(f"--interval phải từ 0 đến {AUTO_MAX}")
    cfg = load_config(args.config, args.env)
    c = Connections()
    if args.once:
        poll_once(c, cfg)
        print_table()
        raise SystemExit
    STATUS["auto"] = args.interval
    serve(cfg, c, args.web_host, args.web_port, args.frames, AuditLog(args.audit))
    atexit.register(lambda: RUNNER and RUNNER.stop())   # tắt collector = dừng luôn container Telegraf
    # SIGTERM (timeout, docker stop, kill) mặc định thoát ngay, bỏ qua atexit: đổi thành thoát bình thường
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    if args.source == "telegraf":
        try:
            set_source(cfg, "telegraf", args.telegraf_interval)
        except TelegrafError as e:
            raise SystemExit(f"LỖI: {e}")
    mode = (f"nguồn Telegraf, đọc mỗi {args.telegraf_interval} giây" if args.source == "telegraf" else
            f"tự đọc mỗi {args.interval} giây" if args.interval else "đọc khi bấm nút trên trang")
    print(f"Collector site {cfg.get('site', '?')}, môi trường {args.env}, {mode}. "
          f"Xem tại http://{args.web_host}:{args.web_port}  (Ctrl+C để dừng)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nĐã dừng collector.")
