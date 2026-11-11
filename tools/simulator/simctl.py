"""ĐIỀU KHIỂN SIMULATOR từ code kiểm thử hoặc dòng lệnh (gọi HTTP API của sim_control.py).

Trong code kiểm thử:
    ctl = SimControl()                                  # mặc định http://127.0.0.1:5080, hoặc biến SIM_URL
    ctl.reset()
    ctl.set("dong-ho-dien-01.nhiet_do_tu", 31.5)        # tạo tình huống
    w = ctl.wait_for_write("bess-01.che_do", timeout=10)  # chờ client phản ứng
    assert w["accepted"] and w["points"][0]["value"] == 1

Dòng lệnh (make set / make writes / make reset gọi vào đây):
    simctl.py get [điểm]
    simctl.py set <điểm> <giá trị> [<điểm> <giá trị> ...]
    simctl.py writes [--point điểm] [--since seq]
    simctl.py clear-writes
    simctl.py frames [--device thiết-bị] [--function 3] [--errors] [--limit 20]   khung tin thô
    simctl.py clear-frames
    simctl.py auto [giây]     xem / đặt chế độ tự thay đổi giá trị (0 = chỉ đặt bằng tay)
    simctl.py reset
"""
import argparse, json, os, socket, sys, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlencode

DEFAULT_URL = "http://127.0.0.1:5080"
BACNET_CLIENT_PORT = 47809    # cổng client BACnet của máy này: khác cổng thiết bị (47808), như environments/lab.yml


class SimError(Exception):
    """Simulator từ chối yêu cầu (điểm không có, giá trị không vừa...) hoặc không kết nối được."""


def _is_virtual_port(path: str) -> bool:
    """Cổng serial ảo simulator tạo trên CHÍNH máy này (vserial.py): symlink trỏ tới một pseudo-terminal."""
    p = Path(path)
    return p.is_symlink() and os.path.realpath(p).startswith(("/dev/pts/", "/dev/ttys"))


