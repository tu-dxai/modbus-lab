"""ĐỌC SNMP THEO POINT MAP — SNMP GET cho collector (edge thật đọc SNMP bằng Telegraf inputs.snmp).

Giá trị = số nguyên thiết bị trả về × scale của điểm. Không trả lời (sai community, mất kết nối)
và OID không có trên thiết bị đều thành ReadError có mã, để trang web dịch được.
"""
from pysnmp.hlapi.v3arch.asyncio import (CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine,
                                          UdpTransportTarget, get_cmd)
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject
import async_bridge, udp_trace
from modbus_io import DEFAULT_TIMEOUT, ReadError

_engine: SnmpEngine | None = None


async def _get(d: dict, oid: str, frames=None):
    global _engine
    if _engine is None:
        _engine = SnmpEngine()
    s, timeout = d["snmp"], d.get("timeout", DEFAULT_TIMEOUT)
    target = await UdpTransportTarget.create((d["host"], d["port"]), timeout=timeout, retries=0)
    model = 0 if str(s["version"]) == "1" else 1
    with udp_trace.client(frames, d.get("site_address", f"{d['host']}:{d['port']}")):   # khung tin thô
        return await get_cmd(_engine, CommunityData(s["community"], mpModel=model), target, ContextData(),
                             ObjectType(ObjectIdentity(oid)))


def read_snmp(d: dict, p: dict, frames=None) -> float:
    """frames: FrameLog của collector để ghi khung tin thô (None = không ghi)."""
    timeout = d.get("timeout", DEFAULT_TIMEOUT)
    err, status, _, var_binds = async_bridge.run(_get(d, p["oid"], frames), timeout + 2)
    if err:
        raise ReadError("read.snmp_no_answer", endpoint=f"{d['host']}:{d['port']}", s=timeout)
    if int(status):
        raise ReadError("read.snmp_error", status=status.prettyPrint())
    value = var_binds[0][1]
    if isinstance(value, (NoSuchObject, NoSuchInstance, EndOfMibView)):
        raise ReadError("read.snmp_no_oid", oid=p["oid"])
    return round(int(value) * p.get("scale", 1), 6)
