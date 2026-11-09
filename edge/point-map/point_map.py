"""POINT MAP — đọc devices.yml, áp môi trường (lab/site), và kiểm tra trước khi dùng.

Một con số sai trong Modbus không báo lỗi, nó chỉ âm thầm sai. Vì vậy Point Map hỏng
phải bị chặn ngay lúc khởi động, kèm tên thiết bị và điểm để sửa.

Môi trường:
  - Point Map ghi địa chỉ THẬT của site (host, port trên từng thiết bị).
  - env "site": dùng nguyên địa chỉ thật — chỉ khi cố ý kết nối thiết bị thật.
  - env khác (mặc định "lab"): đọc environments/<env>.yml cạnh Point Map, ánh xạ từng địa chỉ
    thật "host:port" sang địa chỉ khác (simulator). Mỗi địa chỉ thật phải có đúng một dòng.

Kiểm tra:
  - thiết bị có host, port (1-65535), device_id (số nguyên); timeout nếu có thì > 0
  - thiết bị trùng host:port = cùng sau một gateway: device_id không trùng, trong 1-247, cùng timeout
  - thiết bị riêng một địa chỉ: device_id trong 0-255
  - byte_order thuộc ABCD, CDAB, BADC, DCBA
  - điểm có đủ name, table, address, type; table là holding hoặc input
  - type hợp lệ (theo codec)
  - hai điểm cùng thiết bị, cùng bảng không đè ô nhớ của nhau (kiểu 32 bit chiếm 2 ô)
  - điểm writable có allowed, hoặc có đủ min và max với min <= max
  - điểm có khóa unit (chuỗi rỗng được phép cho đại lượng không đơn vị)
"""
import sys
from pathlib import Path
import yaml
from codec import SIZE

DEFAULT_PATH = "edge/point-map/devices.yml"
DEFAULT_ENV = "lab"
SITE_ENV = "site"
BYTE_ORDERS = ("ABCD", "CDAB", "BADC", "DCBA")
TABLES = ("holding", "input")
REQUIRED = ("name", "table", "address", "type")
CONNECTION = ("host", "port", "device_id")


class PointMapError(Exception):
    """Point Map hoặc file môi trường có lỗi; .errors là danh sách lỗi."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _addr(d: dict) -> str:
    """Địa chỉ để hiển thị trong lỗi: địa chỉ thật của site nếu đã ánh xạ."""
    return d.get("site_address") or f"{d.get('host')}:{d.get('port')}"


def _parse_address(text) -> tuple[str, int] | None:
    host, sep, port = str(text).rpartition(":")
    if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        return None
    return host, int(port)


# ---------- đọc và áp môi trường ----------
def _apply_environment(cfg: dict, env: str, env_file: Path) -> list[str]:
    if not env_file.exists():
        return [f"không có file môi trường '{env}' ({env_file}); dùng --env {SITE_ENV} để kết nối địa chỉ thật"]
    mapping = (yaml.safe_load(env_file.read_text(encoding="utf-8")) or {}).get("addresses") or {}
    errors, targets = [], {}
    for src, dst in mapping.items():
        if _parse_address(dst) is None:
            errors.append(f"môi trường {env}: {src} -> {dst!r} không đúng dạng host:port")
        elif dst in targets:
            errors.append(f"môi trường {env}: {targets[dst]} và {src} cùng trỏ tới {dst}")
        else:
            targets[dst] = src
    used = set()
    for d in cfg.get("devices", []):
        src = f"{d.get('host')}:{d.get('port')}"
        if src not in mapping:
            errors.append(f"môi trường {env}: chưa có địa chỉ cho {src} (thiết bị {d.get('name', '?')})")
            continue
        used.add(src)
        parsed = _parse_address(mapping[src])
        if parsed:
            d["site_address"] = src
            d["host"], d["port"] = parsed
    errors += [f"môi trường {env}: {src} không thuộc thiết bị nào trong Point Map" for src in mapping if src not in used]
    return errors


def read(path: str = DEFAULT_PATH, env: str = DEFAULT_ENV) -> dict:
    """Đọc Point Map và áp môi trường, chưa kiểm tra nội dung. Lỗi môi trường -> PointMapError."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if env != SITE_ENV:
        errors = _apply_environment(cfg, env, Path(path).parent / "environments" / f"{env}.yml")
        if errors:
            raise PointMapError(errors)
    cfg["env"] = env
    return cfg


def load(path: str = DEFAULT_PATH, env: str = DEFAULT_ENV) -> dict:
    """Đọc, áp môi trường và kiểm tra; có lỗi thì PointMapError với mọi lỗi."""
    cfg = read(path, env)
    errors = validate(cfg)
    if errors:
        raise PointMapError(errors)
    return cfg


