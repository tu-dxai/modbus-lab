"""THIẾT BỊ BACNET/IP CỦA SIMULATOR — một device BACnet cho mỗi thiết bị protocol: bacnet trong Point Map.

  - điểm *-input (và điểm không writable): presentValue lấy từ SimState mỗi lần được đọc (đặt bằng tay,
    tự thay đổi); ghi vào thì từ chối (property / write-access-denied) như thiết bị thật;
  - điểm writable (*-value, *-output): đối tượng commandable có mảng ưu tiên 16 mức. Ghi kèm priority vào
    ô tương ứng; ghi Null = nhả lệnh (relinquish), presentValue về mức ưu tiên cao kế tiếp hoặc
    relinquishDefault. Đặt bằng tay trên simulator = đổi relinquishDefault (giá trị khi không ai ra lệnh).
Mỗi lệnh ghi (nhận hay bị từ chối) vào nhật ký lệnh ghi của simulator (make writes).

Client phải gửi từ cổng khác cổng thiết bị (cùng cổng trên cùng máy thì gói tin vòng về chính client).
"""
import asyncio, concurrent.futures, logging, threading
from bacpypes3.app import Application
from bacpypes3.errors import ExecutionError
from bacpypes3.local.analog import AnalogInputObject, AnalogOutputObject, AnalogValueObject
from bacpypes3.local.binary import BinaryInputObject, BinaryOutputObject, BinaryValueObject
from bacpypes3.basetypes import PriorityValue
from bacpypes3.local.cmd import Commandable, PriorityArray
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.primitivedata import Null
from point_map import bacnet_object
import udp_trace

logging.getLogger("bacpypes3").setLevel(logging.CRITICAL)


def _attr(obj, attr) -> str:
    return obj._property_identifier_class(attr).attr if isinstance(attr, int) else attr


def _to_state(kind: str, value) -> float | int | None:
    """Giá trị BACnet -> số trong SimState (binary: active = 1, inactive = 0)."""
    if value is None or isinstance(value, Null):
        return None
    if kind.startswith("binary"):
        return 1 if str(value) in ("active", "1") else 0
    return round(float(value), 6)


def _error_name(e: BaseException) -> str:
    """Tên lỗi BACnet ngắn gọn cho nhật ký, ví dụ invalid-array-index."""
    code = getattr(e, "errorCode", None)
    return str(code) if code is not None else (str(e) or type(e).__name__)


def _to_bacnet(kind: str, value):
    return ("active" if value else "inactive") if kind.startswith("binary") else float(value)


class _Witnessed:
    """Ghi nhật ký lệnh ghi vào SimState; dùng chung cho đối tượng chỉ đọc và commandable."""
    _sim = None                                        # (state, d, p, key, ep, site_ep) — gán khi tạo

    def _log(self, value, priority, accepted, before, exception=None):
        state, d, p, key, ep, site_ep = self._sim
        state.record_external_write(ep, site_ep, d, key, function="bacnet-write", address=p["object"],
                                    value=value, before=before, accepted=accepted, exception=exception,
                                    priority=priority)


def _readonly_class(base):
    class ReadOnly(_Witnessed, base):
        async def read_property(self, attr, index=None):
            state, d, p, key, ep, site_ep = self._sim
            if _attr(self, attr) == "presentValue":
                self.presentValue = _to_bacnet(base.__name__.replace("Object", "").lower(), state.values[key])
            return await super().read_property(attr, index)

        async def write_property(self, attr, value, index=None, priority=None):
            state, d, p, key, ep, site_ep = self._sim
            if _attr(self, attr) == "presentValue":
                self._log(_to_state(p["object"], value), priority, False, state.values[key], "write-access-denied")
            raise ExecutionError(errorClass="property", errorCode="writeAccessDenied")
    return ReadOnly


def _commandable_class(base):
    class Cmd(_Witnessed, Commandable, base):
        async def write_property(self, attr, value, index=None, priority=None):
            state, d, p, key, ep, site_ep = self._sim
            kind = p["object"].split(",")[0]
            if _attr(self, attr) != "presentValue":    # ví dụ relinquishDefault: presentValue có thể đổi theo
                await super().write_property(attr, value, index, priority)
                state.set_from_device(key, _to_state(kind, self.presentValue))
                return
            before = _to_state(kind, self.presentValue)
            try:
                await super().write_property(attr, value, index, priority)
            except BaseException as e:                 # thiết bị từ chối (priority sai, kiểu sai...): vẫn vào nhật ký
                self._log(_to_state(kind, value), priority or 16, False, before, _error_name(e))
                raise
            after = _to_state(kind, self.presentValue)
            state.set_from_device(key, after)
            self._log(_to_state(kind, value), priority or 16, True, before)
    return Cmd


