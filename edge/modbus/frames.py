"""KHUNG TIN MODBUS TCP — từng byte client gửi tới và thiết bị trả về, trước khi giải mã.

Một khung tin Modbus TCP (ADU) gồm:
  MBAP 7 byte:  mã giao dịch (2) | giao thức, luôn 0 (2) | độ dài phần còn lại (2) | unit ID (1)
  PDU:          mã lệnh (1) | dữ liệu theo từng lệnh
Phản hồi lỗi: mã lệnh + 0x80, theo sau một byte mã lỗi (ví dụ 83 02 = đọc holding lỗi 02).

Ví dụ đọc điện áp (holding 0, 1 ô, hệ số 0.1):
  Gửi : 00 01 | 00 00 | 00 06 | 01 | 03 | 00 00 | 00 01
  Nhận: 00 01 | 00 00 | 00 05 | 01 | 03 | 02    | 09 01      09 01 = 2305 -> 230.5 V

FrameLog nhận byte thô qua hook trace_packet của pymodbus (mỗi endpoint một hook), ghép lệnh với
phản hồi theo (endpoint, mã giao dịch), và giữ `limit` cặp gần nhất. Dùng ở cả phía thiết bị
(simulator) và phía client (collector); phía client còn ghi timeout và lỗi kết nối.
"""
import threading, time
from collections import deque
from datetime import datetime
from codec import SIZE, decode

MBAP_SIZE = 7
READ_FC = {3: "holding", 4: "input"}
KNOWN_FC = {3, 4, 6, 16}
KNOWN_EXC = {1, 2, 3, 4, 6, 10, 11}


def _u16(b: bytes, i: int) -> int:
    return int.from_bytes(b[i:i + 2], "big")


def _regs(b: bytes) -> list[int]:
    return [_u16(b, i) for i in range(0, len(b) - 1, 2)]


def split_adus(data: bytes) -> list[bytes]:
    """Tách một gói TCP thành từng khung tin theo trường độ dài của MBAP."""
    out, i = [], 0
    while i < len(data):
        if len(data) - i < MBAP_SIZE:
            out.append(data[i:])
            break
        n = 6 + _u16(data, i + 4)
        out.append(data[i:i + n])
        i += n
    return out


def parse_adu(adu: bytes, response: bool) -> dict:
    """Tách khung tin thành các trường (tên + byte hex) và các số đã đọc ra."""
    r = {"hex": adu.hex(" "), "fields": [], "transaction": None, "unit": None, "function": None,
         "exception": None, "start": None, "quantity": None, "registers": [], "malformed": False}

    def add(name: str, a: int, b: int) -> None:
        r["fields"].append({"name": name, "hex": adu[a:b].hex(" ")})

    def malformed() -> dict:
        r.update(malformed=True, fields=[{"name": "raw", "hex": adu.hex(" ")}], registers=[])
        return r

    if len(adu) < MBAP_SIZE + 1 or 6 + _u16(adu, 4) != len(adu):
        return malformed()
    add("transaction", 0, 2); add("protocol", 2, 4); add("length", 4, 6); add("unit", 6, 7); add("function", 7, 8)
    r["transaction"], r["unit"] = _u16(adu, 0), adu[6]
    fc = adu[7]
    r["function"] = fc & 0x7F
    body = len(adu) - 8                                # số byte sau mã lệnh
    if fc & 0x80:                                      # phản hồi lỗi
        if body != 1:
            return malformed()
        add("exception", 8, 9)
        r["exception"] = adu[8]
    elif fc in READ_FC and not response:               # đọc: ô đầu, số ô
        if body != 4:
            return malformed()
        add("start", 8, 10); add("quantity", 10, 12)
        r["start"], r["quantity"] = _u16(adu, 8), _u16(adu, 10)
    elif fc in READ_FC:                                # trả lời đọc: số byte, dữ liệu
        if body < 1 or adu[8] != body - 1:
            return malformed()
        add("byte_count", 8, 9); add("data", 9, len(adu))
        r["registers"] = _regs(adu[9:])
        r["quantity"] = len(r["registers"])
    elif fc == 6:                                      # ghi một ô; phản hồi lặp lại y hệt
        if body != 4:
            return malformed()
        add("address", 8, 10); add("value", 10, 12)
        r["start"], r["quantity"], r["registers"] = _u16(adu, 8), 1, [_u16(adu, 10)]
    elif fc == 16 and not response:                    # ghi nhiều ô: ô đầu, số ô, số byte, giá trị
        if body < 5 or adu[12] != body - 5:
            return malformed()
        add("start", 8, 10); add("quantity", 10, 12); add("byte_count", 12, 13); add("values", 13, len(adu))
        r["start"], r["quantity"], r["registers"] = _u16(adu, 8), _u16(adu, 10), _regs(adu[13:])
    elif fc == 16:                                     # xác nhận ghi nhiều ô: ô đầu, số ô
        if body != 4:
            return malformed()
        add("start", 8, 10); add("quantity", 10, 12)
        r["start"], r["quantity"] = _u16(adu, 8), _u16(adu, 10)
    elif body:
        add("data", 8, len(adu))
    return r


