"""KHUNG TIN SNMP — tách từng byte của một gói SNMP v1/v2c (mã hóa BER) thành các trường.

Mỗi phần tử BER là TLV: kiểu (1 byte) | độ dài | giá trị. Một lệnh GET và phản hồi có dạng:
  30 len                    SEQUENCE: cả gói
    02 01 01                version (0 = v1, 1 = v2c)
    04 06 70 75 62 6c 69 63 community "public"
    a0 len                  PDU: a0 GET, a1 GET-NEXT, a2 RESPONSE, a3 SET
      02 04 ..              request-id: ghép lệnh với phản hồi
      02 01 00              error-status (0 = không lỗi)
      02 01 00              error-index
      30 len                danh sách biến
        30 len              một biến
          06 len ..         OID
          05 00 | 02 01 64  giá trị: NULL trong lệnh GET; INTEGER 100 trong phản hồi
Phản hồi "không có OID" (v2c): giá trị là 80 00 (noSuchObject), 81 00 (noSuchInstance), 82 00 (endOfMibView).

Dùng chung cho FrameLog (edge/modbus/frames.py) ở phía collector và phía simulator.
"""
PDUS = {0xA0: "get", 0xA1: "get-next", 0xA2: "response", 0xA3: "set", 0xA5: "get-bulk", 0xA6: "inform",
        0xA7: "trap", 0xA8: "report"}
TYPES = {0x02: "integer", 0x04: "octet-string", 0x05: "null", 0x06: "oid", 0x40: "ipaddress", 0x41: "counter32",
         0x42: "gauge32", 0x43: "timeticks", 0x46: "counter64", 0x80: "noSuchObject", 0x81: "noSuchInstance",
         0x82: "endOfMibView"}
UNSIGNED = {0x41, 0x42, 0x43, 0x46}
ERRORS = {1: "tooBig", 2: "noSuchName", 3: "badValue", 4: "readOnly", 5: "genErr", 6: "noAccess",
          7: "wrongType", 10: "wrongValue", 11: "noCreation", 16: "authorizationError", 17: "notWritable"}


class _Bad(Exception):
    pass


def _tlv(b: bytes, i: int, end: int) -> tuple[int, int, int]:
    """Phần tử BER tại i: (kiểu, đầu giá trị, cuối giá trị). Độ dài dạng dài: 0x8n rồi n byte."""
    if i + 2 > end:
        raise _Bad
    tag, n, j = b[i], b[i + 1], i + 2
    if n & 0x80:
        k = n & 0x7F
        if not 0 < k <= 4 or j + k > end:
            raise _Bad
        n, j = int.from_bytes(b[j:j + k], "big"), j + k
    if j + n > end:
        raise _Bad
    return tag, j, j + n


def _int(v: bytes, signed: bool = True) -> int:
    return int.from_bytes(v, "big", signed=signed) if v else 0


