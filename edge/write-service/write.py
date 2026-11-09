"""GHI QUA RÀO CHẮN — chỉ ghi điểm được phép, giá trị trong allowed hoặc trong [min, max], rồi đọc lại xác nhận.

Chạy:  make write P=bess-01.che_do V=1             (môi trường lab: ghi vào simulator)
       make write P=... V=... ARGS="--env site"   (ghi vào thiết bị THẬT — chỉ khi cố ý)

Lệnh ghi đi tới đúng địa chỉ host:port và device_id của thiết bị trong Point Map.
"""
import argparse, logging, sys, warnings
from codec import encode
from modbus_io import Connections
from point_map import DEFAULT_PATH, load_or_exit

warnings.filterwarnings("ignore")
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)


class WriteBlocked(Exception):
    """Lệnh ghi bị rào chắn từ chối."""


def find(cfg, key):
    dev_name, _, pt_name = key.partition(".")
    for d in cfg["devices"]:
        for p in d["points"]:
            if d["name"] == dev_name and p["name"] == pt_name:
                return d, p
    raise WriteBlocked(f"không có điểm '{key}' trong Point Map")


def write_guarded(cfg, conns, key, value):
    d, p = find(cfg, key)
    if not p.get("writable"):
        raise WriteBlocked(f"'{key}' không được phép ghi")
    if "allowed" not in p and not ("min" in p and "max" in p):
        raise WriteBlocked(f"'{key}' thiếu allowed hoặc khoảng min/max trong Point Map")
    if "allowed" in p and value not in p["allowed"]:
        raise WriteBlocked(f"giá trị {value} không nằm trong danh sách cho phép {p['allowed']}")
    if "min" in p and "max" in p and not p["min"] <= value <= p["max"]:
        raise WriteBlocked(f"giá trị {value} nằm ngoài khoảng cho phép [{p['min']}, {p['max']}]")
    if p["table"] != "holding":
        raise WriteBlocked("chỉ ghi được holding register")
    before = conns.read(d, p)                         # đọc trạng thái trước khi ghi
    regs = encode(value, p["type"], d["byte_order"], p.get("scale", 1))
    r = conns.client(d).write_registers(p["address"], regs, device_id=d["device_id"])
    if r.isError():
        raise RuntimeError(f"thiết bị từ chối, mã lỗi {getattr(r, 'exception_code', '?')}")
    after = conns.read(d, p)                          # đọc lại để xác nhận
    if after != value:
        raise RuntimeError(f"đọc lại ra {after}, không khớp giá trị đã ghi {value}")
    return before, after


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("point", help="ví dụ: bess-01.che_do")
    ap.add_argument("value", type=float)
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--env", default="lab", help="lab = simulator (mặc định); site = thiết bị thật")
    args = ap.parse_args()
    cfg = load_or_exit(args.config, args.env)
    c = Connections()
    try:
        before, after = write_guarded(cfg, c, args.point, args.value)
        print(f"Đã ghi {args.point}: {before} -> {after} (đã đọc lại xác nhận)")
    except WriteBlocked as e:
        print(f"RÀO CHẮN TỪ CHỐI: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"LỖI: {e}")
        sys.exit(1)
