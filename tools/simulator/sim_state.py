"""TRẠNG THÁI SIMULATOR — giá trị hiện tại của mọi điểm và nhật ký lệnh ghi (nhân chứng).

Tách khỏi sim.py để sim.py (chạy trực tiếp) và sim_control.py dùng chung đúng một lớp.
"""
import math, random, struct, threading, time
from datetime import datetime
from codec import SIZE, decode, encode
from frames import FrameLog
from i18n import Translatable
from point_map import device_meta, point_ref

# Mọi lệnh ghi Modbus mà nhân chứng ghi lại: 6/16 (thanh ghi), 22 (mask write), 23 (đọc + ghi nhiều thanh ghi);
# 5/15 (coil) — thiết bị giả không có coil ghi được nên luôn bị từ chối, nhưng vẫn phải có trong nhật ký.
WRITE_FC = {5, 6, 15, 16, 22, 23}


class UnknownPoint(Translatable):
    """Điểm không có trong Point Map."""


class BadValue(Translatable):
    """Giá trị không ghi vừa thanh ghi theo kiểu dữ liệu và hệ số của điểm."""


class UnknownDevice(Translatable):
    """Thiết bị không có trong Point Map."""


def _round(v: float) -> float:
    return round(v, 6)                                 # bỏ đuôi sai số dấu phẩy động khi nhân hệ số


def _overlaps(p: dict, start: int, count: int) -> bool:
    return p["address"] < start + count and start < p["address"] + SIZE[p["type"]]


def endpoint(d: dict) -> str:
    """Địa chỉ simulator của thiết bị: host:port (TCP) hoặc rtu:<cổng serial>; cùng gateway / bus thì cùng endpoint."""
    if d.get("transport") == "rtu":
        return f"rtu:{d['serial']['port']}"
    return f"{d['host']}:{d['port']}"


