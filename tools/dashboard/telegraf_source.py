"""NGUỒN TELEGRAF CỦA COLLECTOR — Telegraf thật đọc thiết bị, collector chỉ nhận số liệu và hiện lên trang.

Giống edge thật (và demo A04): Telegraf đọc Modbus TCP, Modbus RTU qua bộ chuyển serial ↔ Ethernet và SNMP theo
cấu hình sinh từ Point Map (generate.py). Khác edge thật ở đầu ra: gửi về collector (outputs.http ->
POST /api/telegraf) thay vì MQTT, để xem ngay trên trang 8080.

Telegraf chạy bằng Docker, image telegraf:1.32 (cùng bản demo A04), mạng host để tới được simulator
(127.0.1.x của make sim, hay 10.20.0.x của Docker demo A04) và collector. Thiết bị Telegraf không mở được vẫn do
Python đọc: BACnet (Telegraf không có plugin) và bus RS-485 nằm ở cổng serial ảo trên máy (không đưa vào container).
"""
import json, subprocess, time
from pathlib import Path
from generate import generate
from i18n import Translatable
from point_map import SOCKET, is_rtu, protocol

IMAGE = "telegraf:1.32"
AGENT_CONF = Path(__file__).resolve().parents[2] / "edge/collectors/telegraf/lab-collector.conf"
WORK_DIR = Path("var/telegraf")


class TelegrafError(Translatable):
    """Không chạy được Telegraf (không có Docker, image, cấu hình sai...)."""


def handled(cfg: dict) -> list[str]:
    """Thiết bị Telegraf đọc được: Modbus TCP, Modbus RTU qua TCP (cổng socket://) và SNMP."""
    out = []
    for d in cfg["devices"]:
        proto = protocol(d)
        if proto == "snmp" or (proto == "modbus" and (not is_rtu(d) or d["serial"]["port"].startswith(SOCKET))):
            out.append(d["name"])
    return out


def _metrics(payload) -> list[dict]:
    """outputs.http gửi {"metrics": [...]}; chấp nhận cả một metric, danh sách, hay JSON Lines."""
    if isinstance(payload, str):
        return [json.loads(x) for x in payload.splitlines() if x.strip()]
    if isinstance(payload, dict):
        return payload["metrics"] if isinstance(payload.get("metrics"), list) else [payload]
    return list(payload)


def ingest(payload, cfg: dict) -> dict:
    """Metric của Telegraf -> các dòng số liệu theo khóa điểm (thiết bị.điểm), như dòng của lượt đọc Python."""
    points = {f"{d['name']}.{p['name']}": p for d in cfg["devices"] for p in d["points"]}
    rows = {}
    for m in _metrics(payload):
        dev = (m.get("tags") or {}).get("device")
        ts = m.get("timestamp", time.time() * 1000) / 1000
        for field, value in (m.get("fields") or {}).items():
            key = f"{dev}.{field}"
            if key not in points or not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            rows[key] = {"value": round(value, 2), "ok": True, "unit": points[key].get("unit", ""),
                         "at": time.strftime("%H:%M:%S", time.localtime(ts)), "ts": ts, "source": "telegraf"}
    return rows


def docker_command(name: str, conf_dir: Path, collector_url: str, interval: int) -> list[str]:
    return ["docker", "run", "--rm", "-d", "--name", name, "--network", "host",
            "-e", f"COLLECTOR_URL={collector_url}", "-e", f"TELEGRAF_INTERVAL={interval}s",
            "-v", f"{AGENT_CONF}:/etc/telegraf/lab.conf:ro", "-v", f"{Path(conf_dir).resolve()}:/cfg:ro",
            IMAGE, "telegraf", "--config", "/etc/telegraf/lab.conf", "--config", "/cfg/devices.conf"]


def _docker(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise TelegrafError("telegraf.no_docker") from None
    except subprocess.TimeoutExpired:
        raise TelegrafError("telegraf.start_failed", detail=f"docker {args[0]} quá {timeout:g} giây") from None


class TelegrafRunner:
    """Một container Telegraf cho một collector (tên theo cổng web, nên nhiều collector không giẫm nhau)."""

    def __init__(self, collector_url: str, interval: int = 2, name: str = "modbus-lab-telegraf",
                 work_dir: Path = WORK_DIR):
        self.url, self.interval, self.name, self.work_dir = collector_url, interval, name, Path(work_dir)
        self.devices: list[str] = []

    def write_config(self, cfg: dict) -> Path:
        self.devices = handled(cfg)
        sub = dict(cfg, devices=[d for d in cfg["devices"] if d["name"] in self.devices])
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.chmod(0o755)                    # container chạy bằng user telegraf: cần đọc được
        out = self.work_dir / "devices.conf"
        out.write_text(generate(sub, inputs_only=True), encoding="utf-8")
        out.chmod(0o644)
        return out

    def start(self, cfg: dict) -> None:
        """Sinh cấu hình từ Point Map và chạy (lại) container. Lỗi -> TelegrafError có mã để trang web dịch."""
        self.write_config(cfg)
        self.stop()
        r = _docker(*docker_command(self.name, self.work_dir, self.url, self.interval)[1:])
        if r.returncode != 0:
            raise TelegrafError("telegraf.start_failed", detail=(r.stderr or r.stdout).strip()[-300:])

    def stop(self) -> None:
        try:
            _docker("rm", "-f", self.name, timeout=15)
        except TelegrafError:
            pass

    def running(self) -> bool:
        try:
            r = _docker("inspect", "-f", "{{.State.Running}}", self.name, timeout=5)
        except TelegrafError:
            return False
        return r.returncode == 0 and r.stdout.strip() == "true"

    def logs(self, n: int = 5) -> list[str]:
        """Vài dòng log cuối của Telegraf (lỗi đọc thiết bị hiện ở đây), bỏ dòng thông tin."""
        try:
            r = _docker("logs", "--tail", "50", self.name, timeout=5)
        except TelegrafError:
            return []
        lines = [x for x in (r.stdout + r.stderr).splitlines() if " E! " in x or " W! " in x]
        return lines[-n:]
