"""GHI QUA RÀO CHẮN — chỉ ghi điểm được phép, giá trị trong allowed hoặc trong [min, max], rồi đọc lại xác nhận.

Chạy:  make write P=bess-01.che_do V=1             (môi trường lab: ghi vào simulator)
       make write P=crah-01.diem_dat_nhiet V=21   (BACnet: ghi kèm priority của điểm)
       make write P=crah-01.diem_dat_nhiet V=relinquish   (BACnet: nhả lệnh ở priority đó)
       make write P=... V=... ARGS="--env site"   (ghi vào thiết bị THẬT — chỉ khi cố ý)

Modbus: ghi holding register. BACnet: WriteProperty presentValue kèm priority của điểm trong Point Map;
khi xong việc điều khiển thì nhả lệnh (relinquish_guarded) để trả quyền cho mức ưu tiên thấp hơn.
SNMP: chỉ đọc.

Lệnh ghi đi tới đúng địa chỉ và device_id của thiết bị trong Point Map. Mỗi lần gọi — ghi được, bị rào chắn
chặn, hay bị thiết bị từ chối — đều để lại một dòng trong nhật ký kiểm toán (audit.py, mặc định
var/audit/writes.jsonl; xem bằng make audit).
"""
import argparse, getpass, logging, sys, warnings
from audit import DEFAULT_PATH as AUDIT_PATH, AuditLog
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


def check(p: dict, key: str, value) -> None:
    """Rào chắn: chỉ điểm writable, có giới hạn, giá trị nằm trong allowed hoặc [min, max]."""
    if not p.get("writable"):
        raise WriteBlocked("write.not_writable", key=key)
    if "allowed" not in p and not ("min" in p and "max" in p):
        raise WriteBlocked("write.no_limits", key=key)
    if "allowed" in p and value not in p["allowed"]:
        raise WriteBlocked("write.not_allowed", value=value, allowed=p["allowed"])
    if "min" in p and "max" in p and not p["min"] <= value <= p["max"]:
        raise WriteBlocked("write.out_of_range", value=value, min=p["min"], max=p["max"])


def _write_modbus(conns, d: dict, p: dict, value, state: dict) -> None:
    if p["table"] != "holding":
        raise WriteBlocked("write.not_holding")
    state["before"] = conns.read(d, p)                # đọc trạng thái trước khi ghi
    regs = encode(value, p["type"], d["byte_order"], p.get("scale", 1))
    r = conns.client(d).write_registers(p["address"], regs, device_id=d["device_id"])
    if r.isError():
        raise WriteFailed("write.device_rejected", code=getattr(r, "exception_code", "?"))
    state["after"] = conns.read(d, p)                 # đọc lại để xác nhận
    if state["after"] != value:
        raise WriteFailed("write.readback_mismatch", after=state["after"], value=value)


def _write_bacnet(conns, d: dict, p: dict, value, state: dict) -> None:
    from bacnet_io import write_bacnet
    state["before"] = conns.read(d, p)
    try:
        write_bacnet(d, p, value, getattr(conns, "frames", None))
    except Translatable as e:
        raise WriteFailed("write.device_rejected", code=e.params.get("detail", e.code)) from None
    state["after"] = conns.read(d, p)
    if state["after"] != value:                       # ví dụ: đang có lệnh ở mức ưu tiên cao hơn giữ giá trị
        raise WriteFailed("write.readback_mismatch", after=state["after"], value=value)


def write_guarded(cfg, conns, key, value, audit: AuditLog | None = None, actor: str = "?"):
    """Ghi qua rào chắn; trả về (trước, sau). Có audit thì mọi kết quả đều được ghi nhật ký."""
    state = {"device": None, "point": None, "before": None, "after": None}
    try:
        d, p = find(cfg, key)
        state.update(device=d, point=p)
        check(p, key, value)
        proto = d.get("protocol", "modbus")
        if proto == "bacnet":
            _write_bacnet(conns, d, p, value, state)
        elif proto == "modbus":
            _write_modbus(conns, d, p, value, state)
        else:
            raise WriteBlocked("write.not_writable", key=key)
    except Exception as e:
        if audit:
            _audit(audit, cfg, actor, key, value, state, "blocked" if isinstance(e, WriteBlocked) else "failed", e)
        raise
    if audit:
        _audit(audit, cfg, actor, key, value, state, "written", None)
    return state["before"], state["after"]


def relinquish_guarded(cfg, conns, key, audit: AuditLog | None = None, actor: str = "?"):
    """BACnet: nhả lệnh (ghi Null ở priority của điểm); trả về giá trị sau khi nhả. Cũng qua rào chắn và nhật ký."""
    from bacnet_io import relinquish_bacnet
    state = {"device": None, "point": None, "before": None, "after": None}
    try:
        d, p = find(cfg, key)
        state.update(device=d, point=p)
        if not p.get("writable") or d.get("protocol") != "bacnet":
            raise WriteBlocked("write.not_bacnet", key=key)
        state["before"] = conns.read(d, p)
        try:
            relinquish_bacnet(d, p, getattr(conns, "frames", None))
        except Translatable as e:
            raise WriteFailed("write.device_rejected", code=e.params.get("detail", e.code)) from None
        state["after"] = conns.read(d, p)
    except Exception as e:
        if audit:
            _audit(audit, cfg, actor, key, None, state, "blocked" if isinstance(e, WriteBlocked) else "failed", e)
        raise
    if audit:
        _audit(audit, cfg, actor, key, None, state, "released", None)
    return state["after"]


def _audit(audit, cfg, actor, key, value, state, outcome, err) -> None:
    d, p = state["device"], state["point"]
    audit.record(actor=actor, env=cfg.get("env"), site=cfg.get("site"), point=key,
                 device=d["name"] if d else None,
                 device_id=(d.get("device_id", d.get("device_instance"))) if d else None,
                 site_endpoint=(d.get("site_address") or f"{d.get('host')}:{d.get('port')}") if d else None,
                 value=value, outcome=outcome, before=state["before"], after=state["after"],
                 priority=p.get("priority") if p else None,
                 code=getattr(err, "code", None) if err else None,
                 error=(str(err) or type(err).__name__) if err else None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("point", help="ví dụ: bess-01.che_do")
    ap.add_argument("value", help="số, hoặc relinquish (BACnet: nhả lệnh)")
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--env", default="lab", help="lab = simulator (mặc định); site = thiết bị thật")
    ap.add_argument("--audit", default=AUDIT_PATH, help=f"file nhật ký kiểm toán (mặc định {AUDIT_PATH})")
    args = ap.parse_args()
    cfg = load_or_exit(args.config, args.env)
    c = Connections()
    log, actor = AuditLog(args.audit), f"cli:{getpass.getuser()}"
    try:
        if args.value.lower() == "relinquish":
            after = relinquish_guarded(cfg, c, args.point, log, actor)
            print(f"Đã nhả lệnh {args.point}: giá trị hiện tại {after}")
        else:
            before, after = write_guarded(cfg, c, args.point, float(args.value), log, actor)
            print(f"Đã ghi {args.point}: {before} -> {after} (đã đọc lại xác nhận)")
    except WriteBlocked as e:
        print(f"RÀO CHẮN TỪ CHỐI: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"LỖI: {e}")
        sys.exit(1)
