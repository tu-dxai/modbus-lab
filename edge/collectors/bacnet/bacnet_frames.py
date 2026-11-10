"""KHUNG TIN BACNET/IP — tách từng byte của một gói BACnet/IP thành các trường.

Một gói gồm ba lớp:
  BVLC  81 | 0a | 00 11            loại (luôn 81 = BACnet/IP) | chức năng (0a gửi thẳng, 0b broadcast) | độ dài gói
  NPDU  01 | 04                    phiên bản | điều khiển (bit 2 = cần trả lời; có thể kèm địa chỉ mạng đích/nguồn)
  APDU  02 | 44 | 00 | 0c | ...    loại APDU | kích thước tối đa | invoke ID (ghép hỏi/đáp) | dịch vụ | tham số
Loại APDU (4 bit cao): 0 lệnh cần xác nhận, 1 lệnh không cần xác nhận, 2 Simple-ACK, 3 Complex-ACK, 5 Error,
6 Reject, 7 Abort. Dịch vụ: 0c ReadProperty, 0f WriteProperty.

Tham số mã hóa bằng thẻ (tag): 0c = thẻ ngữ cảnh 0 dài 4 byte (đối tượng), 19 55 = thẻ ngữ cảnh 1 giá trị 85
(present-value), 3e ... 3f = mở / đóng thẻ 3 bao giá trị, 44 = REAL 4 byte, 91 = ENUMERATED 1 byte, 00 = NULL
(nhả lệnh), 49 08 = thẻ ngữ cảnh 4: mức ưu tiên 8.

Dùng chung cho FrameLog (edge/modbus/frames.py) ở phía collector và phía simulator.
"""
import struct

OBJECT_TYPES = {0: "analog-input", 1: "analog-output", 2: "analog-value", 3: "binary-input", 4: "binary-output",
                5: "binary-value", 8: "device", 13: "multi-state-input", 14: "multi-state-output",
                19: "multi-state-value", 56: "network-port"}
PROPERTIES = {28: "description", 36: "event-state", 77: "object-name", 79: "object-type", 81: "out-of-service",
              85: "present-value", 87: "priority-array", 103: "reliability", 104: "relinquish-default",
              111: "status-flags", 117: "units"}
SERVICES = {12: "read-property", 14: "read-property-multiple", 15: "write-property", 16: "write-property-multiple"}
ERROR_CLASSES = {0: "device", 1: "object", 2: "property", 3: "resources", 4: "security", 5: "services",
                 6: "vt", 7: "communication"}
ERROR_CODES = {0: "other", 2: "configuration-in-progress", 9: "invalid-data-type", 25: "operational-problem",
               31: "unknown-object", 32: "unknown-property", 37: "value-out-of-range", 40: "write-access-denied",
               42: "invalid-array-index", 44: "not-cov-property", 45: "optional-functionality-not-supported",
               50: "property-is-not-an-array"}
APP_TYPES = {0: "NULL", 1: "BOOLEAN", 2: "UNSIGNED", 3: "SIGNED", 4: "REAL", 5: "DOUBLE", 6: "OCTET STRING",
             7: "CHARACTER STRING", 8: "BIT STRING", 9: "ENUMERATED", 10: "DATE", 11: "TIME", 12: "OBJECT ID"}


class _Bad(Exception):
    pass


def _tag(b: bytes, i: int, end: int) -> tuple[int, bool, str, int, int]:
    """Thẻ tại i: (số thẻ, ngữ cảnh?, 'open'|'close'|'data', đầu dữ liệu, cuối dữ liệu)."""
    if i >= end:
        raise _Bad
    x, j = b[i], i + 1
    num, ctx, lvt = x >> 4, bool(x & 0x08), x & 0x07
    if num == 15:
        num, j = b[j], j + 1
    if ctx and lvt == 6:
        return num, ctx, "open", j, j
    if ctx and lvt == 7:
        return num, ctx, "close", j, j
    if not ctx and num == 1:                          # BOOLEAN: giá trị nằm luôn trong 3 bit thấp
        return num, ctx, "data", j, j
    n = lvt
    if lvt == 5:
        n, j = b[j], j + 1
        if n == 254:
            n, j = int.from_bytes(b[j:j + 2], "big"), j + 2
        elif n == 255:
            n, j = int.from_bytes(b[j:j + 4], "big"), j + 4
    if j + n > end:
        raise _Bad
    return num, ctx, "data", j, j + n


def _object(v: bytes) -> str:
    if len(v) != 4:
        raise _Bad
    n = int.from_bytes(v, "big")
    kind = n >> 22
    return f"{OBJECT_TYPES.get(kind, kind)},{n & 0x3FFFFF}"