class SimState:
    """Giá trị hiện tại của mọi điểm và nhật ký lệnh ghi.

    Dùng chung giữa luồng Modbus (asyncio) và luồng HTTP điều khiển, nên mọi truy cập đi qua self.lock.
    """

    AUTO_MAX = 3600

    def __init__(self, cfg: dict, frames: int = 500, auto: int = 0):
        self.cfg = cfg
        self.auto = auto                                   # giây giữa hai lần tự thay đổi; 0 = chỉ đặt bằng tay
        self.lock = threading.Lock()
        self.points = {f"{d['name']}.{p['name']}": (d, p) for d in cfg["devices"] for p in d["points"]}
        self.devices = {(endpoint(d), d.get("device_id")): d for d in cfg["devices"]}
        self.values: dict[str, float] = {}
        self.anchor: dict[str, float] = {}                 # giá trị đặt gần nhất: tâm dao động khi tự thay đổi
        self.hooks: dict[str, list] = {}                   # điểm -> hàm gọi khi đặt bằng tay (thiết bị BACnet)
        self.reset_hooks: list = []                        # hàm gọi khi đặt lại (xóa mảng ưu tiên BACnet)
        self.off: set[str] = set()                         # thiết bị đang tắt (giả lập mất điện)
        self.power_lock = threading.Lock()                 # bật / tắt lần lượt: kiểm tra, đổi, mở/đóng server
        self.power_hooks: dict[str, list] = {}             # thiết bị -> hàm gọi khi bật/tắt (server TCP riêng)
        self.log: list[dict] = []
        self.pending: dict[tuple, dict] = {}               # (endpoint, device_id, transaction_id) -> lệnh chờ phản hồi
        self.seq = 0                                       # tăng mãi, không về 0 khi reset, để client hỏi "since"
        self.frames = FrameLog(self.devices, frames)       # khung tin thô gần nhất (trace_packet)
        self.reset()

    # ---------- giá trị ----------
    def reset(self) -> None:
        """Về giá trị khởi đầu trong Point Map, xóa nhật ký lệnh ghi và khung tin."""
        with self.lock:
            self.values = {k: p.get("sim", {}).get("base", 0) for k, (d, p) in self.points.items()}
            self.anchor = dict(self.values)
            self.log.clear()
            self.pending.clear()
        self.frames.clear()
        for hook in getattr(self, "reset_hooks", []):
            hook()
        for name in list(getattr(self, "off", ())):         # đặt lại = bật lại mọi thiết bị
            self.set_power(name, True)

    # ---------- bật / tắt thiết bị ----------
    def is_on(self, name: str) -> bool:
        return name not in self.off

    def set_power(self, name: str, on: bool) -> None:
        """Bật / tắt thiết bị. Thiết bị tắt phản ứng như mất điện, theo kiểu kết nối (xem sim.py)."""
        if name not in {d["name"] for d in self.cfg["devices"]}:
            raise UnknownDevice("sim.unknown_device", device=name)
        with self.power_lock:                              # hai lệnh bật/tắt cùng lúc không làm lệch trạng thái
            if self.is_on(name) == on:
                return
            with self.lock:
                (self.off.discard if on else self.off.add)(name)
            for hook in self.power_hooks.get(name, []):
                hook(on)

    def _quantize(self, key: str, value) -> float:
        """Giá trị thiết bị thật sẽ báo sau khi lưu (ví dụ 231.55 V lưu x10 -> 231.6)."""
        d, p = self.points[key]
        scale = p.get("scale", 1)
        try:
            finite = math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            finite = False
        if not finite:                                     # NaN / vô cực: JSON trả về sẽ hỏng, trang ngừng cập nhật
            raise BadValue("sim.bad_value", key=key, value=str(value), type=p.get("type", "?"), scale=scale)
        if d.get("protocol") in ("snmp", "bacnet"):
            return self._quantize_typed(key, d, p, value, scale)
        try:
            regs = encode(float(value), p["type"], d["byte_order"], scale)
        except (struct.error, ValueError, TypeError, OverflowError):
            raise BadValue("sim.bad_value", key=key, value=value, type=p["type"], scale=scale) from None
        return _round(decode(regs, p["type"], d["byte_order"], scale))

    INT_RANGES = {"integer": (-2**31, 2**31 - 1), "gauge32": (0, 2**32 - 1), "counter32": (0, 2**32 - 1)}

    def _quantize_typed(self, key: str, d: dict, p: dict, value, scale) -> float:
        """SNMP: số nguyên theo hệ số (Integer32 / Gauge32 / Counter32). BACnet: số thực (REAL) hoặc 0/1."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise BadValue("sim.bad_value", key=key, value=value, type=p.get("type", "?"), scale=scale) from None
        if d.get("protocol") == "snmp":
            raw = round(v / scale) if v == v else None    # NaN không phải số nguyên
            lo, hi = self.INT_RANGES[p["type"]]
            if raw is None or not lo <= raw <= hi:
                raise BadValue("sim.bad_value", key=key, value=value, type=p["type"], scale=scale)
            return _round(raw * scale)
        if p.get("type") == "binary":
            if v not in (0, 1):
                raise BadValue("sim.bad_value", key=key, value=value, type="binary", scale=1)
            return int(v)
        return _round(v)

    def raw_int(self, key: str) -> int:
        """Số nguyên thiết bị SNMP trả về (giá trị / hệ số)."""
        d, p = self.points[key]
        with self.lock:
            return round(self.values[key] / p.get("scale", 1))

    def set_many(self, values: dict) -> dict:
        """Đặt nhiều điểm cùng lúc; một điểm sai thì không điểm nào đổi."""
        unknown = [k for k in values if k not in self.points]
        if unknown:
            raise UnknownPoint("sim.unknown_points", keys=unknown)
        new = {k: self._quantize(k, v) for k, v in values.items()}
        with self.lock:
            self.values.update(new)
            self.anchor.update(new)
        for k, v in new.items():
            for hook in self.hooks.get(k, []):
                hook(v)
        return new

    def on_set(self, key: str, hook) -> None:
        """Đăng ký hàm được gọi khi điểm `key` được đặt bằng tay (ví dụ đổi relinquishDefault của BACnet)."""
        self.hooks.setdefault(key, []).append(hook)

    def set_from_device(self, key: str, value) -> None:
        """Thiết bị tự đổi giá trị (BACnet sau lệnh ghi / nhả lệnh): cập nhật giá trị báo ra."""
        with self.lock:
            self.values[key] = value
            self.anchor[key] = value

    def record_external_write(self, ep, site_ep, d, key, function, address, value, before, accepted,
                              exception=None, priority=None) -> None:
        """Lệnh ghi không đi qua Modbus (BACnet WriteProperty) vào cùng nhật ký lệnh ghi."""
        entry = {"at": datetime.now().isoformat(timespec="milliseconds"), "endpoint": ep, "site_endpoint": site_ep,
                 "device": d["name"], "device_id": d.get("device_instance"), "function": function,
                 "address": address, "registers": [], "points": [{"key": key, "before": before, "value": value}],
                 "accepted": accepted, "exception": exception, "priority": priority}
        with self.lock:
            self.seq += 1
            self.log.append({"seq": self.seq, **entry})

    # ---------- tự thay đổi giá trị ----------
    def tick(self) -> None:
        """Một nhịp tự thay đổi: điểm có sim.noise lấy giá trị ngẫu nhiên trong neo ± noise.

        Điểm writable (giá trị client ghi vào, ví dụ chế độ vận hành) giữ nguyên.
        """
        with self.lock:                                   # giữ khóa cả lúc tính: không ghi đè giá trị vừa đặt tay
            for key, (d, p) in self.points.items():
                noise = p.get("sim", {}).get("noise", 0)
                if p.get("writable") or not noise:
                    continue
                v = self.anchor[key] + random.uniform(-noise, noise)
                if p.get("type", "float32") == "float32":   # BACnet analog (REAL) cũng là số thực
                    v = round(v, 2)                       # số đo thật hiếm khi có nhiều số lẻ hơn
                try:
                    self.values[key] = self._quantize(key, v)
                except BadValue:                          # ra ngoài khoảng kiểu dữ liệu: giữ giá trị cũ
                    pass

    def run_auto(self) -> None:
        """Luồng nền: tự thay đổi mỗi self.auto giây; self.auto = 0 thì nằm chờ."""
        last = time.monotonic()
        while True:
            if self.auto and time.monotonic() - last >= self.auto:
                last = time.monotonic()
                self.tick()
            elif not self.auto:
                last = time.monotonic()
            time.sleep(0.1)

    def snapshot(self) -> dict:
        with self.lock:
            values = dict(self.values)
        out = {}
        for key, (d, p) in self.points.items():
            row = {"device": d["name"], "device_label": d["label"], "label": p["label"],
                   "protocol": d.get("protocol", "modbus"), "ref": point_ref(d, p),
                   "device_id": d.get("device_id"), "byte_order": d.get("byte_order"),
                   "device_meta": device_meta(d),
                   "endpoint": endpoint(d), "site_endpoint": d.get("site_address", endpoint(d)),
                   "table": p.get("table"), "address": p.get("address"), "type": p.get("type"), "unit": p.get("unit", ""),
                   "writable": bool(p.get("writable")), "value": values[key], "on": self.is_on(d["name"])}
            for k in ("allowed", "min", "max", "priority"):
                if k in p:
                    row[k] = p[k]
            out[key] = row
        return out

    # ---------- phục vụ Modbus ----------
    def fill(self, d: dict, table: str, start_address: int, registers: list[int]) -> None:
        """Lệnh đọc: ghi giá trị hiện tại của các điểm trong bảng vào thanh ghi."""
        with self.lock:
            self._fill(d, table, start_address, registers)

    def _fill(self, d: dict, table: str, start_address: int, registers: list[int]) -> None:
        for p in d["points"]:
            if p["table"] == table:
                key = f"{d['name']}.{p['name']}"
                regs = encode(self.values[key], p["type"], d["byte_order"], p.get("scale", 1))
                i = p["address"] - start_address
                registers[i:i + len(regs)] = regs

    def apply_write(self, d: dict, table: str, start_address: int, registers: list[int],
                    address: int, set_values: list[int]) -> None:
        """Lệnh ghi đã qua kiểm tra của thiết bị: cập nhật giá trị các điểm bị ghi (kể cả ghi một nửa điểm 32 bit)."""
        with self.lock:
            # Thanh ghi pymodbus giữ là nội dung của lần ĐỌC trước, không phải giá trị hiện tại (đặt tay, tự thay đổi
            # sau đó): điền lại giá trị hiện tại trước, để ghi một nửa điểm 32 bit ghép với nửa còn lại đúng.
            merged = list(registers)
            self._fill(d, table, start_address, merged)
            merged[address - start_address:address - start_address + len(set_values)] = set_values
            for p in d["points"]:
                if p["table"] == table and _overlaps(p, address, len(set_values)):
                    i = p["address"] - start_address
                    regs = merged[i:i + SIZE[p["type"]]]
                    key = f"{d['name']}.{p['name']}"
                    self.values[key] = self.anchor[key] = _round(
                        decode(regs, p["type"], d["byte_order"], p.get("scale", 1)))

    # ---------- nhân chứng ----------
    def tracer(self, ep: str, site_ep: str):
        """Hook trace_pdu cho server ở endpoint `ep`: pymodbus gọi với mọi PDU nhận và gửi.

        trace_pdu.unanswered(pdu): lệnh tới thiết bị đang tắt trên bus (không ai trả lời) — vẫn vào nhật ký."""
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

        def unanswered(pdu) -> None:
            try:
                if pdu.function_code in WRITE_FC:
                    self._requested(ep, site_ep, pdu)
                    self._close(ep, pdu, accepted=False, exception=None, no_response=True)
            except Exception as e:
                print(f"  ?? simulator: không ghi được nhật ký lệnh ghi: {e!r}")
        trace_pdu.unanswered = unanswered
        return trace_pdu

    def _written_registers(self, d: dict | None, pdu) -> tuple[int, list[int]]:
        """(ô đầu, các thanh ghi sẽ được ghi) của lệnh ghi; coil (FC5/15) không có thanh ghi."""
        fc = pdu.function_code
        if fc in (5, 15):
            return pdu.address, []
        if fc == 23:
            return pdu.write_address, list(pdu.write_registers)
        if fc == 22:                                   # mask write: tính giá trị mới từ giá trị hiện tại
            reg = 0                                    # ô không khai báo: thiết bị sẽ từ chối, giá trị không quan trọng
            for p in (d["points"] if d else []):
                if p["table"] == "holding" and _overlaps(p, pdu.address, 1):
                    regs = encode(self.values[f"{d['name']}.{p['name']}"], p["type"], d["byte_order"], p.get("scale", 1))
                    reg = regs[pdu.address - p["address"]]
            return pdu.address, [(reg & pdu.and_mask) | (pdu.or_mask & ~pdu.and_mask & 0xFFFF)]
        return pdu.address, list(pdu.registers)

    def _requested(self, ep: str, site_ep: str, pdu) -> None:
        d = self.devices.get((ep, pdu.dev_id))
        points = []
        with self.lock:
            start, regs = self._written_registers(d, pdu)
            for p in (d["points"] if d and regs else []):
                if p["table"] == "holding" and _overlaps(p, start, len(regs)):
                    key = f"{d['name']}.{p['name']}"
                    i, n = p["address"] - start, SIZE[p["type"]]
                    full = 0 <= i and i + n <= len(regs)       # ghi đủ mọi ô của điểm?
                    value = _round(decode(regs[i:i + n], p["type"], d["byte_order"], p.get("scale", 1))) if full else None
                    points.append({"key": key, "before": self.values[key], "value": value})
            entry = {"at": datetime.now().isoformat(timespec="milliseconds"),
                     "endpoint": ep, "site_endpoint": site_ep,
                     "device": d["name"] if d else None, "device_id": pdu.dev_id,
                     "function": pdu.function_code, "address": start, "registers": regs, "points": points}
            if pdu.function_code in (5, 15):
                entry["coils"] = [bool(b) for b in pdu.bits]
            self.pending[(ep, pdu.dev_id, pdu.transaction_id)] = entry

    def _answered(self, ep: str, pdu) -> None:
        rejected = bool(pdu.function_code & 0x80)
        self._close(ep, pdu, accepted=not rejected, exception=pdu.exception_code if rejected else None)

    def _close(self, ep: str, pdu, accepted: bool, exception, no_response: bool = False) -> None:
        with self.lock:
            entry = self.pending.pop((ep, pdu.dev_id, pdu.transaction_id), None)
            if entry is None:
                return
            self.seq += 1
            self.log.append({"seq": self.seq, **entry, "accepted": accepted, "exception": exception,
                             **({"no_response": True} if no_response else {})})

    def writes(self, point: str | None = None, since: int | None = None) -> list[dict]:
        with self.lock:
            return [w for w in self.log
                    if (since is None or w["seq"] > since)
                    and (point is None or any(p["key"] == point for p in w["points"]))]

    def clear_writes(self) -> None:
        with self.lock:
            self.log.clear()
