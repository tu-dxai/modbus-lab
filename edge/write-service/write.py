"""GHI QUA RÀO CHẮN — chỉ ghi điểm được phép, giá trị trong allowed hoặc trong [min, max], rồi đọc lại xác nhận.

Chạy:  make write P=bess-01.che_do V=1             (môi trường lab: ghi vào simulator)
       make write P=crah-01.diem_dat_nhiet V=21   (BACnet: ghi kèm priority của điểm)
       make write P=crah-01.diem_dat_nhiet V=relinquish   (BACnet: nhả lệnh ở priority đó)
       make write P=... V=... ARGS="--env site"   (ghi vào thiết bị THẬT — chỉ khi cố ý)

Modbus: ghi holding register. BACnet: WriteProperty presentValue kèm priority của điểm trong Point Map;
khi xong việc điều khiển thì nhả lệnh (relinquish_guarded) để trả quyền cho mức ưu tiên thấp hơn.
SNMP: chỉ đọc.

Lệnh ghi đi tới đúng địa chỉ và device_id của thiết bị trong Point Map. Mỗi lần gọi — ghi được, bị rào chắn
chặn, hay bị thiết bị từ chối — đều để lại dấu trong nhật ký kiểm toán (audit.py, mặc định
var/audit/writes.jsonl; xem bằng make audit): một dòng "attempt" ngay trước khi gửi lệnh (không ghi được
dòng này thì không gửi), rồi một dòng kết quả.

Đọc lại phải khớp đúng giá trị thiết bị lưu được (stored_value). BACnet: lệnh đã gửi mà không xác nhận được
(không trả lời, đọc lại không khớp) thì nhả lệnh ngay ở priority đó, để nó không âm thầm có hiệu lực sau này.
"""
import argparse, getpass, logging, math, struct, sys, warnings
from audit import DEFAULT_PATH as AUDIT_PATH, AuditLog
from codec import decode, encode
from i18n import Translatable
from modbus_io import Connections, ReadError
from point_map import DEFAULT_PATH, load_or_exit

warnings.filterwarnings("ignore")
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)


class WriteBlocked(Translatable):
    """Lệnh ghi bị rào chắn từ chối (chưa gửi gì tới thiết bị)."""


class WriteFailed(Translatable):
    """Lệnh ghi đã gửi nhưng thiết bị từ chối, không trả lời, hoặc đọc lại không khớp."""


class AuditFailed(Translatable):
    """Thiết bị ĐÃ nhận lệnh ghi (đọc lại khớp) nhưng không ghi được dòng kết quả vào nhật ký kiểm toán.
    Không phải lệnh ghi thất bại: đừng ghi lại lần nữa. Dòng "attempt" của lệnh này vẫn có trong nhật ký."""


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


def stored_value(d: dict, p: dict, value: float) -> float:
    """Giá trị thiết bị sẽ lưu và báo lại khi đọc — đọc lại phải khớp đúng số này.

    Modbus số nguyên: giá trị phải là bội số của hệ số (scale 0.1 thì 21.3 được, 21.35 bị chặn) để thiết bị
    nhận đúng con số người dùng nhập, không làm tròn ngầm. float32 và BACnet REAL: số thực 32 bit gần nhất
    (21.3 lưu thành 21.299999...), so với chính số đó thay vì số người dùng nhập.
    """
    if d.get("protocol") == "bacnet":
        if p["object"].split(",")[0].strip().startswith("binary"):
            return 1 if value else 0
        try:
            return round(struct.unpack(">f", struct.pack(">f", value))[0], 6)   # như read_bacnet
        except (struct.error, OverflowError):
            raise WriteBlocked("write.out_of_type_range", value=value, type="REAL", scale=1) from None
    scale = p.get("scale", 1)
    try:
        regs = encode(value, p["type"], d["byte_order"], scale)
    except (struct.error, OverflowError, ValueError):
        raise WriteBlocked("write.out_of_type_range", value=value, type=p["type"], scale=scale) from None
    if p["type"] != "float32" and not math.isclose(value / scale, round(value / scale), rel_tol=0, abs_tol=1e-6):
        raise WriteBlocked("write.not_representable", value=value, step=scale)
    return decode(regs, p["type"], d["byte_order"], scale)         # như read_point