KINDS = {
    "analog-input": AnalogInputObject, "analog-output": AnalogOutputObject, "analog-value": AnalogValueObject,
    "binary-input": BinaryInputObject, "binary-output": BinaryOutputObject, "binary-value": BinaryValueObject,
}


def start_device(state, d: dict) -> None:
    """Chạy device BACnet của thiết bị `d` ở luồng nền, tại d["host"]:d["port"] (UDP)."""
    ep = f"{d['host']}:{d['port']}"
    site_ep = d.get("site_address", ep)
    ready = threading.Event()

    def run():
        async def main():
            loop = asyncio.get_running_loop()
            objects = []
            for p in d["points"]:
                kind, inst = bacnet_object(p["object"])
                key = f"{d['name']}.{p['name']}"
                writable = bool(p.get("writable"))
                cls = (_commandable_class if writable else _readonly_class)(KINDS[kind])
                init = _to_bacnet(kind, state.values[key])
                extra = {"relinquishDefault": init} if writable else {}
                obj = cls(objectIdentifier=(kind, inst), objectName=p["name"], presentValue=init, **extra)
                obj._sim = (state, d, p, key, ep, site_ep)
                if writable:                           # đặt bằng tay trên simulator = đổi giá trị mặc định
                    # luồng HTTP gọi các hàm này; đối tượng bacpypes thuộc vòng lặp của thiết bị nên chạy ở đó
                    state.on_set(key, lambda v, o=obj, k=kind, key=key:
                                 _on_loop(loop, lambda: _set_default(state, key, o, k, v)))
                    state.reset_hooks.append(lambda o=obj, k=kind, key=key:
                                             _on_loop(loop, lambda: _clear(state, key, o, k, state.values[key])))
                objects.append(obj)
            dev = DeviceObject(objectIdentifier=("device", d["device_instance"]), objectName=d["name"],
                               vendorIdentifier=999)
            port = NetworkPortObject(f"{d['host']}/32:{d['port']}", objectIdentifier=("network-port", 1),
                                     objectName="NP-1")
            app = Application.from_object_list([dev, port, *objects])
            server = app.link_layers[port.objectIdentifier].server
            udp_trace.device(server, state.frames, ep, site_ep)
            receive = server.confirmation

            async def confirmation(pdu):               # thiết bị tắt: không nghe thấy gì, không trả lời
                if state.is_on(d["name"]):
                    await receive(pdu)
            server.confirmation = confirmation
            ready.set()
            await asyncio.Future()
        asyncio.run(main())

    threading.Thread(target=run, daemon=True).start()
    ready.wait(5)


def _on_loop(loop, fn):
    """Chạy fn trên vòng lặp asyncio của thiết bị và chờ xong (gọi từ luồng khác)."""
    done = concurrent.futures.Future()

    def run():
        try:
            done.set_result(fn())
        except BaseException as e:
            done.set_exception(e)
    loop.call_soon_threadsafe(run)
    return done.result(5)


def _set_default(state, key: str, obj, kind: str, value) -> None:
    """Đổi relinquishDefault rồi tính lại presentValue theo mảng ưu tiên.

    Không gán obj.presentValue: với đối tượng commandable của bacpypes3, gán presentValue = ghi vào ô ưu tiên 16,
    và ô đó sẽ giữ giá trị cũ mãi (lần đặt sau client vẫn đọc số cũ, nhả lệnh rơi về số cũ)."""
    obj.relinquishDefault = _to_bacnet(kind, value)
    obj.recalculating()
    state.set_from_device(key, _to_state(kind, obj.presentValue))   # đang có lệnh ưu tiên: báo đúng số thiết bị trả


def _clear(state, key: str, obj, kind: str, value) -> None:
    """Đặt lại simulator: xóa mọi lệnh trong mảng ưu tiên, như thiết bị vừa khởi động lại."""
    obj.priorityArray = PriorityArray([PriorityValue(null=()) for _ in range(16)], obj=obj)
    _set_default(state, key, obj, kind, value)
