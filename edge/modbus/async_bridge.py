"""CẦU NỐI ASYNCIO — chạy coroutine (pysnmp, bacpypes3) từ code đồng bộ (collector, write-service).

Một vòng lặp asyncio riêng chạy ở luồng nền suốt đời tiến trình; run(coro, timeout) gửi coroutine vào
đó và chờ kết quả. Thư viện giữ trạng thái theo vòng lặp (engine SNMP, ứng dụng BACnet) nên dùng chung
một vòng lặp thay vì asyncio.run mỗi lần.
"""
import asyncio, threading

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True, name="async-bridge").start()
    return _loop


def run(coro, timeout: float):
    """Chạy coroutine trên vòng lặp nền và chờ kết quả (ném lại lỗi của coroutine)."""
    return asyncio.run_coroutine_threadsafe(coro, loop()).result(timeout)