def load_or_exit(path: str = DEFAULT_PATH, env: str = DEFAULT_ENV) -> dict:
    """Gọi khi khởi động chương trình: Point Map hỏng thì in mọi lỗi rồi dừng."""
    try:
        return load(path, env)
    except PointMapError as e:
        print(f"Point Map {path} (môi trường {env}) có {len(e.errors)} lỗi:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        raise SystemExit(1)


# ---------- kiểm tra ----------
def _span(start: int, size: int) -> str:
    return str(start) if size == 1 else f"{start}-{start + size - 1}"


def _check_writable(key: str, p: dict) -> list[str]:
    if not p.get("writable"):
        return []
    if "allowed" in p:
        return [] if p["allowed"] else [f"{key}: allowed rỗng, điểm ghi được sẽ không ghi được giá trị nào"]
    has_min, has_max = "min" in p, "max" in p
    if not has_min and not has_max:
        return [f"{key}: điểm ghi được nhưng thiếu allowed hoặc khoảng min/max"]
    if has_min != has_max:
        return [f"{key}: khoảng ghi cần đủ cả min và max (đang chỉ có {'min' if has_min else 'max'})"]
    if p["min"] > p["max"]:
        return [f"{key}: min {p['min']} lớn hơn max {p['max']}"]
    return []


def _check_connection(d: dict) -> list[str]:
    dev = d.get("name", "?")
    missing = [f for f in CONNECTION if f not in d]
    errors = [f"{dev}: thiếu trường kết nối {', '.join(missing)}"] if missing else []
    if "host" in d and (not isinstance(d["host"], str) or not d["host"]):
        errors.append(f"{dev}: host {d['host']!r} không hợp lệ")
    if "port" in d and not (_is_int(d["port"]) and 1 <= d["port"] <= 65535):
        errors.append(f"{dev}: port {d['port']!r} không hợp lệ (số nguyên 1-65535)")
    if "device_id" in d and not (_is_int(d["device_id"]) and 0 <= d["device_id"] <= 255):
        errors.append(f"{dev}: device_id {d['device_id']!r} không hợp lệ (số nguyên 0-255)")
    if "timeout" in d and not (isinstance(d["timeout"], (int, float)) and not isinstance(d["timeout"], bool)
                               and d["timeout"] > 0):
        errors.append(f"{dev}: timeout {d['timeout']!r} không hợp lệ (số giây > 0)")
    return errors


def _check_shared_addresses(devices: list[dict]) -> list[str]:
    """Thiết bị trùng host:port nằm sau cùng một gateway."""
    groups: dict[tuple, list[dict]] = {}
    for d in devices:
        if all(f in d for f in CONNECTION):
            groups.setdefault((d["host"], d["port"]), []).append(d)
    errors = []
    for group in groups.values():
        if len(group) < 2:
            continue
        addr = _addr(group[0])
        owner: dict = {}
        for d in group:
            did = d["device_id"]
            if did in owner:
                errors.append(f"trùng device_id {did} tại {addr}: {owner[did]} và {d['name']}")
            else:
                owner[did] = d["name"]
            if _is_int(did) and not 1 <= did <= 247 and 0 <= did <= 255:
                errors.append(f"{d['name']}: device_id {did} không hợp lệ sau gateway {addr} "
                              f"(địa chỉ RTU trên bus chỉ 1-247)")
        timeouts = {d["name"]: d.get("timeout") for d in group}
        if len(set(timeouts.values())) > 1:
            listed = ", ".join(f"{n}={t if t is not None else 'mặc định'}" for n, t in timeouts.items())
            errors.append(f"thiết bị cùng gateway {addr} phải cùng timeout: {listed}")
    return errors


def validate(cfg: dict) -> list[str]:
    """Trả về danh sách lỗi; rỗng nghĩa là Point Map hợp lệ."""
    errors: list[str] = []
    if "modbus" in cfg:
        errors.append("khóa modbus: đã bỏ — khai báo host, port, device_id trên từng thiết bị")
    devices = cfg.get("devices", [])
    for d in devices:
        dev = d.get("name", "?")
        errors += _check_connection(d)
        if d.get("byte_order") not in BYTE_ORDERS:
            errors.append(f"{dev}: byte_order {d.get('byte_order')!r} không hợp lệ "
                          f"(chỉ nhận {', '.join(BYTE_ORDERS)})")

        used: dict[str, list[tuple[int, int, str]]] = {t: [] for t in TABLES}   # bảng -> (ô đầu, số ô, tên)
        for p in d.get("points", []):
            key = f"{dev}.{p.get('name', '?')}"
            missing = [f for f in REQUIRED if f not in p]
            if missing:
                errors.append(f"{key}: thiếu trường bắt buộc {', '.join(missing)}")
            if "unit" not in p:
                errors.append(f"{key}: thiếu unit (dùng unit: \"\" nếu không có đơn vị)")
            errors += _check_writable(key, p)
            if "table" in p and p["table"] not in TABLES:
                errors.append(f"{key}: table {p['table']!r} không hợp lệ (chỉ nhận {', '.join(TABLES)})")
            if "type" in p and p["type"] not in SIZE:
                errors.append(f"{key}: type {p['type']!r} không hợp lệ (chỉ nhận {', '.join(SIZE)})")
            if missing or p["table"] not in TABLES or p["type"] not in SIZE:
                continue                                   # không biết chắc ô nào, bỏ qua kiểm tra đè
            start, size = p["address"], SIZE[p["type"]]
            for o_start, o_size, o_key in used[p["table"]]:
                if start < o_start + o_size and o_start < start + size:
                    errors.append(f"{key} ({p['table']} {_span(start, size)}) đè lên "
                                  f"{o_key} ({p['table']} {_span(o_start, o_size)})")
            used[p["table"]].append((start, size, key))
    errors += _check_shared_addresses(devices)
    return errors
