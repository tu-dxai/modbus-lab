"""SIMULATOR — giả lập mọi thiết bị khai báo trong Point Map, giá trị do người kiểm thử điều khiển.

Chạy:  make sim                      (giá trị chỉ đổi khi đặt bằng tay: trang http://localhost:5080 hoặc make set)
       make sim ARGS="--auto 5"     (tự thay đổi mỗi 5 giây: dao động quanh giá trị đặt gần nhất, biên độ sim.noise)

Mỗi địa chỉ (sau khi áp môi trường, mặc định lab) là một server riêng, giống site thật:
  - Modbus TCP: mỗi gateway hoặc thiết bị TCP một host:port; thiết bị sau gateway phân biệt bằng device_id;
  - Modbus RTU: mỗi bus RS-485 một cổng serial ảo (vserial.py), client mở đầu kia như cổng USB-RS485;
  - SNMP: mỗi thiết bị một agent (snmp_agent.py); BACnet/IP: mỗi thiết bị một device (bacnet_device.py).

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
from pymodbus import FramerType
from pymodbus.server import StartAsyncSerialServer, StartAsyncTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice
from codec import SIZE
from point_map import DEFAULT_PATH, device_meta, load_or_exit, point_ref
from sim_state import SimState, endpoint
from vserial import VirtualSerial

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


def start(cfg, control_port=None, control_host="127.0.0.1", frames=500, auto=0) -> Simulator:
    """Khởi động simulator chạy nền (dùng cho cả kiểm thử). control_port=0 để hệ điều hành chọn cổng.

    frames: số cặp khung tin hỏi/đáp gần nhất được giữ lại để xem byte thô.
    auto: giây giữa hai lần tự thay đổi giá trị; 0 = chỉ đặt bằng tay (đổi được lúc chạy qua /api/auto).
    """
    state = SimState(cfg, frames, auto)
    threading.Thread(target=state.run_auto, daemon=True).start()
    by_endpoint: dict[str, list[dict]] = {}
    for d in cfg["devices"]:
        by_endpoint.setdefault(endpoint(d), []).append(d)
    for ep, devs in by_endpoint.items():
        site_ep = devs[0].get("site_address", ep)
        proto = devs[0].get("protocol", "modbus")
        if proto == "snmp":                              # agent SNMP: mỗi thiết bị một địa chỉ riêng
            from snmp_agent import start_agent
            start_agent(state, devs[0])
            continue
        if proto == "bacnet":
            from bacnet_device import start_device
            start_device(state, devs[0])
            continue
        devices = [build_device(d, state) for d in devs]
        hooks = {"trace_pdu": state.tracer(ep, site_ep)}
        if devs[0].get("transport") == "rtu":            # bus RS-485: cổng serial ảo, client mở đầu kia
            s = devs[0]["serial"]
            line = VirtualSerial(s["port"])
            server = StartAsyncSerialServer(context=devices, port=line.device_path, framer=FramerType.RTU,
                                            baudrate=s["baudrate"], parity=s.get("parity", "N"),
                                            stopbits=s.get("stop_bits", 1), bytesize=s.get("bytesize", 8),
                                            trace_packet=state.frames.tracer(ep, site_ep, rtu=True), **hooks)
        else:
            server = StartAsyncTcpServer(context=devices, address=(devs[0]["host"], devs[0]["port"]),
                                         trace_packet=state.frames.tracer(ep, site_ep), **hooks)
        threading.Thread(target=partial(asyncio.run, server), daemon=True).start()
    control_url = None
    if control_port is not None:
        from sim_control import serve
        srv = serve(state, control_host, control_port)
        control_url = f"http://{control_host}:{srv.server_address[1]}"
    time.sleep(0.5)
    return Simulator(state, control_url)


KIND = {"modbus": "Modbus TCP", "snmp": "SNMP", "bacnet": "BACnet/IP"}


def banner(cfg) -> list[str]:
    """Danh sách thiết bị in ra khi khởi động, nhóm theo địa chỉ; đủ mọi giao thức."""
    def order(d):
        m = device_meta(d)
        return endpoint(d), m.get("id") or m.get("instance") or 0

    lines, shown = [], None
    for d in sorted(cfg["devices"], key=order):
        ep, m = endpoint(d), device_meta(d)
        if ep != shown:
            shown = ep
            kind = "Modbus RTU" if ep.startswith("rtu:") else KIND[m["protocol"]]
            where = ep.removeprefix("rtu:")
            lines.append(f"  {kind} {where}  (site {d.get('site_address', where).removeprefix('rtu:')})")
        if m["protocol"] == "snmp":
            info = f"SNMP v{m['version']}"
        elif m["protocol"] == "bacnet":
            info = f"device instance {m['instance']}"
        else:
            info = f"thiết bị {m['id']}, byte order {m['order']}"
        lines.append(f"    {d['name']}  ({info})")
        for p in d["points"]:
            w = "  [ghi được]" if p.get("writable") else ""
            lines.append(f"        {point_ref(d, p):34} {p['name']:16} {p.get('unit', '')}{w}")
    return lines


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--env", default="lab", help="môi trường ánh xạ địa chỉ (environments/<env>.yml)")
    ap.add_argument("--auto", type=int, default=0,
                    help="tự thay đổi giá trị mỗi N giây (1-3600); mặc định 0 = chỉ đặt bằng tay")
    ap.add_argument("--control-host", default="127.0.0.1", help="0.0.0.0 để điều khiển từ máy khác")
    ap.add_argument("--control-port", type=int, default=5080)
    ap.add_argument("--frames", type=int, default=500, help="số cặp khung tin gần nhất giữ lại để xem")
    args = ap.parse_args()
    cfg = load_or_exit(args.config, args.env)
    if not 0 <= args.auto <= SimState.AUTO_MAX:
        ap.error(f"--auto phải từ 0 đến {SimState.AUTO_MAX}")
    sim = start(cfg, args.control_port, args.control_host, args.frames, args.auto)
    print(f"Simulator site {cfg.get('site', '?')}, môi trường {args.env}, "
          f"{f'tự thay đổi mỗi {args.auto} giây' if args.auto else 'giá trị chỉ đổi khi đặt bằng tay'}")
    print(f"Điều khiển: {sim.control_url}  (trang web, API, hoặc make set P=... V=...)")
    print("\n".join(banner(cfg)))
    print("Nhấn Ctrl+C để dừng.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nĐã dừng simulator.")
