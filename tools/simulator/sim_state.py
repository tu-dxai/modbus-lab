"""TRẠNG THÁI SIMULATOR — giá trị hiện tại của mọi điểm và nhật ký lệnh ghi (nhân chứng).

Tách khỏi sim.py để sim.py (chạy trực tiếp) và sim_control.py dùng chung đúng một lớp.
"""
import random, struct, threading, time
from datetime import datetime
from codec import SIZE, decode, encode

WRITE_FC = {6, 16}


class UnknownPoint(Exception):
    """Điểm không có trong Point Map."""


class BadValue(Exception):
    """Giá trị không ghi vừa thanh ghi theo kiểu dữ liệu và hệ số của điểm."""


def _round(v: float) -> float:
    return round(v, 6)                                 # bỏ đuôi sai số dấu phẩy động khi nhân hệ số


def _overlaps(p: dict, start: int, count: int) -> bool:
    return p["address"] < start + count and start < p["address"] + SIZE[p["type"]]


def endpoint(d: dict) -> str:
    """Địa chỉ simulator của thiết bị (host:port); thiết bị cùng gateway có cùng endpoint."""
    return f"{d['host']}:{d['port']}"


class SimState:
    """Giá trị hiện tại của mọi điểm và nhật ký lệnh ghi.

    Dùng chung giữa luồng Modbus (asyncio) và luồng HTTP điều khiển, nên mọi truy cập đi qua self.lock.
    """

    def __init__(self, cfg: dict, noise: bool = False):
        self.cfg, self.noise, self.t0 = cfg, noise, time.monotonic()
        self.lock = threading.Lock()
        self.points = {f"{d['name']}.{p['name']}": (d, p) for d in cfg["devices"] for p in d["points"]}
        self.devices = {(endpoint(d), d["device_id"]): d for d in cfg["devices"]}
        self.values: dict[str, float] = {}
        self.log: list[dict] = []
        self.pending: dict[tuple, dict] = {}               # (endpoint, device_id, transaction_id) -> lệnh chờ phản hồi
        self.seq = 0                                       # tăng mãi, không về 0 khi reset, để client hỏi "since"
        self.reset()

    # ---------- giá trị ----------
    def reset(self) -> None:
        """Về giá trị khởi đầu trong Point Map và xóa nhật ký."""
        with self.lock:
            self.values = {k: p.get("sim", {}).get("base", 0) for k, (d, p) in self.points.items()}
            self.log.clear()
            self.pending.clear()

    def _quantize(self, key: str, value) -> float:
        """Giá trị thiết bị thật sẽ báo sau khi lưu vào thanh ghi (ví dụ 231.55 V lưu x10 -> 231.6)."""
        d, p = self.points[key]
        scale = p.get("scale", 1)
        try:
            regs = encode(float(value), p["type"], d["byte_order"], scale)
        except (struct.error, ValueError, TypeError, OverflowError):
            raise BadValue(f"{key}: giá trị {value} không vừa kiểu {p['type']} với hệ số {scale}") from None
        return _round(decode(regs, p["type"], d["byte_order"], scale))

    def set_many(self, values: dict) -> dict:
        """Đặt nhiều điểm cùng lúc; một điểm sai thì không điểm nào đổi."""
        unknown = [k for k in values if k not in self.points]
        if unknown:
            raise UnknownPoint(f"không có điểm {', '.join(repr(k) for k in unknown)} trong Point Map")
        new = {k: self._quantize(k, v) for k, v in values.items()}
        with self.lock:
            self.values.update(new)
        return new

    def snapshot(self) -> dict:
        with self.lock:
            values = dict(self.values)
        out = {}
        for key, (d, p) in self.points.items():
            row = {"device": d["name"], "device_id": d["device_id"], "byte_order": d["byte_order"],
                   "endpoint": endpoint(d), "site_endpoint": d.get("site_address", endpoint(d)),
                   "table": p["table"], "address": p["address"], "type": p["type"], "unit": p.get("unit", ""),
                   "writable": bool(p.get("writable")), "value": values[key]}
            for k in ("allowed", "min", "max"):
                if k in p:
                    row[k] = p[k]
            out[key] = row
        return out

    def _reported(self, key: str, p: dict) -> float:
        """Giá trị trả cho lệnh đọc: giá trị hiện tại, cộng nhiễu nếu bật --noise (trừ điểm writable)."""
        v = self.values[key]
        if self.noise and not p.get("writable"):
            s = p.get("sim", {})
            t = time.monotonic() - self.t0
            v += s.get("drift", 0) * (int(t) % 30) + random.uniform(-1, 1) * s.get("noise", 0)
        return v

    # ---------- phục vụ Modbus ----------
    def fill(self, d: dict, table: str, start_address: int, registers: list[int]) -> None:
        """Lệnh đọc: ghi giá trị hiện tại của các điểm trong bảng vào thanh ghi."""
        with self.lock:
            for p in d["points"]:
                if p["table"] == table:
                    key = f"{d['name']}.{p['name']}"
                    regs = encode(self._reported(key, p), p["type"], d["byte_order"], p.get("scale", 1))
                    i = p["address"] - start_address
                    registers[i:i + len(regs)] = regs

    def apply_write(self, d: dict, table: str, start_address: int, registers: list[int],
                    address: int, set_values: list[int]) -> None:
        """Lệnh ghi đã qua kiểm tra của thiết bị: cập nhật giá trị các điểm bị ghi (kể cả ghi một nửa điểm 32 bit)."""
        merged = list(registers)
        merged[address - start_address:address - start_address + len(set_values)] = set_values
        with self.lock:
            for p in d["points"]:
                if p["table"] == table and _overlaps(p, address, len(set_values)):
                    i = p["address"] - start_address
                    regs = merged[i:i + SIZE[p["type"]]]
                    self.values[f"{d['name']}.{p['name']}"] = _round(
                        decode(regs, p["type"], d["byte_order"], p.get("scale", 1)))

    # ---------- nhân chứng ----------
    def tracer(self, ep: str, site_ep: str):
        """Hook trace_pdu cho server ở endpoint `ep`: pymodbus gọi với mọi PDU nhận và gửi."""
        def trace_pdu(sending: bool, pdu):
            try:                                       # lỗi ở nhân chứng không được làm sập thiết bị giả
                if (pdu.function_code & 0x7F) in WRITE_FC:
                    if sending:
                        self._answered(ep, pdu)
                    else:
                        self._requested(ep, site_ep, pdu)
            except Exception as e:
                print(f"  ?? simulator: không ghi được nhật ký lệnh ghi: {e!r}")
            return pdu
        return trace_pdu

    def _requested(self, ep: str, site_ep: str, pdu) -> None:
        d = self.devices.get((ep, pdu.dev_id))
        regs = list(pdu.registers)
        points = []
        with self.lock:
            for p in (d["points"] if d else []):
                if p["table"] == "holding" and _overlaps(p, pdu.address, len(regs)):
                    key = f"{d['name']}.{p['name']}"
                    i, n = p["address"] - pdu.address, SIZE[p["type"]]
                    full = 0 <= i and i + n <= len(regs)       # ghi đủ mọi ô của điểm?
                    value = _round(decode(regs[i:i + n], p["type"], d["byte_order"], p.get("scale", 1))) if full else None
                    points.append({"key": key, "before": self.values[key], "value": value})
            self.pending[(ep, pdu.dev_id, pdu.transaction_id)] = {
                "at": datetime.now().isoformat(timespec="milliseconds"),
                "endpoint": ep, "site_endpoint": site_ep,
                "device": d["name"] if d else None, "device_id": pdu.dev_id,
                "function": pdu.function_code, "address": pdu.address, "registers": regs, "points": points}

    def _answered(self, ep: str, pdu) -> None:
        with self.lock:
            entry = self.pending.pop((ep, pdu.dev_id, pdu.transaction_id), None)
            if entry is None:
                return
            rejected = bool(pdu.function_code & 0x80)
            self.seq += 1
            self.log.append({"seq": self.seq, **entry, "accepted": not rejected,
                             "exception": pdu.exception_code if rejected else None})

    def writes(self, point: str | None = None, since: int | None = None) -> list[dict]:
        with self.lock:
            return [w for w in self.log
                    if (since is None or w["seq"] > since)
                    and (point is None or any(p["key"] == point for p in w["points"]))]

    def clear_writes(self) -> None:
        with self.lock:
            self.log.clear()
