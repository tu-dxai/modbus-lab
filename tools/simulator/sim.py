"""SIMULATOR — giả lập mọi thiết bị khai báo trong Point Map, giá trị do người kiểm thử điều khiển.

Chạy:  make sim                      (giá trị đứng yên, đặt bằng trang http://localhost:5080 hoặc make set)
       make sim ARGS=--noise        (thêm nhiễu và độ trôi theo mục sim: của từng điểm, để xem cảnh báo)

Mỗi địa chỉ host:port (sau khi áp môi trường, mặc định lab) là một Modbus TCP server riêng, giống site
thật: mỗi gateway hoặc thiết bị TCP một IP. Thiết bị cùng host:port (sau một gateway) phân biệt bằng device_id.

Hai vai trò:
  1. Nguồn dữ liệu: mỗi điểm có một giá trị hiện tại (đơn vị kỹ thuật, ví dụ 231.5 V). Giá trị khởi đầu
     là sim.base trong Point Map, chỉ đổi khi người kiểm thử đặt qua kênh điều khiển (sim_control.py)
     hoặc khi client ghi vào điểm writable qua Modbus.
  2. Nhân chứng: ghi nhật ký mọi lệnh ghi Modbus nhận được, kể cả lệnh bị từ chối (ô chỉ đọc, ô không
     khai báo, sai device_id), để kiểm tra client đã ghi gì, vào đâu.

Dùng API SimData/SimDevice của pymodbus 3.16 (API cũ sẽ bị gỡ ở bản 4):
  - ô không khai báo trong Point Map -> thiết bị trả mã lỗi 02
  - ô không có `writable: true`      -> thiết bị từ chối ghi, mã lỗi 02
"""
import argparse, asyncio, logging, threading, time, warnings
from functools import partial
from pymodbus.server import StartAsyncTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice
from codec import SIZE
from point_map import DEFAULT_PATH, load_or_exit
from sim_state import SimState, endpoint

warnings.filterwarnings("ignore")
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
HOLDING_FC = {3, 6, 16, 22, 23}


async def action(state, d, fc, start_address, address, count, registers, set_values):
    """pymodbus gọi sau khi lệnh đã qua kiểm tra địa chỉ và quyền ghi của thiết bị."""
    table = "holding" if fc in HOLDING_FC else "input"
    if set_values is not None:
        state.apply_write(d, table, start_address, registers, address, list(set_values))
    else:
        state.fill(d, table, start_address, registers)
    return None


def build_device(d, state):
    blocks = {"holding": [], "input": []}
    for p in d["points"]:
        regs = [0] * SIZE[p["type"]]                   # nội dung thật được action điền mỗi lần đọc
        blocks[p["table"]].append(SimData(p["address"], values=regs, datatype=DataType.REGISTERS,
                                          readonly=not p.get("writable", False)))
    placeholder = lambda: [SimData(9999, values=0, datatype=DataType.REGISTERS, readonly=True)]
    bits = lambda: [SimData(0, values=False, datatype=DataType.BITS, readonly=True)]
    return SimDevice(d["device_id"],
                     simdata=(bits(), bits(), blocks["holding"] or placeholder(), blocks["input"] or placeholder()),
                     action=partial(action, state, d))


class Simulator:
    """Simulator đang chạy: state để đọc/đặt trực tiếp, control_url nếu có bật kênh điều khiển."""

    def __init__(self, state: SimState, control_url: str | None):
        self.state, self.control_url = state, control_url


def start(cfg, noise=False, control_port=None, control_host="127.0.0.1") -> Simulator:
    """Khởi động simulator chạy nền (dùng cho cả kiểm thử). control_port=0 để hệ điều hành chọn cổng."""
    state = SimState(cfg, noise)
    by_endpoint: dict[str, list[dict]] = {}
    for d in cfg["devices"]:
        by_endpoint.setdefault(endpoint(d), []).append(d)
    for ep, devs in by_endpoint.items():
        host, port = devs[0]["host"], devs[0]["port"]
        site_ep = devs[0].get("site_address", ep)
        devices = [build_device(d, state) for d in devs]
        threading.Thread(target=partial(asyncio.run, StartAsyncTcpServer(
            context=devices, address=(host, port), trace_pdu=state.tracer(ep, site_ep))), daemon=True).start()
    control_url = None
    if control_port is not None:
        from sim_control import serve
        srv = serve(state, control_host, control_port)
        control_url = f"http://{control_host}:{srv.server_address[1]}"
    time.sleep(0.5)
    return Simulator(state, control_url)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--env", default="lab", help="môi trường ánh xạ địa chỉ (environments/<env>.yml)")
    ap.add_argument("--noise", action="store_true", help="thêm nhiễu và độ trôi (mục sim: trong Point Map)")
    ap.add_argument("--control-host", default="127.0.0.1", help="0.0.0.0 để điều khiển từ máy khác")
    ap.add_argument("--control-port", type=int, default=5080)
    args = ap.parse_args()
    cfg = load_or_exit(args.config, args.env)
    sim = start(cfg, args.noise, args.control_port, args.control_host)
    print(f"Simulator site {cfg.get('site', '?')}, môi trường {args.env}"
          f"{'  (có nhiễu)' if args.noise else '  (giá trị đứng yên)'}")
    print(f"Điều khiển: {sim.control_url}  (trang web, API, hoặc make set P=... V=...)")
    shown = None
    for d in sorted(cfg["devices"], key=lambda d: (endpoint(d), d["device_id"])):
        if endpoint(d) != shown:
            shown = endpoint(d)
            print(f"  Modbus TCP {shown}  (site {d.get('site_address', shown)})")
        print(f"    thiết bị {d['device_id']}  {d['name']}  (byte order {d['byte_order']})")
        for p in d["points"]:
            w = "  [ghi được]" if p.get("writable") else ""
            print(f"        {p['table']:8} ngăn {p['address']:<4} {p['name']:14} {p['type']:8} {p.get('unit', '')}{w}")
    print("Nhấn Ctrl+C để dừng.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nĐã dừng simulator.")
