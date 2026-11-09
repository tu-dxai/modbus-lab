"""GHI QUA RÀO CHẮN — chỉ ghi điểm được phép, giá trị trong allowed hoặc trong [min, max], rồi đọc lại xác nhận.

Chạy:  make write P=bess-01.che_do V=1             (môi trường lab: ghi vào simulator)
       make write P=... V=... ARGS="--env site"   (ghi vào thiết bị THẬT — chỉ khi cố ý)

Lệnh ghi đi tới đúng địa chỉ host:port và device_id của thiết bị trong Point Map.
"""
import argparse, logging, sys, warnings
from codec import encode
from i18n import Translatable
from modbus_io import Connections
from point_map import DEFAULT_PATH, load_or_exit

warnings.filterwarnings("ignore")
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)


class WriteBlocked(Translatable):
    """Lệnh ghi bị rào chắn từ chối (chưa gửi gì tới thiết bị)."""


class WriteFailed(Translatable):
    """Lệnh ghi đã gửi nhưng thiết bị từ chối, hoặc đọc lại không khớp."""


def find(cfg, key):
    dev_name, _, pt_name = key.partition(".")
    for d in cfg["devices"]:
        for p in d["points"]:
            if d["name"] == dev_name and p["name"] == pt_name:
                return d, p
    raise WriteBlocked("write.unknown_point", key=key)


def write_guarded(cfg, conns, key, value):
    d, p = find(cfg, key)
    if not p.get("writable"):
        raise WriteBlocked("write.not_writable", key=key)
    if "allowed" not in p and not ("min" in p and "max" in p):
        raise WriteBlocked("write.no_limits", key=key)
    if "allowed" in p and value not in p["allowed"]:
        raise WriteBlocked("write.not_allowed", value=value, allowed=p["allowed"])
    if "min" in p and "max" in p and not p["min"] <= value <= p["max"]:
        raise WriteBlocked("write.out_of_range", value=value, min=p["min"], max=p["max"])
    if p["table"] != "holding":
        raise WriteBlocked("write.not_holding")
    before = conns.read(d, p)                         # đọc trạng thái trước khi ghi
    regs = encode(value, p["type"], d["byte_order"], p.get("scale", 1))
    r = conns.client(d).write_registers(p["address"], regs, device_id=d["device_id"])
    if r.isError():
        raise WriteFailed("write.device_rejected", code=getattr(r, "exception_code", "?"))
    after = conns.read(d, p)                          # đọc lại để xác nhận
    if after != value:
        raise WriteFailed("write.readback_mismatch", after=after, value=value)
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