def _app_value(b: bytes, num: int, i: int, j: int, z: int):
    v = b[j:z]
    if num == 0:
        return None
    if num == 1:
        return bool(b[i] & 0x07)
    if num in (2, 9):
        return int.from_bytes(v, "big") if v else 0
    if num == 3:
        return int.from_bytes(v, "big", signed=True) if v else 0
    if num == 4 and len(v) == 4:
        return round(struct.unpack(">f", v)[0], 6)
    if num == 5 and len(v) == 8:
        return round(struct.unpack(">d", v)[0], 9)
    if num == 7 and v:
        return v[1:].decode("utf-8", "replace")
    if num == 12:
        return _object(v)
    return v.hex(" ")


def parse_bacnet(data: bytes, response: bool) -> dict:
    """Tách gói BACnet/IP thành các trường (tên + byte hex) và các giá trị đọc ra. Không bao giờ ném lỗi."""
    data = bytes(data)
    r = {"protocol": "bacnet", "hex": data.hex(" "), "fields": [], "transaction": None, "unit": None,
         "function": None, "exception": None, "malformed": False, "ref": None, "property": None, "apdu": None,
         "value": None, "vtype": None, "vhex": None, "write": None, "fc_key": "frame.fc.bacnet_other"}
    try:
        _parse(data, r)
    except (_Bad, IndexError, ValueError, struct.error):
        r.update(malformed=True, fields=[{"name": "raw", "hex": data.hex(" ")}], transaction=None, write=None)
    r["summary"] = _summary(r)
    return r


def _parse(b: bytes, r: dict) -> None:
    end = len(b)

    def add(name, a, z):
        if z > end or z <= a and name not in ("open_tag", "close_tag"):
            raise _Bad
        r["fields"].append({"name": name, "hex": b[a:z].hex(" ")})

    if end < 6 or b[0] != 0x81 or int.from_bytes(b[2:4], "big") != end:
        raise _Bad
    add("bvlc_type", 0, 1); add("bvlc_function", 1, 2); add("bvlc_length", 2, 4)
    if b[1] not in (0x0A, 0x0B):                      # Forwarded-NPDU, đăng ký foreign device...: chưa tách
        add("data", 4, end)
        r["function"] = f"bvlc-{b[1]:02x}"
        return
    if b[4] != 0x01:
        raise _Bad
    add("npdu_version", 4, 5); add("npdu_control", 5, 6)
    control, i = b[5], 6
    if control & 0x20:                                # có địa chỉ mạng đích: DNET (2) | DLEN (1) | DADR
        n = b[i + 2]
        add("npdu_dest", i, i + 3 + n)
        i += 3 + n
    if control & 0x08:                                # có địa chỉ mạng nguồn: SNET | SLEN | SADR
        n = b[i + 2]
        add("npdu_source", i, i + 3 + n)
        i += 3 + n
    if control & 0x20:
        add("hop_count", i, i + 1)
        i += 1
    if control & 0x80:                                # bản tin của lớp mạng, không phải APDU
        add("data", i, end)
        r["function"] = "network"
        return
    kind = b[i] >> 4
    r["apdu"] = {0: "confirmed", 1: "unconfirmed", 2: "simple-ack", 3: "complex-ack", 5: "error", 6: "reject",
                 7: "abort"}.get(kind, f"apdu-{kind}")
    add("apdu_type", i, i + 1)
    if kind == 0:
        segmented = b[i] & 0x08
        add("max_apdu", i + 1, i + 2); add("invoke_id", i + 2, i + 3)
        r["transaction"], i = b[i + 2], i + 3
        if segmented:
            add("segment", i, i + 2)
            i += 2
    elif kind == 1:
        add("service", i + 1, i + 2)
        r["function"] = f"unconfirmed-{b[i + 1]}"
        if i + 2 < end:
            add("data", i + 2, end)
        return
    elif kind in (2, 3, 5, 6, 7):
        add("invoke_id", i + 1, i + 2)
        r["transaction"], i = b[i + 1], i + 2
        if kind == 3 and b[i - 2] & 0x08:
            add("segment", i, i + 2)
            i += 2
        if kind in (6, 7):
            add("reason", i, i + 1)
            r["exception"] = f"{r['apdu']}: {b[i]}"
            r["function"] = r["apdu"]
            if i + 1 != end:
                raise _Bad
            return
    else:
        raise _Bad
    service = b[i]
    add("service", i, i + 1)
    r["function"] = SERVICES.get(service, f"service-{service}")
    r["fc_key"] = {12: "frame.fc.bacnet_read", 15: "frame.fc.bacnet_write"}.get(service, "frame.fc.bacnet_other")
    i += 1
    if kind == 5:                                      # Error: lớp lỗi | mã lỗi (ENUMERATED)
        out = []
        for name in ("error_class", "error_code"):
            num, ctx, what, j, z = _tag(b, i, end)
            if ctx or num != 9:
                raise _Bad
            add(name, i, z)
            out.append(int.from_bytes(b[j:z], "big"))
            i = z
        cls, code = out
        r["exception"] = f"{ERROR_CLASSES.get(cls, cls)}: {ERROR_CODES.get(code, code)}"
        if i != end:
            raise _Bad
        return
    _params(b, i, end, r, add)


