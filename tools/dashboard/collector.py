"""COLLECTOR — đọc mọi điểm theo Point Map, giải mã, kiểm tra cảnh báo.

Chạy:  make collect                 (đọc liên tục, mở http://localhost:8080 để xem và ghi)
       make once                    (đọc một lượt, in bảng rồi thoát)

Trang web (collector.html) lấy số liệu từ GET /api/points và ghi qua POST /api/write.
Lệnh ghi từ web đi qua cùng rào chắn với edge/write-service/write.py.

Mỗi địa chỉ host:port một kết nối; thiết bị sau cùng gateway dùng chung. Một địa chỉ không kết nối
được thì chỉ các thiết bị ở địa chỉ đó báo lỗi, và lượt đó không thử lại nó cho từng điểm.
Mặc định --env lab (simulator); --env site để đọc thiết bị thật.
"""
import argparse, json, logging, threading, time, warnings
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from modbus_io import Connections, address
from point_map import DEFAULT_PATH, load_or_exit

warnings.filterwarnings("ignore")
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
LATEST, ALERTS, HISTORY = {}, {}, {}           # HISTORY: các giá trị gần nhất của mỗi điểm, để vẽ xu hướng
STATUS = {"round": 0, "at": None}
CLIENT_LOCK = threading.Lock()                 # kết nối pymodbus không an toàn đa luồng: lượt đọc và lệnh ghi từ web
DATA_LOCK = threading.Lock()                   # trang web đọc số liệu trong lúc vòng đọc đang cập nhật
PAGE = Path(__file__).with_name("collector.html")


def poll_once(conns, cfg):
    rows, down = {}, set()                         # down: địa chỉ không kết nối được trong lượt này
    with CLIENT_LOCK:
        for d in cfg["devices"]:
            ep = address(d)
            if ep not in down and not conns.client(d).connected:
                down.add(ep)
            for p in d["points"]:
                key = f"{d['name']}.{p['name']}"
                row = {"unit": p.get("unit", ""), "at": time.strftime("%H:%M:%S")}
                if ep in down:
                    row.update(value=None, ok=False, error=f"không kết nối được {ep}")
                else:
                    try:
                        row.update(value=round(conns.read(d, p), 2), ok=True)
                    except Exception as e:         # timeout, mã lỗi, rớt kết nối giữa chừng
                        row.update(value=None, ok=False, error=str(e) or type(e).__name__)
                rows[key] = row
    with DATA_LOCK:
        LATEST.update(rows)
        for k, r in rows.items():
            HISTORY.setdefault(k, deque(maxlen=60)).append(r["value"])
        STATUS.update(round=STATUS["round"] + 1, at=time.strftime("%H:%M:%S"))
        check_alerts(cfg)


def check_alerts(cfg):
    for a in cfg.get("alerts", []):
        v = LATEST.get(a["point"], {}).get("value")
        firing = v is not None and (("above" in a and v > a["above"]) or ("below" in a and v < a["below"]))
        if firing and not ALERTS.get(a["point"]):
            print(f"  !! CẢNH BÁO: {a['message']} — {a['point']} = {v}")
        elif not firing and ALERTS.get(a["point"]):
            print(f"  ok Hết cảnh báo: {a['point']} = {v}")
        ALERTS[a["point"]] = firing


def print_table():
    for k, r in LATEST.items():
        val = f"{r['value']} {r['unit']}" if r["ok"] else f"LỖI: {r['error']}"
        print(f"  {k:28} {val}")


def snapshot(cfg):
    """Mọi thứ trang web cần trong một lần gọi. Gọi khi đang giữ DATA_LOCK."""
    devices = [{"name": d["name"], "device_id": d["device_id"], "byte_order": d["byte_order"],
                "endpoint": address(d), "site_endpoint": d.get("site_address", address(d)),
                "points": [{"key": f"{d['name']}.{p['name']}", "name": p["name"], "unit": p.get("unit", ""),
                            "table": p["table"], "address": p["address"], "type": p["type"],
                            "writable": bool(p.get("writable")), "allowed": p.get("allowed")}
                           for p in d["points"]]}
               for d in cfg["devices"]]
    return {"site": cfg.get("site"), "env": cfg.get("env"),
            "points": LATEST,
            "alerts": [k for k, v in ALERTS.items() if v],
            "devices": devices,
            "alert_rules": [dict(a, firing=bool(ALERTS.get(a["point"]))) for a in cfg.get("alerts", [])],
            "history": {k: list(v) for k, v in HISTORY.items()},
            "status": STATUS}


class Web(BaseHTTPRequestHandler):
    cfg = conns = None                             # gán trong serve()

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

    def do_GET(self):
        if self.path == "/api/points":
            with DATA_LOCK:
                body = json.dumps(snapshot(self.cfg), ensure_ascii=False).encode()
            self.reply(200, body)
        elif self.path in ("/", "/index.html"):
            self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self.reply(404, {"ok": False, "error": "không có đường dẫn này"})

    def do_POST(self):
        if self.path != "/api/write":
            return self.reply(404, {"ok": False, "error": "không có đường dẫn này"})
        from write import WriteBlocked, write_guarded     # nhập muộn: write.py cũng nhập collector
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            key, value = str(req["point"]), float(req["value"])
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"ok": False, "error": 'cần JSON dạng {"point": "...", "value": số}'})
        try:
            with CLIENT_LOCK:
                before, after = write_guarded(self.cfg, self.conns, key, value)
        except WriteBlocked as e:
            print(f"  xx Rào chắn từ chối lệnh ghi từ web: {key} = {value} ({e})")
            return self.reply(403, {"ok": False, "blocked": True, "error": str(e)})
        except Exception as e:
            return self.reply(502, {"ok": False, "error": str(e) or type(e).__name__})
        print(f"  >> Ghi từ web: {key}: {before} -> {after} (đã đọc lại xác nhận)")
        self.reply(200, {"ok": True, "point": key, "before": before, "after": after})


def serve(cfg, conns, host="127.0.0.1", port=8080):
    """Chạy web ở luồng nền. port=0 để hệ điều hành tự chọn cổng (dùng cho kiểm thử)."""
    Web.cfg, Web.conns = cfg, conns
    srv = ThreadingHTTPServer((host, port), Web)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--env", default="lab", help="lab = simulator (mặc định); site = thiết bị thật")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--web-host", default="127.0.0.1", help="0.0.0.0 để mở từ ngoài máy ảo")
    ap.add_argument("--web-port", type=int, default=8080)
    args = ap.parse_args()
    cfg = load_or_exit(args.config, args.env)
    c = Connections()
    if args.once:
        poll_once(c, cfg)
        print_table()
        raise SystemExit
    serve(cfg, c, args.web_host, args.web_port)
    print(f"Collector site {cfg.get('site', '?')}, môi trường {args.env}. "
          f"Xem tại http://{args.web_host}:{args.web_port}  (Ctrl+C để dừng)")
    try:
        while True:
            poll_once(c, cfg)
            ok = sum(r["ok"] for r in LATEST.values())
            print(f"Lượt {STATUS['round']}: {ok}/{len(LATEST)} điểm đọc được")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nĐã dừng collector.")
