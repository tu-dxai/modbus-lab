"""Mã hóa và giải mã giá trị Modbus theo kiểu dữ liệu và byte order.

Tự viết thay vì dùng hàm của pymodbus, vì hàm đó chỉ đảo thứ tự word
(ABCD, CDAB), không hỗ trợ BADC và DCBA.
"""
import struct

IDX = {"A": 0, "B": 1, "C": 2, "D": 3}
FMT = {"int16": ">h", "uint16": ">H", "int32": ">i", "uint32": ">I", "float32": ">f"}
SIZE = {"int16": 1, "uint16": 1, "int32": 2, "uint32": 2, "float32": 2}  # số ngăn


def _wire_order(canonical: bytes, order: str) -> bytes:
    """Bốn byte theo thứ tự chuẩn A B C D -> thứ tự trên dây theo `order`."""
    return bytes(canonical[IDX[c]] for c in order)


def _canonical(wire: bytes, order: str) -> bytes:
    out = bytearray(4)
    for i, c in enumerate(order):
        out[IDX[c]] = wire[i]
    return bytes(out)


def encode(value: float, dtype: str, order: str = "ABCD", scale: float = 1) -> list[int]:
    raw = round(value / scale) if dtype != "float32" else value / scale
    b = struct.pack(FMT[dtype], raw)
    if SIZE[dtype] == 1:
        if order in ("BADC", "DCBA"):   # thiết bị đảo byte trong từng ngăn
            b = b[::-1]
        return [int.from_bytes(b, "big")]
    w = _wire_order(b, order)
    return [int.from_bytes(w[0:2], "big"), int.from_bytes(w[2:4], "big")]


def decode(regs: list[int], dtype: str, order: str = "ABCD", scale: float = 1) -> float:
    wire = b"".join(r.to_bytes(2, "big") for r in regs)
    if SIZE[dtype] == 1:
        if order in ("BADC", "DCBA"):
            wire = wire[::-1]
        b = wire
    else:
        b = _canonical(wire, order)
    value = struct.unpack(FMT[dtype], b)[0]
    return value * scale
