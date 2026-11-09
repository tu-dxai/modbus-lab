"""ĐỌC MODBUS THEO POINT MAP — dùng chung cho collector và write-service.

Mỗi thiết bị khai báo host, port của chính nó. Thiết bị trùng host:port nằm sau cùng một gateway
và dùng chung MỘT kết nối TCP: nhiều gateway thật chỉ cho 1-4 kết nối cùng lúc.
"""
from pymodbus.client import ModbusTcpClient
from codec import SIZE, decode

DEFAULT_TIMEOUT = 3.0                              # giây; thiết bị thật chậm hơn simulator


def address(d: dict) -> str:
    return f"{d['host']}:{d['port']}"


def read_point(c: ModbusTcpClient, d: dict, p: dict) -> float:
    fn = c.read_holding_registers if p["table"] == "holding" else c.read_input_registers
    r = fn(p["address"], count=SIZE[p["type"]], device_id=d["device_id"])
    if r.isError():
        raise RuntimeError(f"mã lỗi Modbus {getattr(r, 'exception_code', '?')}")
    return decode(r.registers, p["type"], d["byte_order"], p.get("scale", 1))


class Connections:
    """Một ModbusTcpClient cho mỗi địa chỉ host:port, mở khi cần và tự nối lại khi rớt."""

    def __init__(self):
        self.clients: dict[tuple[str, int], ModbusTcpClient] = {}

    def client(self, d: dict) -> ModbusTcpClient:
        key = (d["host"], d["port"])
        c = self.clients.get(key)
        if c is None:
            c = ModbusTcpClient(d["host"], port=d["port"], timeout=d.get("timeout", DEFAULT_TIMEOUT), retries=0)
            self.clients[key] = c
        if not c.connected:
            c.connect()
        return c

    def read(self, d: dict, p: dict) -> float:
        return read_point(self.client(d), d, p)

    def close(self) -> None:
        for c in self.clients.values():
            c.close()
        self.clients.clear()
