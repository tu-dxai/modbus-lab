"""BẮT KHUNG TIN UDP (SNMP, BACnet/IP) — chép byte thô gửi đi / nhận về vào FrameLog, không đổi byte nào.

pymodbus có sẵn hook trace_packet; pysnmp và bacpypes3 thì không, nên module này bọc đúng hai chỗ gửi và
nhận datagram của hai thư viện (một lần cho cả tiến trình):
  - pysnmp:    DgramAsyncioProtocol.send_message / datagram_received
  - bacpypes3: IPv4DatagramServer.indication (gửi) / confirmation (nhận)

Hai vai:
  - thiết bị (simulator): device(transport, log, ep, site_ep) gắn FrameLog vào đúng transport của agent /
    device đó — byte nhận vào là lệnh, byte gửi ra là phản hồi;
  - client (collector):   bọc lệnh trong `with client(log, site_ep):` ngay trong coroutine gửi lệnh. Byte gửi
    ra là lệnh; phản hồi được ghép lại theo (địa chỉ thiết bị, request-id / invoke ID) đã gửi.
Một hook lỗi không bao giờ được làm hỏng gói tin hay ném lỗi ra thư viện.
"""
import contextvars
from contextlib import contextmanager
from bacnet_frames import parse_bacnet
from snmp_frames import parse_snmp

_CLIENT: contextvars.ContextVar = contextvars.ContextVar("udp_trace_client", default=None)
_routes: dict[tuple, object] = {}                     # (địa chỉ thiết bị, mã giao dịch) -> FrameLog chờ phản hồi
MAX_ROUTES = 1000
_installed = False


def device(transport, log, ep: str, site_ep: str) -> None:
    """Phía thiết bị: mọi gói qua `transport` (pysnmp transport / IPv4DatagramServer) vào `log` tại `ep`."""
    install()
    transport._frame_tap = (log, ep, site_ep)


@contextmanager
def client(log, site_ep: str):
    """Phía client: các lệnh gửi trong khối này (cùng coroutine) được ghi vào `log`."""
    install()
    token = _CLIENT.set((log, site_ep) if log is not None else None)
    try:
        yield
    finally:
        _CLIENT.reset(token)


def _peer(addr) -> str:
    t = getattr(addr, "addrTuple", None) or addr       # bacpypes3 IPv4Address / tuple (host, port) của pysnmp
    try:
        return f"{t[0]}:{t[1]}"
    except (TypeError, IndexError, KeyError):
        return str(addr)


def _sent(obj, data, addr, parse) -> None:
    try:
        tap = getattr(obj, "_frame_tap", None)
        if tap:                                        # thiết bị gửi ra: phản hồi
            log, ep, _ = tap
            log.add_response(ep, parse(data, True))
            return
        ctx = _CLIENT.get()
        if ctx:                                        # client gửi ra: lệnh
            log, site_ep = ctx
            req = parse(data, False)
            if req["transaction"] is None:
                return
            peer = _peer(addr)
            if len(_routes) >= MAX_ROUTES:
                _routes.clear()
            _routes[(peer, req["transaction"])] = log
            log.add_request(peer, site_ep, req)
    except Exception as e:
        print(f"  ?? không ghi được khung tin: {e!r}")


def _received(obj, data, addr, parse) -> None:
    try:
        tap = getattr(obj, "_frame_tap", None)
        if tap:                                        # thiết bị nhận vào: lệnh
            log, ep, site_ep = tap
            req = parse(data, False)
            if req["transaction"] is not None:
                log.add_request(ep, site_ep, req)
            return
        if not _routes:
            return
        peer = _peer(addr)
        resp = parse(data, True)
        log = _routes.pop((peer, resp["transaction"]), None)
        if log is not None:                            # client nhận vào: phản hồi của lệnh đã ghi
            log.add_response(peer, resp)
    except Exception as e:
        print(f"  ?? không ghi được khung tin: {e!r}")


def install() -> None:
    """Bọc hàm gửi / nhận của pysnmp và bacpypes3 (một lần). Gói tin đi qua nguyên vẹn."""
    global _installed
    if _installed:
        return
    _installed = True
    from bacpypes3.ipv4 import IPv4DatagramServer
    from pysnmp.carrier.asyncio.dgram.base import DgramAsyncioProtocol

    snmp_send, snmp_recv = DgramAsyncioProtocol.send_message, DgramAsyncioProtocol.datagram_received

    def send_message(self, message, address):
        _sent(self, bytes(message), address, parse_snmp)
        return snmp_send(self, message, address)

    def datagram_received(self, datagram, address):
        _received(self, bytes(datagram), address, parse_snmp)
        return snmp_recv(self, datagram, address)

    DgramAsyncioProtocol.send_message, DgramAsyncioProtocol.datagram_received = send_message, datagram_received

    bac_send, bac_recv = IPv4DatagramServer.indication, IPv4DatagramServer.confirmation

    async def indication(self, pdu):
        _sent(self, bytes(pdu.pduData), pdu.pduDestination, parse_bacnet)
        return await bac_send(self, pdu)

    async def confirmation(self, pdu):
        _received(self, bytes(pdu.pduData), pdu.pduSource, parse_bacnet)
        return await bac_recv(self, pdu)

    IPv4DatagramServer.indication, IPv4DatagramServer.confirmation = indication, confirmation