def _oid(v: bytes) -> str:
    if not v:
        raise _Bad
    first = v[0]
    parts = [min(first // 40, 2), first - 40 * min(first // 40, 2)]
    n = 0
    for x in v[1:]:
        n = (n << 7) | (x & 0x7F)
        if not x & 0x80:
            parts.append(n)
            n = 0
    return ".".join(map(str, parts))


def _value(tag: int, v: bytes):
    if tag == 0x02:
        return _int(v)
    if tag in UNSIGNED:
        return _int(v, signed=False)
    if tag == 0x04:
        return v.decode("utf-8", "replace")
    if tag == 0x06:
        return _oid(v)
    if tag == 0x40 and len(v) == 4:
        return ".".join(map(str, v))
    return None


def parse_snmp(data: bytes, response: bool) -> dict:
    """Tách gói SNMP thành các trường (tên + byte hex) và các giá trị đọc ra. Không bao giờ ném lỗi."""
    data = bytes(data)
    r = {"protocol": "snmp", "hex": data.hex(" "), "fields": [], "transaction": None, "unit": None,
         "function": None, "exception": None, "malformed": False, "ref": None, "oid": None,
         "value": None, "vtype": None, "vhex": None, "varbinds": [], "write": None, "fc_key": "frame.fc.snmp_other"}
    try:
        _parse(data, r)
    except (_Bad, IndexError, ValueError):
        r.update(malformed=True, fields=[{"name": "raw", "hex": data.hex(" ")}], varbinds=[], transaction=None)
    r["summary"] = _summary(r)
    return r


def _parse(b: bytes, r: dict) -> None:
    def add(name, a, z):
        r["fields"].append({"name": name, "hex": b[a:z].hex(" ")})

    tag, j, end = _tlv(b, 0, len(b))
    if tag != 0x30 or end != len(b):
        raise _Bad
    add("message", 0, j)
    i = j
    for name, want in (("version", 0x02), ("community", 0x04)):
        tag, j, z = _tlv(b, i, end)
        if tag != want:
            raise _Bad
        add(name, i, z)
        r[name] = _int(b[j:z]) if want == 0x02 else b[j:z].decode("utf-8", "replace")
        i = z
    tag, j, pend = _tlv(b, i, end)
    if tag not in PDUS or pend != end:
        raise _Bad
    add("pdu", i, j)
    r["pdu"] = PDUS[tag]
    r["function"] = PDUS[tag]
    r["fc_key"] = "frame.fc.snmp_get" if tag == 0xA0 else "frame.fc.snmp_other"
    i = j
    nums = []
    for name in ("request_id", "error_status", "error_index"):
        tag, j, z = _tlv(b, i, pend)
        if tag != 0x02:
            raise _Bad
        add(name, i, z)
        nums.append(_int(b[j:z]))
        i = z
    r["transaction"], status, index = nums
    tag, j, lend = _tlv(b, i, pend)
    if tag != 0x30 or lend != pend:
        raise _Bad
    add("varbinds", i, j)
    i = j
    while i < lend:
        tag, j, vend = _tlv(b, i, lend)
        if tag != 0x30:
            raise _Bad
        add("varbind", i, j)
        tag, oj, oz = _tlv(b, j, vend)
        if tag != 0x06:
            raise _Bad
        add("oid", j, oz)
        vtag, vj, vz = _tlv(b, oz, vend)
        if vz != vend:
            raise _Bad
        add("value", oz, vz)
        r["varbinds"].append({"oid": _oid(b[oj:oz]), "tag": vtag, "vtype": TYPES.get(vtag, f"0x{vtag:02x}"),
                              "value": _value(vtag, b[vj:vz]), "vhex": b[vj:vz].hex(" ")})
        i = vend
    if r["varbinds"]:
        first = r["varbinds"][0]
        r.update(oid=first["oid"], ref=f"OID {first['oid']}", value=first["value"], vtype=first["vtype"],
                 vhex=first["vhex"])
    if status:
        r["exception"] = ERRORS.get(status, str(status))
        r["error_index"] = index
    else:
        missing = next((v for v in r["varbinds"] if v["tag"] in (0x80, 0x81, 0x82)), None)
        if missing and r["pdu"] == "response":
            r["exception"] = missing["vtype"]


def _summary(r: dict) -> dict:
    if r["malformed"]:
        return {"key": "frame.sum.malformed_snmp", "params": {}}
    oid = r["oid"] or "?"
    if r["pdu"] == "response":
        if r["exception"] in ("noSuchObject", "noSuchInstance", "endOfMibView"):
            return {"key": "frame.sum.snmp_no_oid", "params": {"oid": oid, "type": r["exception"]}}
        if r["exception"]:
            return {"key": "frame.sum.snmp_error", "params": {"status": r["exception"], "index": r.get("error_index")}}
        return {"key": "frame.sum.snmp_value", "params": {"oid": oid, "value": r["value"], "type": r["vtype"]}}
    if r["pdu"] == "get":
        return {"key": "frame.sum.snmp_get", "params": {"oid": oid}}
    return {"key": "frame.sum.snmp_other", "params": {"pdu": r["pdu"], "oid": oid}}


def explain_snmp(d: dict | None, req: dict, resp: dict) -> list[dict]:
    """Biến trong phản hồi ứng với điểm nào của thiết bị: số nguyên thô × hệ số -> giá trị."""
    if d is None or resp["malformed"] or resp["exception"]:
        return []
    by_oid = {p.get("oid"): p for p in d["points"]}
    out = []
    for v in resp["varbinds"]:
        p = by_oid.get(v["oid"])
        if p is None or not isinstance(v["value"], int):
            continue
        scale = p.get("scale", 1)
        out.append({"kind": "snmp", "key": f"{d['name']}.{p['name']}", "label": p.get("label"), "hex": v["vhex"],
                    "raw": v["value"], "value": round(v["value"] * scale, 6), "scale": scale,
                    "unit": p.get("unit", ""), "type": v["vtype"], "byte_order": None})
    return out
