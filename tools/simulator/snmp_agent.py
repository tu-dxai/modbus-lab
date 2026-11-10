"""AGENT SNMP CỦA SIMULATOR — trả lời SNMP GET / GETNEXT / GETBULK (walk) cho một thiết bị SNMP.

Giá trị lấy thẳng từ SimState (đặt bằng tay, tự thay đổi), đổi sang số nguyên theo hệ số của điểm
(ví dụ 545,0 V với scale 0.1 -> 5450). Chỉ đọc: không trả lời SET. Sai community thì im lặng, như
agent thật (client hết thời gian chờ). OID không khai báo -> noSuchObject.
"""
import asyncio, threading
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.proto import rfc1902
from pysnmp.proto.api import v2c
from pysnmp.smi import instrum
import udp_trace

SNMP_CLASS = {"integer": rfc1902.Integer32, "gauge32": rfc1902.Gauge32, "counter32": rfc1902.Counter32}


def _oid(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split("."))


class PointMib(instrum.AbstractMibInstrumController):
    """MIB ảo: mỗi điểm của thiết bị là một OID; đọc giá trị hiện tại từ SimState."""

    def __init__(self, state, d: dict):
        self.state = state
        self.points = sorted((_oid(p["oid"]), f"{d['name']}.{p['name']}", p["type"]) for p in d["points"])
        self.by_oid = {o: (key, t) for o, key, t in self.points}

    def _value(self, oid: tuple):
        key, typ = self.by_oid[oid]
        return SNMP_CLASS[typ](self.state.raw_int(key))

    def read_variables(self, *var_binds, **ctx):
        return [(oid, self._value(tuple(oid)) if tuple(oid) in self.by_oid else v2c.NoSuchObject())
                for oid, _ in var_binds]

    def read_next_variables(self, *var_binds, **ctx):
        out = []
        for oid, _ in var_binds:
            nxt = next((o for o, _, _ in self.points if o > tuple(oid)), None)
            out.append((rfc1902.ObjectName(nxt), self._value(nxt)) if nxt else (oid, v2c.EndOfMibView()))
        return out

    def write_variables(self, *var_binds, **ctx):    # chỉ đọc
        raise NotImplementedError("simulator SNMP chỉ đọc")


def start_agent(state, d: dict) -> None:
    """Chạy agent SNMP của thiết bị `d` ở luồng nền, tại d["host"]:d["port"] (UDP)."""
    ready = threading.Event()

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        eng = engine.SnmpEngine()
        transport = udp.UdpTransport().open_server_mode((d["host"], d["port"]))
        ep = f"{d['host']}:{d['port']}"
        udp_trace.device(transport, state.frames, ep, d.get("site_address", ep))     # khung tin thô (make frames)
        config.add_transport(eng, udp.DOMAIN_NAME, transport)
        s = d["snmp"]
        config.add_v1_system(eng, "lab-area", s["community"])
        model = 1 if str(s["version"]) == "1" else 2
        config.add_vacm_user(eng, model, "lab-area", "noAuthNoPriv", (1, 3, 6), ())
        ctx = context.SnmpContext(eng)
        ctx.unregister_context_name(b"")
        ctx.register_context_name(b"", PointMib(state, d))
        cmdrsp.GetCommandResponder(eng, ctx)
        cmdrsp.NextCommandResponder(eng, ctx)
        cmdrsp.BulkCommandResponder(eng, ctx)
        eng.transport_dispatcher.job_started(1)
        ready.set()
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    ready.wait(5)