def crc16(data: bytes) -> int:
    """CRC-16/Modbus (đa thức 0xA001, khởi đầu 0xFFFF) — 2 byte cuối khung RTU, byte thấp trước."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def parse_rtu(frame: bytes, response: bool) -> dict:
    """Khung Modbus RTU: unit (1) | mã lệnh (1) | dữ liệu | CRC (2). Không có MBAP như Modbus TCP.

    Tách bằng cách dựng tạm MBAP rồi dùng chung parse_adu, sau đó thay ba trường MBAP bằng CRC ở cuối.
    """
    if len(frame) < 4:
        return {"hex": frame.hex(" "), "fields": [{"name": "raw", "hex": frame.hex(" ")}], "transaction": 0,
                "unit": None, "function": None, "exception": None, "start": None, "quantity": None,
                "registers": [], "malformed": True}
    pdu, crc = frame[:-2], frame[-2:]
    r = parse_adu(bytes([0, 0, 0, 0]) + (len(pdu)).to_bytes(2, "big") + pdu, response)
    r["hex"], r["transaction"] = frame.hex(" "), 0
    if r["malformed"]:
        r["fields"] = [{"name": "raw", "hex": frame.hex(" ")}]
        return r
    r["fields"] = [f for f in r["fields"] if f["name"] not in ("transaction", "protocol", "length")]
    r["fields"].append({"name": "crc", "hex": crc.hex(" ")})
    if crc16(pdu) != int.from_bytes(crc, "little"):
        r["malformed"] = True                          # CRC sai: nhiễu đường truyền hoặc khung bị cắt
    return r


def summary(r: dict, response: bool) -> dict:
    """Một câu tóm tắt dạng khóa từ điển + tham số, để dòng lệnh và trang web tự dịch."""
    fc = r["function"]
    if r["malformed"]:
        return {"key": "frame.sum.malformed", "params": {}}
    if r["exception"] is not None:
        code = r["exception"]
        if code in KNOWN_EXC:
            return {"key": f"frame.exc.{code}", "params": {}}
        return {"key": "frame.exc.other", "params": {"code": f"{code:02X}"}}
    if fc in READ_FC:
        if response:
            return {"key": "frame.sum.registers", "params": {"count": r["quantity"]}}
        return {"key": "frame.sum.read", "params": {"table": READ_FC[fc], "start": r["start"], "count": r["quantity"]}}
    if fc == 6:
        key = "frame.sum.write_single_ack" if response else "frame.sum.write_single"
        return {"key": key, "params": {"address": r["start"], "value": r["registers"][0]}}
    if fc == 16:
        if response:
            return {"key": "frame.sum.write_multi_ack", "params": {"start": r["start"], "count": r["quantity"]}}
        return {"key": "frame.sum.write_multi",
                "params": {"start": r["start"], "count": r["quantity"], "values": r["registers"]}}
    return {"key": "frame.sum.other", "params": {"fc": f"{fc:02X}"}}


def explain(d: dict | None, req: dict, resp: dict) -> list[dict]:
    """Các điểm đo mà thanh ghi trong khung tin chứa trọn: byte thô -> số nguyên -> giá trị sau hệ số."""
    if d is None or req["malformed"] or resp["malformed"] or resp["exception"] is not None:
        return []
    fc = req["function"]
    if fc in READ_FC:
        table, start, regs = READ_FC[fc], req["start"], resp["registers"]
    elif fc in (6, 16):
        table, start, regs = "holding", req["start"], req["registers"]
    else:
        return []
    out = []
    for p in d["points"]:
        n = SIZE[p["type"]]
        i = p["address"] - start
        if p["table"] != table or i < 0 or i + n > len(regs):
            continue
        part = regs[i:i + n]
        raw = decode(part, p["type"], d["byte_order"], 1)
        scale = p.get("scale", 1)
        out.append({"key": f"{d['name']}.{p['name']}", "label": p.get("label"),
                    "hex": b"".join(x.to_bytes(2, "big") for x in part).hex(" "),
                    "raw": round(raw, 6) if isinstance(raw, float) else raw,
                    "value": round(decode(part, p["type"], d["byte_order"], scale), 6),
                    "unit": p.get("unit", ""), "type": p["type"], "byte_order": d["byte_order"], "scale": scale})
    return out


class FrameLog:
    """Các cặp hỏi/đáp gần nhất, dùng chung giữa luồng Modbus và luồng HTTP.

    Dùng được ở hai phía:
      - thiết bị (simulator):   tracer(ep, site_ep)              — byte nhận vào là yêu cầu, byte gửi ra là phản hồi
      - client (collector):     tracer(ep, site_ep, client=True) — byte gửi ra là yêu cầu, byte nhận vào là phản hồi
    Phía client còn ghi được sự cố mà thiết bị không thấy: yêu cầu không có phản hồi (expire) và
    địa chỉ không kết nối được (event). Các mục đó có "status" khác None.
    """

    MAX_PENDING = 1000                                 # lệnh chưa có phản hồi; quá số này thì bỏ bớt

    def __init__(self, devices: dict, limit: int = 500):
        self.devices = devices                         # (endpoint, device_id) -> thiết bị trong Point Map
        self.entries: deque = deque(maxlen=limit)
        self.pending: dict[tuple, tuple] = {}          # (endpoint, mã giao dịch) -> (t0, lúc, yêu cầu, site_ep)
        self.seq = 0                                   # tăng mãi, không về 0 khi xóa, để hỏi "since"
        self.lock = threading.Lock()

    def tracer(self, ep: str, site_ep: str, client: bool = False, rtu: bool = False):
        """Hook trace_packet của pymodbus cho endpoint `ep`. Không bao giờ được làm hỏng byte hay ném lỗi.

        rtu=True: khung Modbus RTU (có CRC, không có mã giao dịch); một bus chỉ có một lệnh chờ tại một lúc.
        """
        def trace_packet(sending: bool, data: bytes) -> bytes:
            try:
                for adu in ([data] if rtu else split_adus(data)):
                    if sending != client:              # thiết bị gửi ra / client nhận vào: phản hồi
                        self._answered(ep, adu, rtu)
                    else:
                        self._requested(ep, site_ep, adu, rtu)
            except Exception as e:
                print(f"  ?? không ghi được khung tin: {e!r}")
            return data
        return trace_packet

    def _requested(self, ep: str, site_ep: str, adu: bytes, rtu: bool = False) -> None:
        req = parse_rtu(adu, response=False) if rtu else parse_adu(adu, response=False)
        with self.lock:
            if len(self.pending) >= self.MAX_PENDING:
                self.pending.clear()
            self.pending[(ep, req["transaction"])] = (time.perf_counter(), datetime.now(), req, site_ep)

    def _answered(self, ep: str, adu: bytes, rtu: bool = False) -> None:
        resp = parse_rtu(adu, response=True) if rtu else parse_adu(adu, response=True)
        with self.lock:
            item = self.pending.pop((ep, resp["transaction"]), None)
        if item is not None:
            t0, at, req, site_ep = item
            self._add(ep, site_ep, at, t0, req, resp)

    def expire(self, ep: str, status: dict) -> None:
        """Client hết chờ: mọi yêu cầu còn treo ở `ep` thành mục không có phản hồi, kèm lý do."""
        with self.lock:
            items = [self.pending.pop(k) for k in [k for k in self.pending if k[0] == ep]]
        for t0, at, req, site_ep in items:
            self._add(ep, site_ep, at, t0, req, None, status)

    def event(self, ep: str, site_ep: str, device_id: int, status: dict) -> None:
        """Sự cố không có byte nào trên đường truyền, ví dụ không kết nối được."""
        self._add(ep, site_ep, datetime.now(), time.perf_counter(), None, None, status, device_id)

    def _add(self, ep, site_ep, at, t0, req, resp, status=None, device_id=None) -> None:
        unit = req["unit"] if req else device_id
        d = self.devices.get((ep, unit))
        fc = req["function"] if req else None
        entry = {"at": at.isoformat(timespec="milliseconds"), "ms": round((time.perf_counter() - t0) * 1000, 2),
                 "endpoint": ep, "site_endpoint": site_ep,
                 "device": d["name"] if d else None, "device_label": d.get("label") if d else None,
                 "device_id": unit, "function": fc,
                 "fc_key": f"frame.fc.{fc}" if fc in KNOWN_FC else "frame.fc.other",
                 "exception": resp["exception"] if resp else None, "status": status,
                 "request": {**req, "summary": summary(req, False)} if req else None,
                 "response": {**resp, "summary": summary(resp, True)} if resp else None,
                 "values": explain(d, req, resp) if req and resp else []}
        with self.lock:
            self.seq += 1
            self.entries.append({"seq": self.seq, **entry})

    def query(self, since: int | None = None, limit: int | None = None, device: str | None = None,
              function: int | None = None, errors: bool = False) -> list[dict]:
        def bad(e):
            return (e["exception"] is not None or e["status"] is not None
                    or (e["request"] and e["request"]["malformed"]) or (e["response"] and e["response"]["malformed"]))
        with self.lock:
            found = [e for e in self.entries
                     if (since is None or e["seq"] > since)
                     and (device is None or e["device"] == device)
                     and (function is None or e["function"] == function)
                     and (not errors or bad(e))]
        return found[-limit:] if limit else found

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()
            self.pending.clear()
