"""ĐỌC / GHI BACNET/IP THEO POINT MAP — collector Python cho BACnet (Telegraf không đọc BACnet).

  read_bacnet(d, p)                      presentValue (binary: active -> 1, inactive -> 0)
  write_bacnet(d, p, value)              WriteProperty presentValue kèm priority của điểm
  relinquish_bacnet(d, p)                ghi Null ở đúng priority đó: nhả lệnh, trả quyền cho mức thấp hơn

Client gửi từ địa chỉ d["bacnet_client"] (Point Map bacnet.client, môi trường lab ghi đè) — phải khác
cổng thiết bị nếu cùng máy. Mỗi địa chỉ client một ứng dụng bacpypes3, chạy trên vòng lặp nền dùng chung.
"""
import asyncio, logging
from bacpypes3.apdu import ErrorRejectAbortNack
from bacpypes3.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Null, ObjectIdentifier, Real
import async_bridge
from i18n import Translatable
from modbus_io import DEFAULT_TIMEOUT, ReadError

logging.getLogger("bacpypes3").setLevel(logging.CRITICAL)
_apps: dict[str, Application] = {}


class BacnetRejected(Translatable):
    """Thiết bị BACnet trả lỗi cho lệnh (unknown-object, write-access-denied...)."""


async def _app(local: str) -> Application:
    if local not in _apps:
        dev = DeviceObject(objectIdentifier=("device", 4194301), objectName="edge-collector", vendorIdentifier=999)
        port = NetworkPortObject(local, objectIdentifier=("network-port", 1), objectName="NP-1")
        _apps[local] = Application.from_object_list([dev, port])
    return _apps[local]


def _kind(p: dict) -> str:
    return p["object"].split(",")[0].strip()


async def _call(d: dict, p: dict, action, value=None, priority=None):
    app = await _app(d["bacnet_client"])
    addr, oid = Address(f"{d['host']}:{d['port']}"), ObjectIdentifier(p["object"])
    if action == "read":
        coro = app.read_property(addr, oid, "present-value")
    else:
        coro = app.write_property(addr, oid, "present-value", value, priority=priority)
    return await asyncio.wait_for(coro, d.get("timeout", DEFAULT_TIMEOUT))


def _run(d: dict, p: dict, action, value=None, priority=None):
    timeout = d.get("timeout", DEFAULT_TIMEOUT)
    try:
        return async_bridge.run(_call(d, p, action, value, priority), timeout + 2)
    except (asyncio.TimeoutError, TimeoutError):
        raise ReadError("read.bacnet_no_answer", endpoint=f"{d['host']}:{d['port']}", s=timeout) from None
    except Translatable:
        raise
    except (ErrorRejectAbortNack, Exception) as e:     # Error / Reject / Abort của bacpypes3 là BaseException
        raise BacnetRejected("read.bacnet_error", detail=str(e) or type(e).__name__) from None


def read_bacnet(d: dict, p: dict) -> float:
    value = _run(d, p, "read")
    if _kind(p).startswith("binary"):
        return 1 if str(value) in ("active", "1") else 0
    return round(float(value), 6)


def write_bacnet(d: dict, p: dict, value) -> None:
    v = ("active" if value else "inactive") if _kind(p).startswith("binary") else Real(float(value))
    _run(d, p, "write", v, p["priority"])


def relinquish_bacnet(d: dict, p: dict) -> None:
    _run(d, p, "write", Null(()), p["priority"])
