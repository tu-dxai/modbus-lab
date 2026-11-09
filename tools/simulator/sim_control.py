"""KÊNH ĐIỀU KHIỂN SIMULATOR — HTTP, tách khỏi Modbus.

Điểm chỉ đọc (ví dụ điện áp) thì client Modbus không ghi được, giống thiết bị thật. Người kiểm thử
đặt giá trị qua kênh này, nên client vẫn thấy thiết bị y như thật.

  GET    /                 trang điều khiển (control.html)
  GET    /api/state        mọi điểm và giá trị hiện tại
  POST   /api/state        {"bess-01.muc_pin": 15.5, ...}  đặt nhiều điểm; một điểm sai thì không đổi gì
  GET    /api/writes       nhật ký lệnh ghi Modbus; lọc bằng ?point=...&since=<seq>
  DELETE /api/writes       xóa nhật ký
  POST   /api/reset        về giá trị khởi đầu và xóa nhật ký
"""
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from sim_state import BadValue, SimState, UnknownPoint

PAGE = Path(__file__).with_name("control.html")


class Control(BaseHTTPRequestHandler):
    state: SimState = None                         # gán trong serve()

    def log_message(self, *a):
        pass

    def reply(self, code: int, body, ctype: str = "application/json; charset=utf-8") -> None:
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def not_found(self) -> None:
        self.reply(404, {"ok": False, "error": "không có đường dẫn này"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self.reply(200, {"points": self.state.snapshot()})
        elif url.path == "/api/writes":
            q = parse_qs(url.query)
            try:
                since = int(q["since"][0]) if "since" in q else None
            except ValueError:
                return self.reply(400, {"ok": False, "error": "since phải là số nguyên"})
            point = q["point"][0] if "point" in q else None
            self.reply(200, {"writes": self.state.writes(point, since)})
        else:
            self.not_found()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/reset":
            self.state.reset()
            return self.reply(200, {"ok": True})
        if path != "/api/state":
            return self.not_found()
        try:
            values = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if not isinstance(values, dict) or not values:
                raise ValueError
        except ValueError:
            return self.reply(400, {"ok": False, "error": 'cần JSON dạng {"thiết-bị.điểm": giá trị, ...}'})
        try:
            changed = self.state.set_many(values)
        except UnknownPoint as e:
            return self.reply(404, {"ok": False, "error": str(e)})
        except BadValue as e:
            return self.reply(400, {"ok": False, "error": str(e)})
        print(f"  << Đặt giá trị: {', '.join(f'{k} = {v}' for k, v in changed.items())}")
        self.reply(200, {"ok": True, "points": changed})

    def do_DELETE(self):
        if urlparse(self.path).path != "/api/writes":
            return self.not_found()
        self.state.clear_writes()
        self.reply(200, {"ok": True})


def serve(state: SimState, host: str = "127.0.0.1", port: int = 5080) -> ThreadingHTTPServer:
    """Chạy kênh điều khiển ở luồng nền. port=0 để hệ điều hành tự chọn cổng."""
    handler = type("BoundControl", (Control,), {"state": state})   # mỗi simulator một lớp, không dùng chung
    srv = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
