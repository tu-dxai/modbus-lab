"""KÊNH ĐIỀU KHIỂN SIMULATOR — HTTP, tách khỏi Modbus.

Điểm chỉ đọc (ví dụ điện áp) thì client Modbus không ghi được, giống thiết bị thật. Người kiểm thử
đặt giá trị qua kênh này, nên client vẫn thấy thiết bị y như thật.

  GET    /                 trang điều khiển (control.html)
  GET    /api/state        mọi điểm và giá trị hiện tại
  POST   /api/state        {"bess-01.muc_pin": 15.5, ...}  đặt nhiều điểm; một điểm sai thì không đổi gì
  GET    /api/writes       nhật ký lệnh ghi Modbus; lọc bằng ?point=...&since=<seq>
  DELETE /api/writes       xóa nhật ký
  GET    /api/frames       khung tin thô hỏi/đáp; lọc ?device=...&function=3&errors=1&since=<seq>&limit=N
  DELETE /api/frames       xóa khung tin
  POST   /api/reset        về giá trị khởi đầu và xóa nhật ký
  POST   /api/auto         {"interval": 5} tự thay đổi giá trị mỗi 5 giây; {"interval": 0} chỉ đặt bằng tay
  GET    /i18n.json        từ điển song ngữ vi/ja cho trang điều khiển
  GET    /i18n.js          mã song ngữ dùng chung (i18n/i18n.js)
  GET    /ui.css, /ui.js   giao diện dùng chung (tools/web/)

Lỗi trả về gồm error (tiếng Việt), code và params (để trang web dịch theo ngôn ngữ người dùng).
"""
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from frames import function_filter
from i18n import SCRIPT, ApiError, by_language
from sim_state import BadValue, SimState, UnknownPoint

PAGE = Path(__file__).with_name("control.html")
WEB = Path(__file__).resolve().parents[1] / "web"     # giao diện dùng chung với trang collector: ui.css, ui.js


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
        self.reply(404, {"ok": False, **ApiError("api.not_found").as_json()})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/i18n.json":
            self.reply(200, by_language())
        elif url.path == "/ui.css":
            self.reply(200, (WEB / "ui.css").read_bytes(), "text/css; charset=utf-8")
        elif url.path == "/ui.js":
            self.reply(200, (WEB / "ui.js").read_bytes(), "text/javascript; charset=utf-8")
        elif url.path == "/i18n.js":
            self.reply(200, SCRIPT.read_bytes(), "text/javascript; charset=utf-8")
        elif url.path == "/api/state":
            self.reply(200, {"points": self.state.snapshot(), "auto": self.state.auto})
        elif url.path == "/api/writes":
            q = parse_qs(url.query)
            try:
                since = int(q["since"][0]) if "since" in q else None
            except ValueError:
                return self.reply(400, {"ok": False, **ApiError("api.bad_since").as_json()})
            point = q["point"][0] if "point" in q else None
            self.reply(200, {"writes": self.state.writes(point, since)})
        elif url.path == "/api/frames":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                since = int(q["since"]) if "since" in q else None
                limit = int(q["limit"]) if "limit" in q else None
                function = function_filter(q.get("function"))
            except ValueError:
                return self.reply(400, {"ok": False, **ApiError("api.bad_frames_query").as_json()})
            self.reply(200, {"frames": self.state.frames.query(
                since, limit, q.get("device"), function, q.get("errors") in ("1", "true"))})
        else:
            self.not_found()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/reset":
            self.state.reset()
            return self.reply(200, {"ok": True})
        if path == "/api/auto":
            return self.set_auto()
        if path != "/api/state":
            return self.not_found()
        try:
            values = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if not isinstance(values, dict) or not values:
                raise ValueError
        except ValueError:
            return self.reply(400, {"ok": False, **ApiError("api.bad_state_request").as_json()})
        try:
            changed = self.state.set_many(values)
        except UnknownPoint as e:
            return self.reply(404, {"ok": False, **e.as_json()})
        except BadValue as e:
            return self.reply(400, {"ok": False, **e.as_json()})
        print(f"  << Đặt giá trị: {', '.join(f'{k} = {v}' for k, v in changed.items())}")
        self.reply(200, {"ok": True, "points": changed})

    def set_auto(self):
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            interval = json.loads(raw).get("interval")
            ok = isinstance(interval, int) and not isinstance(interval, bool) and (
                interval == 0 or 1 <= interval <= SimState.AUTO_MAX)
        except (ValueError, AttributeError):
            ok = False
        if not ok:
            return self.reply(400, {"ok": False, **ApiError("api.bad_auto", max=SimState.AUTO_MAX).as_json()})
        self.state.auto = interval
        print(f"  ~~ Tự thay đổi giá trị: {'tắt (chỉ đặt bằng tay)' if not interval else f'mỗi {interval} giây'}")
        self.reply(200, {"ok": True, "auto": interval})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path == "/api/writes":
            self.state.clear_writes()
        elif path == "/api/frames":
            self.state.frames.clear()
        else:
            return self.not_found()
        self.reply(200, {"ok": True})


def serve(state: SimState, host: str = "127.0.0.1", port: int = 5080) -> ThreadingHTTPServer:
    """Chạy kênh điều khiển ở luồng nền. port=0 để hệ điều hành tự chọn cổng."""
    handler = type("BoundControl", (Control,), {"state": state})   # mỗi simulator một lớp, không dùng chung
    srv = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
