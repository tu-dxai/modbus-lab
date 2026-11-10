"""ĐỌC MODBUS THEO POINT MAP — dùng chung cho collector và write-service.

Mỗi thiết bị khai báo host, port của chính nó. Thiết bị trùng host:port nằm sau cùng một gateway
và dùng chung MỘT kết nối TCP: nhiều gateway thật chỉ cho 1-4 kết nối cùng lúc.
Thiết bị Modbus RTU (transport: rtu) khai báo cổng serial; thiết bị cùng cổng = cùng bus RS-485,
dùng chung một cổng mở (một bus chỉ có một master).
"""
from pymodbus import FramerType
from pymodbus.client import ModbusSerialClient, ModbusTcpClient
from codec import SIZE, decode
from i18n import Translatable

DEFAULT_TIMEOUT = 3.0                              # giây; thiết bị thật chậm hơn simulator


class ReadError(Translatable):
    """Thiết bị trả mã lỗi Modbus (exception response) cho lệnh đọc."""


def address(d: dict) -> str:
    """Địa chỉ kết nối của thiết bị: "host:port" (TCP, SNMP, BACnet) hoặc "rtu:<cổng serial>" (Modbus RTU)."""
    if d.get("transport") == "rtu":
        return f"rtu:{d['serial']['port']}"
    return f"{d['host']}:{d['port']}"


def read_point(c: ModbusTcpClient, d: dict, p: dict) -> float:
    fn = c.read_holding_registers if p["table"] == "holding" else c.read_input_registers
    r = fn(p["address"], count=SIZE[p["type"]], device_id=d["device_id"])
    if r.isError():
        raise ReadError("read.modbus_exception", code=getattr(r, "exception_code", "?"))
    return decode(r.registers, p["type"], d["byte_order"], p.get("scale", 1))


class Connections:
    """Một ModbusTcpClient cho mỗi địa chỉ host:port, mở khi cần và tự nối lại khi rớt.

    frames: FrameLog (edge/modbus/frames.py) để ghi lại từng byte gửi đi và nhận về, kèm các yêu cầu
    không có phản hồi. Gắn khi tạo, hoặc sau bằng trace(log).
    """

    def __init__(self, frames=None):
        self.clients: dict[str, ModbusTcpClient | ModbusSerialClient] = {}
        self.frames = frames

    def trace(self, frames) -> None:
        """Bắt đầu ghi khung tin; đóng kết nối cũ để kết nối mới được gắn hook."""
        self.close()
        self.frames = frames

    def client(self, d: dict) -> ModbusTcpClient | ModbusSerialClient:
        key = address(d)
        c = self.clients.get(key)
        if c is None:
            rtu = d.get("transport") == "rtu"
            hook = self.frames.tracer(key, d.get("site_address", key), client=True, rtu=rtu) \
                if self.frames else None
            timeout = d.get("timeout", DEFAULT_TIMEOUT)
            if rtu:
                s = d["serial"]
                c = ModbusSerialClient(port=s["port"], framer=FramerType.RTU, baudrate=s["baudrate"],
                                       parity=s.get("parity", "N"), stopbits=s.get("stop_bits", 1),
                                       bytesize=s.get("bytesize", 8), timeout=timeout, retries=0, trace_packet=hook)
            else:
                c = ModbusTcpClient(d["host"], port=d["port"], timeout=timeout, retries=0, trace_packet=hook)
            self.clients[key] = c
        if not c.connected:
            c.connect()
        return c

    def no_response(self, d: dict) -> None:
        """Gọi khi một lệnh gửi đi mà không nhận được gì (timeout, rớt kết nối giữa chừng)."""
        if self.frames:
            self.frames.expire(address(d), {"key": "frame.status.timeout",
                                            "params": {"s": d.get("timeout", DEFAULT_TIMEOUT)}})

    def unreachable(self, d: dict) -> None:
        """Gọi khi không mở được kết nối tới địa chỉ của thiết bị: không có byte nào được gửi."""
        if self.frames:
            self.frames.event(address(d), d.get("site_address", address(d)), d["device_id"],
                              {"key": "read.unreachable", "params": {"endpoint": address(d)}})

    def reachable(self, d: dict) -> bool:
        """Modbus: mở được kết nối TCP / cổng serial. SNMP, BACnet chạy trên UDP: không có kết nối để kiểm trước."""
        return d.get("protocol", "modbus") != "modbus" or self.client(d).connected

    def read(self, d: dict, p: dict) -> float:
        proto = d.get("protocol", "modbus")
        if proto == "snmp":
            from snmp_io import read_snmp
            return read_snmp(d, p)
        if proto == "bacnet":
            from bacnet_io import read_bacnet
            return read_bacnet(d, p)
        try:
            return read_point(self.client(d), d, p)
        except ReadError:                              # thiết bị có trả lời (mã lỗi Modbus): đã ghi đủ cặp
            raise
        except Exception:
            self.no_response(d)
            raise

    def close(self) -> None:
        for c in self.clients.values():
            c.close()
        self.clients.clear()
