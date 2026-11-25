"""CẦU NỐI ASYNCIO — chạy coroutine (pysnmp, bacpypes3) từ code đồng bộ (collector, write-service).

Một vòng lặp asyncio riêng chạy ở luồng nền suốt đời tiến trình; run(coro, timeout) gửi coroutine vào
đó và chờ kết quả. Thư viện giữ trạng thái theo vòng lặp (engine SNMP, ứng dụng BACnet) nên dùng chung
một vòng lặp thay vì asyncio.run mỗi lần.
"""
import asyncio, concurrent.futures, threading

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
    """Chạy coroutine trên vòng lặp nền và chờ kết quả (ném lại lỗi của coroutine).

    Hết giờ: hủy coroutine và ném TimeoutError có sẵn của Python. Trên Python 3.10,
    concurrent.futures.TimeoutError là lớp khác, nên nơi gọi bắt TimeoutError sẽ không thấy nó."""
    future = asyncio.run_coroutine_threadsafe(coro, loop())
    try:
        return future.result(timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise TimeoutError(f"quá {timeout:g} giây") from None
