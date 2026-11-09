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
    simctl.py reset
"""
import argparse, json, os, sys, time, urllib.error, urllib.request
from urllib.parse import urlencode

DEFAULT_URL = "http://127.0.0.1:5080"


class SimError(Exception):
    """Simulator từ chối yêu cầu (điểm không có, giá trị không vừa...) hoặc không kết nối được."""


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

    def set(self, key: str, value: float) -> float:
        """Đặt một điểm; trả về giá trị thiết bị sẽ báo (đã làm tròn theo kiểu và hệ số)."""
        return self.set_many({key: value})[key]

    def set_many(self, values: dict) -> dict:
        return self._call("POST", "/api/state", values)["points"]

    def reset(self) -> None:
        self._call("POST", "/api/reset", {})

    # ---------- nhân chứng ----------
    def writes(self, point: str | None = None, since: int | None = None) -> list[dict]:
        q = {k: v for k, v in (("point", point), ("since", since)) if v is not None}
        return self._call("GET", "/api/writes" + (f"?{urlencode(q)}" if q else ""))["writes"]

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
        print(f"#{w['seq']:<4} {w['at']}  {target} ô {w['address']} {w['registers']}  [{status}]  {points}")


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
    sub.add_parser("reset", help="về giá trị khởi đầu và xóa nhật ký")
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
        elif args.cmd == "reset":
            ctl.reset()
            print("Đã đặt lại mọi giá trị và xóa nhật ký.")
    except SimError as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