def _write_modbus(conns, d: dict, p: dict, value, expected, state: dict, attempt) -> None:
    if p["table"] != "holding":
        raise WriteBlocked("write.not_holding")
    state["before"] = conns.read(d, p)                # đọc trạng thái trước khi ghi
    attempt()                                         # nhật ký trước khi gửi; không ghi được thì không gửi
    regs = encode(value, p["type"], d["byte_order"], p.get("scale", 1))
    r = conns.client(d).write_registers(p["address"], regs, device_id=d["device_id"])
    if r.isError():
        raise WriteFailed("write.device_rejected", code=getattr(r, "exception_code", "?"))
    state["after"] = conns.read(d, p)                 # đọc lại để xác nhận
    if state["after"] != expected:
        raise WriteFailed("write.readback_mismatch", after=state["after"], value=expected)


def _write_bacnet(conns, d: dict, p: dict, value, expected, state: dict, attempt) -> None:
    from bacnet_io import relinquish_bacnet, write_bacnet
    frames = getattr(conns, "frames", None)
    state["before"] = conns.read(d, p)
    attempt()
    try:
        write_bacnet(d, p, value, frames)
    except ReadError as e:                            # không trả lời: có thể thiết bị đã nhận lệnh
        _release(relinquish_bacnet, d, p, frames, state)
        raise WriteFailed("write.no_answer", detail=str(e)) from None
    except Translatable as e:                         # thiết bị trả lỗi: lệnh không vào mảng ưu tiên
        raise WriteFailed("write.device_rejected", code=e.params.get("detail", e.code)) from None
    try:
        state["after"] = conns.read(d, p)
        if state["after"] != expected:                # ví dụ: đang có lệnh ở mức ưu tiên cao hơn giữ giá trị
            raise WriteFailed("write.readback_mismatch", after=state["after"], value=expected)
    except Exception:
        # Lệnh đã nằm trong mảng ưu tiên nhưng không xác nhận được: nhả ngay, để nó không âm thầm có hiệu lực
        # khi mức ưu tiên cao hơn nhả ra sau này.
        _release(relinquish_bacnet, d, p, frames, state)
        raise


def _release(relinquish_bacnet, d, p, frames, state: dict) -> None:
    try:
        relinquish_bacnet(d, p, frames)
        state["relinquished"] = True
    except Exception as e:
        state["relinquished"] = False
        print(f"  xx Không nhả được lệnh {d['name']}.{p['name']} sau khi ghi thất bại: {e}", file=sys.stderr)


def _attempt_hook(audit, cfg, actor, key, value, state):
    """Hàm gọi ngay trước khi gửi lệnh: ghi dòng "attempt"; không ghi được thì chặn lệnh."""
    def attempt():
        state["sent"] = True
        if audit is None:
            return
        try:
            _audit(audit, cfg, actor, key, value, state, "attempt", None)
        except Exception as e:
            state["sent"] = False
            raise WriteBlocked("write.audit_unavailable", detail=str(e) or type(e).__name__) from None
    return attempt


def _new_state() -> dict:
    return {"device": None, "point": None, "before": None, "after": None, "sent": False, "relinquished": None}


