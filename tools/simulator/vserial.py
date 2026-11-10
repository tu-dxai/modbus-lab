"""CỔNG SERIAL ẢO — một "dây RS-485" giữa simulator và client, không cần phần cứng hay socat.

Tạo hai pseudo-terminal (pty) và một luồng chép byte qua lại giữa hai đầu. Simulator mở một đầu
(device_path); đầu kia có đường dẫn cố định `link` (ví dụ var/serial/ttyUSB0, theo environments/lab.yml)
để collector và Telegraf mở như mở cổng USB-RS485 thật.

Chỉ chạy trên Linux/macOS (cần pty).
"""
import os, pty, select, threading, tty
from pathlib import Path


class VirtualSerial:
    def __init__(self, link: str | Path):
        self.link = Path(link)
        m1, s1 = pty.openpty()
        m2, s2 = pty.openpty()
        for fd in (s1, s2):
            tty.setraw(fd)                             # không để line discipline sửa byte (CR/LF, echo...)
        self._fds = (m1, s1, m2, s2)
        self.device_path = os.ttyname(s1)              # đầu simulator mở
        self.client_path = os.ttyname(s2)              # đầu client, được trỏ tới từ `link`
        self.link.parent.mkdir(parents=True, exist_ok=True)
        if self.link.is_symlink() or self.link.exists():
            self.link.unlink()
        self.link.symlink_to(self.client_path)
        threading.Thread(target=self._bridge, args=(m1, m2), daemon=True).start()

    @staticmethod
    def _bridge(a: int, b: int) -> None:
        while True:
            ready, _, _ = select.select([a, b], [], [])
            for src, dst in ((a, b), (b, a)):
                if src in ready:
                    try:
                        os.write(dst, os.read(src, 4096))
                    except OSError:                    # đầu kia đóng: bỏ qua, chờ mở lại
                        pass