def _local_ip(host: str) -> str:
    """IP của máy này trên đường tới host (không gửi gói nào: UDP connect chỉ chọn tuyến)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 47808))
        return s.getsockname()[0]


def environment_from_state(points: dict, bacnet_port: int = BACNET_CLIENT_PORT) -> dict:
    """Từ /api/state của simulator: địa chỉ thật trong Point Map -> nơi simulator đang nghe.

    make sim (môi trường lab):   10.20.0.21:502 -> 127.0.1.21:5020;  /dev/ttyUSB0 -> var/serial/ttyUSB0 (cổng ảo)
    Docker demo A04 (site):      10.20.0.21:502 -> 10.20.0.21:502 (máy host tới được mạng Docker);
                                 /dev/ttyUSB0 nằm trong container -> unreachable, KHÔNG mở cổng thật của máy này
    bacnet_client: IP của máy này trên đường tới thiết bị BACnet, cổng bacnet_port.
    """
    env: dict = {"addresses": {}, "serial": {}, "unreachable": {}}
    bacnet: dict[str, str] = {}                        # địa chỉ thật -> nơi simulator nghe, của thiết bị BACnet
    for p in points.values():
        site, ep = p["site_endpoint"], p["endpoint"]
        if ep.startswith("rtu:"):
            src, dst = site.removeprefix("rtu:"), ep.removeprefix("rtu:")
            if _is_virtual_port(dst):
                env["serial"][src] = dst
            else:
                env["unreachable"][site] = f"cổng serial {dst} nằm ở máy hoặc container chạy simulator"
            continue
        env["addresses"][site] = ep
        if p.get("protocol") == "bacnet":
            bacnet[site] = ep
    if bacnet:
        try:
            env["bacnet_client"] = f"{_local_ip(min(bacnet.values()).rsplit(':', 1)[0])}/32:{bacnet_port}"
        except OSError as e:                               # máy này không có tuyến tới thiết bị BACnet
            for site, ep in bacnet.items():
                env["addresses"].pop(site)
                env["unreachable"][site] = f"không có đường mạng tới {ep} ({e.strerror})"
    return env


class SimControl:
    def __init__(self, url: str | None = None, timeout: float = 3.0):
        self.url = (url or os.environ.get("SIM_URL") or DEFAULT_URL).rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, data=None) -> dict:
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(self.url + path, data=body, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read())["error"]
            except (ValueError, KeyError):
                msg = f"HTTP {e.code}"
            raise SimError(msg) from None
        except urllib.error.URLError as e:
            raise SimError(f"không kết nối được simulator tại {self.url} ({e.reason})") from None

    # ---------- giá trị ----------
    def get(self, key: str | None = None) -> dict:
        """Mọi điểm (dict theo tên), hoặc một điểm nếu có key."""
        points = self._call("GET", "/api/state")["points"]
        if key is None:
            return points
        if key not in points:
            raise SimError(f"không có điểm '{key}' trong Point Map")
        return points[key]

    def environment(self, bacnet_port: int = BACNET_CLIENT_PORT) -> dict:
        """Môi trường theo simulator đang chạy, cùng dạng environments/<env>.yml (xem environment_from_state)."""
        return environment_from_state(self.get(), bacnet_port)

    def set(self, key: str, value: float) -> float:
        """Đặt một điểm; trả về giá trị thiết bị sẽ báo (đã làm tròn theo kiểu và hệ số)."""
        return self.set_many({key: value})[key]

    def set_many(self, values: dict) -> dict:
        return self._call("POST", "/api/state", values)["points"]

    def auto(self) -> int:
        """Chu kỳ tự thay đổi giá trị hiện tại (giây); 0 = chỉ đặt bằng tay."""
        return self._call("GET", "/api/state")["auto"]

    def set_auto(self, interval: int) -> None:
        self._call("POST", "/api/auto", {"interval": interval})

    def power(self, device: str, on: bool) -> dict:
        """Bật / tắt thiết bị giả. Tắt = mất điện: IP riêng từ chối kết nối, sau gateway trả 0B,
        RS-485 / SNMP / BACnet im lặng. reset() bật lại tất cả."""
        return self._call("POST", "/api/power", {"device": device, "on": on})

    def off_devices(self) -> list[str]:
        """Các thiết bị đang tắt."""
        return sorted({p["device"] for p in self.get().values() if not p.get("on", True)})

    def reset(self) -> None:
        self._call("POST", "/api/reset", {})

    # ---------- nhân chứng ----------
    def writes(self, point: str | None = None, since: int | None = None) -> list[dict]:
        q = {k: v for k, v in (("point", point), ("since", since)) if v is not None}
        return self._call("GET", "/api/writes" + (f"?{urlencode(q)}" if q else ""))["writes"]

    def frames(self, device: str | None = None, function: int | str | None = None, errors: bool = False,
               since: int | None = None, limit: int | None = None) -> list[dict]:
        """Các cặp khung tin hỏi/đáp thô gần nhất, cũ trước mới sau (xem tools/simulator/frames.py)."""
        q = {k: v for k, v in (("device", device), ("function", function), ("since", since), ("limit", limit))
             if v is not None}
        if errors:
            q["errors"] = 1
        return self._call("GET", "/api/frames" + (f"?{urlencode(q)}" if q else ""))["frames"]

    def clear_frames(self) -> None:
        self._call("DELETE", "/api/frames")

    def clear_writes(self) -> None:
        self._call("DELETE", "/api/writes")

    def last_seq(self) -> int:
        """Số thứ tự lệnh ghi mới nhất (0 nếu chưa có), dùng làm mốc `since` trước khi tạo tình huống."""
        w = self.writes()
        return w[-1]["seq"] if w else 0

    def wait_for_write(self, point: str, timeout: float = 5.0, since: int | None = None,
                       interval: float = 0.1) -> dict:
        """Chờ tới khi có lệnh ghi chạm vào `point` (tính cả lệnh bị từ chối); hết giờ thì TimeoutError.

        Truyền since=ctl.last_seq() lấy TRƯỚC khi tạo tình huống để bỏ qua lệnh ghi cũ.
        """
        deadline = time.monotonic() + timeout
        while True:
            found = self.writes(point, since)
            if found:
                return found[0]
            if time.monotonic() >= deadline:
                raise TimeoutError(f"sau {timeout}s client vẫn chưa ghi vào {point}")
            time.sleep(interval)


def _print_writes(writes: list[dict]) -> None:
    if not writes:
        print("(chưa có lệnh ghi nào)")
    for w in writes:
        status = "nhận" if w["accepted"] else f"TỪ CHỐI mã {w['exception']}"
        target = (w["device"] or f"device_id {w['device_id']} (không tồn tại)") + f" @ {w['site_endpoint']}"
        arrow = (lambda p: f"{p['before']} -> {p['value']}") if w["accepted"] else \
                (lambda p: f"định ghi {p['value']} (vẫn giữ {p['before']})")
        points = ", ".join(f"{p['key']}: {arrow(p)}" for p in w["points"]) or "không trúng điểm nào"
        if w.get("function") == "bacnet-write":         # BACnet WriteProperty: đối tượng và mức ưu tiên
            p = w["points"][0]
            what = f"nhả lệnh (đang là {p['before']})" if p["value"] is None and w["accepted"] else arrow(p)
            print(f"#{w['seq']:<4} {w['at']}  {target} BACnet {w['address']} ưu tiên {w.get('priority') or '-'}"
                  f"  [{status}]  {p['key']}: {what}")
            continue
        print(f"#{w['seq']:<4} {w['at']}  {target} ô {w['address']} {w['registers']}  [{status}]  {points}")


def _print_frames(frames: list[dict]) -> None:
    from i18n import t                                 # nhập muộn: chỉ dòng lệnh cần chữ tiếng Việt
    if not frames:
        print(t("frames.empty"))
    for f in frames:
        target = (f["device_label"] or {}).get("vi") or f["device"] \
            or (t("frames.unknown_device", id=f["device_id"], endpoint=f["site_endpoint"])
                if f.get("protocol", "modbus") == "modbus" else t("frames.unknown_endpoint", endpoint=f["site_endpoint"]))
        print(f"#{f['seq']:<5} {f['at'][11:]}  {target} @ {f['site_endpoint']} · {t(f['fc_key'])} · {f['ms']} ms")
        for label, part in ((t("frames.sent"), f["request"]), (t("frames.received"), f["response"])):
            hexs = " | ".join(x["hex"] for x in part["fields"])
            s = part["summary"]
            print(f"  {label:<5} {hexs}      {t(s['key'], **s['params'])}")
            print(f"  {'':<5} {' | '.join(t('frame.f.' + x['name']) for x in part['fields'])}")
        for v in f["values"]:
            key = f"frame.explain_{v['kind']}" if v.get("kind") else \
                "frame.explain_16" if len(v["hex"].split()) == 2 else "frame.explain_32"
            name = (v["label"] or {}).get("vi") or v["key"]
            print(f"  {'':<5} " + t(key, hex=v["hex"], raw=v["raw"], scale=v["scale"], name=name,
                                     value=v["value"], unit=v["unit"], type=v["type"], order=v["byte_order"]))
        print()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="simctl", description="Điều khiển simulator Modbus")
    ap.add_argument("--url", help=f"mặc định biến SIM_URL hoặc {DEFAULT_URL}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get", help="xem giá trị hiện tại")
    g.add_argument("point", nargs="?")
    s = sub.add_parser("set", help="đặt giá trị: điểm giá trị [điểm giá trị ...]")
    s.add_argument("pairs", nargs="+")
    w = sub.add_parser("writes", help="xem nhật ký lệnh ghi của client")
    w.add_argument("--point")
    w.add_argument("--since", type=int)
    sub.add_parser("clear-writes", help="xóa nhật ký lệnh ghi")
    fr = sub.add_parser("frames", help="xem khung tin thô Modbus / SNMP / BACnet (byte gửi và nhận)")
    fr.add_argument("--device")
    fr.add_argument("--function", help="mã lệnh Modbus (3, 16) hoặc get / read-property / write-property")
    fr.add_argument("--errors", action="store_true", help="chỉ khung tin lỗi")
    fr.add_argument("--limit", type=int, default=20)
    sub.add_parser("clear-frames", help="xóa khung tin")
    sub.add_parser("reset", help="về giá trị khởi đầu và xóa nhật ký")
    au = sub.add_parser("auto", help="xem / đặt chế độ tự thay đổi giá trị (giây, 0 = chỉ đặt bằng tay)")
    au.add_argument("interval", nargs="?", type=int)
    pw = sub.add_parser("power", help="xem thiết bị đang tắt / bật, tắt một thiết bị: power <thiết bị> on|off")
    pw.add_argument("device", nargs="?")
    pw.add_argument("state", nargs="?", choices=("on", "off"))
    args = ap.parse_args(argv)
    ctl = SimControl(args.url)
    try:
        if args.cmd == "get":
            points = {args.point: ctl.get(args.point)} if args.point else ctl.get()
            for k, p in points.items():
                print(f"  {k:30} {p['value']} {p['unit']}{'  [ghi được]' if p['writable'] else ''}")
        elif args.cmd == "set":
            if len(args.pairs) % 2:
                ap.error("set cần từng cặp: điểm giá trị")
            pairs = dict(zip(args.pairs[::2], args.pairs[1::2]))
            try:
                values = {k: float(v) for k, v in pairs.items()}
            except ValueError:
                ap.error("giá trị phải là số")
            for k, v in ctl.set_many(values).items():
                print(f"Đã đặt {k} = {v}")
        elif args.cmd == "writes":
            _print_writes(ctl.writes(args.point, args.since))
        elif args.cmd == "clear-writes":
            ctl.clear_writes()
            print("Đã xóa nhật ký lệnh ghi.")
        elif args.cmd == "frames":
            _print_frames(ctl.frames(args.device, args.function, args.errors, limit=args.limit))
        elif args.cmd == "clear-frames":
            ctl.clear_frames()
            print("Đã xóa khung tin.")
        elif args.cmd == "auto":
            if args.interval is not None:
                ctl.set_auto(args.interval)
            n = ctl.auto()
            print(f"Tự thay đổi giá trị: mỗi {n} giây" if n else "Tự thay đổi giá trị: tắt (chỉ đặt bằng tay)")
        elif args.cmd == "power":
            if args.device and not args.state:
                ap.error("cần on hoặc off, ví dụ: power bess-01 off")
            if args.device:
                ctl.power(args.device, args.state == "on")
                print(f"Đã {'bật' if args.state == 'on' else 'tắt'} {args.device}")
            off = ctl.off_devices()
            print(f"Đang tắt: {', '.join(off)}" if off else "Mọi thiết bị đang bật.")
        elif args.cmd == "reset":
            ctl.reset()
            print("Đã đặt lại mọi giá trị và xóa nhật ký.")
    except SimError as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