def _params(b: bytes, i: int, end: int, r: dict, add) -> None:
    """Tham số ReadProperty / WriteProperty và Complex-ACK của ReadProperty."""
    write, values = {}, []
    while i < end:
        num, ctx, what, j, z = _tag(b, i, end)
        if not ctx:
            raise _Bad
        if num == 0 and what == "data":
            add("object", i, z)
            r["ref"] = _object(b[j:z])
        elif num == 1 and what == "data":
            add("property", i, z)
            pid = int.from_bytes(b[j:z], "big")
            r["property"] = PROPERTIES.get(pid, str(pid))
        elif num == 2 and what == "data":
            add("array_index", i, z)
        elif num == 3 and what == "open":
            add("open_tag", i, j)
            i = j
            while True:
                vnum, vctx, vwhat, vj, vz = _tag(b, i, end)
                if vctx and vnum == 3 and vwhat == "close":
                    add("close_tag", i, vj)
                    z = vj
                    break
                if vctx:
                    raise _Bad
                add("value", i, vz)
                values.append((APP_TYPES.get(vnum, f"tag-{vnum}"), _app_value(b, vnum, i, vj, vz),
                               b[vj:vz].hex(" ")))
                i = vz
        elif num == 4 and what == "data":
            add("priority", i, z)
            write["priority"] = int.from_bytes(b[j:z], "big")
        else:
            raise _Bad
        i = z
    if values:
        r["vtype"], r["value"], r["vhex"] = values[0]
    if r["function"] == "write-property" and r["apdu"] == "confirmed":
        r["write"] = {"value": r["value"], "priority": write.get("priority")}


def _text(r: dict):
    """Giá trị để hiện: binary present-value là active / inactive như trên thiết bị."""
    if r["vtype"] == "ENUMERATED" and (r["ref"] or "").startswith("binary") and r["property"] == "present-value":
        return "active" if r["value"] else "inactive"
    return r["value"]


def _summary(r: dict) -> dict:
    if r["malformed"]:
        return {"key": "frame.sum.malformed_bacnet", "params": {}}
    obj, prop = r["ref"] or "?", r["property"] or "?"
    apdu = r["apdu"]
    if apdu == "error":
        cls, _, code = r["exception"].partition(": ")
        return {"key": "frame.sum.bacnet_error", "params": {"cls": cls, "code": code}}
    if apdu in ("reject", "abort"):
        return {"key": f"frame.sum.bacnet_{apdu}", "params": {"reason": r["exception"].split(": ")[1]}}
    if apdu == "simple-ack":
        return {"key": "frame.sum.bacnet_ack", "params": {}}
    if r["function"] == "read-property" and apdu == "confirmed":
        return {"key": "frame.sum.bacnet_read", "params": {"object": obj, "property": prop}}
    if r["function"] == "read-property" and apdu == "complex-ack":
        return {"key": "frame.sum.bacnet_value", "params": {"object": obj, "property": prop, "value": _text(r)}}
    if r["write"] is not None:
        if r["write"]["value"] is None:
            return {"key": "frame.sum.bacnet_relinquish",
                    "params": {"object": obj, "property": prop, "priority": r["write"]["priority"]}}
        return {"key": "frame.sum.bacnet_write", "params": {"object": obj, "property": prop, "value": _text(r),
                                                            "priority": r["write"]["priority"]}}
    return {"key": "frame.sum.bacnet_other", "params": {"service": r["function"] or "?"}}


def explain_bacnet(d: dict | None, req: dict, resp: dict) -> list[dict]:
    """Giá trị present-value trong khung tin ứng với điểm nào: đọc thì lấy từ phản hồi, ghi thì từ lệnh."""
    if d is None or req["malformed"] or resp["malformed"] or resp["exception"] or req["property"] != "present-value":
        return []
    src = resp if req["function"] == "read-property" else req
    if src["value"] is None or src["vtype"] not in ("REAL", "ENUMERATED", "UNSIGNED", "SIGNED", "DOUBLE"):
        return []
    from point_map import bacnet_object
    want = bacnet_object(req["ref"])
    if want is None:
        return []
    p = next((p for p in d["points"] if bacnet_object(p.get("object", "")) == want), None)
    if p is None:
        return []
    return [{"kind": "bacnet", "key": f"{d['name']}.{p['name']}", "label": p.get("label"), "hex": src["vhex"],
             "raw": _text(src), "value": src["value"], "scale": 1, "unit": p.get("unit", ""),
             "type": src["vtype"], "byte_order": None}]