def write_guarded(cfg, conns, key, value, audit: AuditLog | None = None, actor: str = "?"):
    """Ghi qua rào chắn; trả về (trước, sau).

    Có audit: dòng "attempt" trước khi gửi lệnh (không ghi được thì không gửi), rồi dòng kết quả
    (written / blocked / failed). Ghi xong mà không ghi được dòng kết quả -> AuditFailed (thiết bị ĐÃ đổi)."""
    state = _new_state()
    try:
        d, p = find(cfg, key)
        state.update(device=d, point=p)
        check(p, key, value)
        proto = d.get("protocol", "modbus")
        if proto not in ("bacnet", "modbus"):
            raise WriteBlocked("write.not_writable", key=key)
        expected = stored_value(d, p, value)
        attempt = _attempt_hook(audit, cfg, actor, key, value, state)
        (_write_bacnet if proto == "bacnet" else _write_modbus)(conns, d, p, value, expected, state, attempt)
    except Exception as e:
        _audit_outcome(audit, cfg, actor, key, value, state, e)
        raise
    _audit_written(audit, cfg, actor, key, value, state, "written")
    return state["before"], state["after"]


def relinquish_guarded(cfg, conns, key, audit: AuditLog | None = None, actor: str = "?"):
    """BACnet: nhả lệnh (ghi Null ở priority của điểm); trả về giá trị sau khi nhả. Cũng qua rào chắn và nhật ký."""
    from bacnet_io import relinquish_bacnet
    state = _new_state()
    try:
        d, p = find(cfg, key)
        state.update(device=d, point=p)
        if not p.get("writable") or d.get("protocol") != "bacnet":
            raise WriteBlocked("write.not_bacnet", key=key)
        state["before"] = conns.read(d, p)
        _attempt_hook(audit, cfg, actor, key, None, state)()
        try:
            relinquish_bacnet(d, p, getattr(conns, "frames", None))
        except ReadError as e:
            raise WriteFailed("write.no_answer", detail=str(e)) from None
        except Translatable as e:
            raise WriteFailed("write.device_rejected", code=e.params.get("detail", e.code)) from None
        state["after"] = conns.read(d, p)
    except Exception as e:
        _audit_outcome(audit, cfg, actor, key, None, state, e)
        raise
    _audit_written(audit, cfg, actor, key, None, state, "released")
    return state["after"]


def _audit_outcome(audit, cfg, actor, key, value, state, err) -> None:
    """Dòng kết quả cho lệnh không thành: blocked (chưa gửi gì) hoặc failed. Lỗi ghi nhật ký ở đây không
    được che lỗi gốc; nếu lệnh đã gửi thì dòng "attempt" vẫn còn trong nhật ký."""
    if audit is None:
        return
    outcome = "blocked" if isinstance(err, WriteBlocked) and not state["sent"] else "failed"
    try:
        _audit(audit, cfg, actor, key, value, state, outcome, err)
    except Exception as e:
        print(f"  xx Không ghi được nhật ký kiểm toán ({outcome} {key}): {e}", file=sys.stderr)


def _audit_written(audit, cfg, actor, key, value, state, outcome) -> None:
    if audit is None:
        return
    try:
        _audit(audit, cfg, actor, key, value, state, outcome, None)
    except Exception as e:
        raise AuditFailed("write.audit_failed", point=key, before=state["before"], after=state["after"],
                          detail=str(e) or type(e).__name__) from None


def _audit(audit, cfg, actor, key, value, state, outcome, err) -> None:
    d, p = state["device"], state["point"]
    audit.record(actor=actor, env=cfg.get("env"), site=cfg.get("site"), point=key,
                 device=d["name"] if d else None,
                 device_id=(d.get("device_id", d.get("device_instance"))) if d else None,
                 site_endpoint=(d.get("site_address") or f"{d.get('host')}:{d.get('port')}") if d else None,
                 value=value, outcome=outcome, before=state["before"], after=state["after"],
                 priority=p.get("priority") if p else None, relinquished=state["relinquished"],
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
    except AuditFailed as e:
        print(f"CẢNH BÁO: {e}")
        sys.exit(3)
    except Exception as e:
        print(f"LỖI: {e}")
        sys.exit(1)
