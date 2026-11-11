"""POINT MAP — đọc devices.yml, áp môi trường (lab/site), và kiểm tra trước khi dùng.

Một con số sai trong Modbus không báo lỗi, nó chỉ âm thầm sai. Vì vậy Point Map hỏng
phải bị chặn ngay lúc khởi động, kèm tên thiết bị và điểm để sửa.

Môi trường:
  - Point Map ghi địa chỉ THẬT của site (host, port trên từng thiết bị).
  - env "site": dùng nguyên địa chỉ thật — chỉ khi cố ý kết nối thiết bị thật.
  - env khác (mặc định "lab"): đọc environments/<env>.yml cạnh Point Map, ánh xạ từng địa chỉ
    thật "host:port" sang địa chỉ khác (simulator). Mỗi địa chỉ thật phải có đúng một dòng.
  - môi trường cũng có thể truyền sẵn dạng dict (env_cfg), ví dụ dựng từ simulator đang chạy;
    mục `unreachable` {địa chỉ thật: lý do} bỏ thiết bị máy này không tới được, lý do ở cfg["unreachable"].

Kiểm tra:
  - thiết bị có host, port (1-65535), device_id (số nguyên); timeout nếu có thì > 0
  - thiết bị trùng host:port = cùng sau một gateway: device_id không trùng, trong 1-247, cùng timeout
  - thiết bị riêng một địa chỉ: device_id trong 0-255
  - Modbus RTU (transport: rtu): serial { port, baudrate, parity, stop_bits }, device_id 1-247;
    thiết bị cùng cổng serial = cùng bus RS-485: cùng thông số serial và timeout, device_id không trùng
  - byte_order thuộc ABCD, CDAB, BADC, DCBA
  - điểm có đủ name, table, address, type; table là holding hoặc input
  - type hợp lệ (theo codec)
  - hai điểm cùng thiết bị, cùng bảng không đè ô nhớ của nhau (kiểu 32 bit chiếm 2 ô)
  - điểm writable có allowed, hoặc có đủ min và max với min <= max
  - điểm có khóa unit (chuỗi rỗng được phép cho đại lượng không đơn vị)
  - thiết bị và điểm có label { vi, ja } không rỗng; cảnh báo trỏ tới điểm có thật, message { vi, ja }
  - protocol: modbus (mặc định) | snmp | bacnet. SNMP: snmp { version 1|2c, community }, điểm có oid (không trùng)
    và type integer|gauge32|counter32, chỉ đọc; mỗi thiết bị SNMP/BACnet một địa chỉ riêng
  - BACnet: device_instance không trùng; điểm có object "loại,số" không trùng; chỉ *-value/*-output ghi được,
    và phải có priority 1-16; cần bacnet.client (địa chỉ của edge trên mạng BACnet)
"""
import re, sys
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
BAUDRATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)
PARITIES = ("N", "E", "O")
SERIAL_SHARED = ("baudrate", "parity", "stop_bits", "bytesize")   # thiết bị chung bus RS-485 phải giống nhau
PROTOCOLS = ("modbus", "snmp", "bacnet")
SNMP_TYPES = ("integer", "gauge32", "counter32")
SNMP_VERSIONS = ("1", "2c")
OID = re.compile(r"^\d+(\.\d+)+$")
BACNET_TYPES = ("analog-input", "analog-output", "analog-value", "binary-input", "binary-output", "binary-value")
BACNET_WRITABLE = ("analog-output", "analog-value", "binary-output", "binary-value")   # đối tượng commandable
BACNET_MAX_INSTANCE = 4194302
LANGS = ("vi", "ja")                               # ngôn ngữ hiển thị bắt buộc cho label và message


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


def is_rtu(d: dict) -> bool:
    """Thiết bị Modbus RTU trên bus RS-485 (cổng serial) thay vì Modbus TCP."""
    return d.get("transport") == "rtu"


SOCKET = "socket://"                                   # cổng serial dạng URL của pyserial: bus nối qua TCP


def serial_over_tcp(cfg: dict, mapping: dict) -> list[str]:
    """Bus RS-485 nối qua bộ chuyển serial ↔ Ethernet (RTU over TCP): {cổng serial thật: "host:port"}.

    Thiết bị trên bus đó mở cổng "socket://host:port" (pyserial mở được như cổng serial; khung vẫn là RTU có CRC);
    simulator nghe ở host:port, Telegraf đọc bằng transmission_mode RTUoverTCP. Bus không có trong mapping giữ nguyên.
    """
    errors, used = [], set()
    for src, dst in mapping.items():
        if _parse_address(dst) is None:
            errors.append(f"bus {src} -> {dst!r} không đúng dạng host:port")
    for d in cfg.get("devices", []):
        if not is_rtu(d):
            continue
        src = d.get("site_address", f"rtu:{d['serial']['port']}").removeprefix("rtu:")
        if src in mapping and _parse_address(mapping[src]):
            used.add(src)
            d["site_address"] = f"rtu:{src}"
            d["serial"] = dict(d["serial"], port=f"{SOCKET}{mapping[src]}")
    errors += [f"bus {src}: không có thiết bị RTU nào dùng cổng này trong Point Map"
               for src in mapping if src not in used and _parse_address(mapping[src])]
    return errors


# ---------- đọc và áp môi trường ----------
def _apply_serial(cfg: dict, env: str, mapping: dict) -> list[str]:
    """Ánh xạ cổng serial thật (ví dụ /dev/ttyUSB0) sang cổng của môi trường (ví dụ cổng ảo của simulator)."""
    errors, targets, used = [], {}, set()
    for src, dst in mapping.items():
        if dst in targets:
            errors.append(f"môi trường {env}: {targets[dst]} và {src} cùng trỏ tới cổng {dst}")
        targets[dst] = src
    for d in cfg.get("devices", []):
        if not is_rtu(d) or not isinstance(d.get("serial"), dict) or "port" not in d["serial"]:
            continue
        src = d["serial"]["port"]
        if src not in mapping:
            errors.append(f"môi trường {env}: chưa có cổng serial cho {src} (thiết bị {d.get('name', '?')})")
            continue
        used.add(src)
        d["site_address"] = f"rtu:{src}"
        d["serial"] = dict(d["serial"], port=str(mapping[src]))
    errors += [f"môi trường {env}: cổng {src} không thuộc thiết bị nào trong Point Map" for src in mapping if src not in used]
    return errors


def _site_key(d: dict) -> str:
    """Địa chỉ thật của thiết bị trong Point Map, cùng dạng khóa của môi trường: host:port hoặc rtu:<cổng>."""
    if is_rtu(d) and isinstance(d.get("serial"), dict):
        return f"rtu:{d['serial'].get('port')}"
    return f"{d.get('host')}:{d.get('port')}"


def _drop_unreachable(cfg: dict, unreachable: dict) -> None:
    """Bỏ thiết bị môi trường báo máy này không tới được (kèm cảnh báo của nó); lý do ghi vào cfg["unreachable"]."""
    keep, dropped = [], {}
    for d in cfg.get("devices", []):
        if _site_key(d) in unreachable:
            dropped[d.get("name", "?")] = unreachable[_site_key(d)]
        else:
            keep.append(d)
    cfg["devices"] = keep
    cfg["alerts"] = [a for a in cfg.get("alerts", []) if str(a.get("point", "")).split(".")[0] not in dropped]
    cfg["unreachable"] = dropped


def _apply_environment(cfg: dict, env: str, env_cfg: dict) -> list[str]:
    _drop_unreachable(cfg, env_cfg.get("unreachable") or {})
    mapping = env_cfg.get("addresses") or {}
    errors, targets = _apply_serial(cfg, env, env_cfg.get("serial") or {}), {}
    for src, dst in mapping.items():
        if _parse_address(dst) is None:
            errors.append(f"môi trường {env}: {src} -> {dst!r} không đúng dạng host:port")
        elif dst in targets:
            errors.append(f"môi trường {env}: {targets[dst]} và {src} cùng trỏ tới {dst}")
        else:
            targets[dst] = src
    used = set()
    for d in cfg.get("devices", []):
        if is_rtu(d):
            continue
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


def read(path: str = DEFAULT_PATH, env: str = DEFAULT_ENV, env_cfg: dict | None = None) -> dict:
    """Đọc Point Map và áp môi trường, chưa kiểm tra nội dung. Lỗi môi trường -> PointMapError.

    env_cfg: môi trường cho sẵn (cùng dạng environments/<env>.yml, thêm mục unreachable), ví dụ dựng từ
    simulator đang chạy (simctl.SimControl.environment); None = đọc file environments/<env>.yml.
    """
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if env != SITE_ENV:
        if env_cfg is None:
            env_file = Path(path).parent / "environments" / f"{env}.yml"
            if not env_file.exists():
                raise PointMapError([f"không có file môi trường '{env}' ({env_file}); "
                                     f"dùng --env {SITE_ENV} để kết nối địa chỉ thật"])
            env_cfg = yaml.safe_load(env_file.read_text(encoding="utf-8")) or {}
        errors = _apply_environment(cfg, env, env_cfg)
        if errors:
            raise PointMapError(errors)
        client = env_cfg.get("bacnet_client")
        if client:
            cfg["bacnet"] = dict(cfg.get("bacnet") or {}, client=client)
    for d in cfg.get("devices", []):                   # client BACnet dùng khi đọc/ghi thiết bị này
        if d.get("protocol") == "bacnet":
            d["bacnet_client"] = (cfg.get("bacnet") or {}).get("client")
    cfg["env"] = env
    return cfg


def load(path: str = DEFAULT_PATH, env: str = DEFAULT_ENV, env_cfg: dict | None = None) -> dict:
    """Đọc, áp môi trường và kiểm tra; có lỗi thì PointMapError với mọi lỗi."""
    cfg = read(path, env, env_cfg)
    errors = validate(cfg)
    if errors:
        raise PointMapError(errors)
    return cfg


def load_or_exit(path: str = DEFAULT_PATH, env: str = DEFAULT_ENV, env_cfg: dict | None = None) -> dict:
    """Gọi khi khởi động chương trình: Point Map hỏng thì in mọi lỗi rồi dừng."""
    try:
        return load(path, env, env_cfg)
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


def _check_bilingual(owner: str, field: str, value) -> list[str]:
    """label / message phải là { vi: "...", ja: "..." } với chữ không rỗng."""
    if not isinstance(value, dict):
        return [f"{owner}: thiếu {field} song ngữ (dạng {field}: {{ vi: \"...\", ja: \"...\" }})"]
    missing = [lang for lang in LANGS if not isinstance(value.get(lang), str) or not value[lang].strip()]
    return [f"{owner}: {field} thiếu bản {', '.join(missing)}"] if missing else []


def _check_serial(d: dict) -> list[str]:
    dev, s = d.get("name", "?"), d.get("serial")
    if not isinstance(s, dict) or not isinstance(s.get("port"), str) or not s["port"]:
        return [f"{dev}: thiết bị RTU cần serial: {{ port, baudrate, parity, stop_bits }}"]
    errors = []
    if s.get("baudrate") not in BAUDRATES:
        errors.append(f"{dev}: serial.baudrate {s.get('baudrate')!r} không hợp lệ (chỉ nhận {', '.join(map(str, BAUDRATES))})")
    if s.get("parity", "N") not in PARITIES:
        errors.append(f"{dev}: serial.parity {s.get('parity')!r} không hợp lệ (N, E hoặc O)")
    if s.get("stop_bits", 1) not in (1, 2):
        errors.append(f"{dev}: serial.stop_bits {s.get('stop_bits')!r} không hợp lệ (1 hoặc 2)")
    if s.get("bytesize", 8) not in (7, 8):
        errors.append(f"{dev}: serial.bytesize {s.get('bytesize')!r} không hợp lệ (7 hoặc 8)")
    return errors


def _check_connection(d: dict) -> list[str]:
    dev = d.get("name", "?")
    if d.get("transport", "tcp") not in ("tcp", "rtu"):
        return [f"{dev}: transport {d['transport']!r} không hợp lệ (tcp hoặc rtu)"]
    if is_rtu(d):
        errors = _check_serial(d)
        if "device_id" not in d:
            errors.append(f"{dev}: thiếu trường kết nối device_id")
        elif not (_is_int(d["device_id"]) and 1 <= d["device_id"] <= 247):
            errors.append(f"{dev}: device_id {d['device_id']!r} không hợp lệ trên bus RS-485 (địa chỉ RTU chỉ 1-247)")
        if "timeout" in d and not (isinstance(d["timeout"], (int, float)) and not isinstance(d["timeout"], bool)
                                   and d["timeout"] > 0):
            errors.append(f"{dev}: timeout {d['timeout']!r} không hợp lệ (số giây > 0)")
        return errors
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


def _check_shared_bus(devices: list[dict]) -> list[str]:
    """Thiết bị cùng cổng serial nằm trên cùng một bus RS-485: cùng thông số, device_id không trùng."""
    buses: dict[str, list[dict]] = {}
    for d in devices:
        if is_rtu(d) and not _check_serial(d) and "device_id" in d:
            buses.setdefault(d["serial"]["port"], []).append(d)
    errors = []
    for group in buses.values():
        bus = group[0].get("site_address") or f"rtu:{group[0]['serial']['port']}"
        owner: dict = {}
        for d in group:
            if d["device_id"] in owner:
                errors.append(f"trùng device_id {d['device_id']} trên bus {bus}: {owner[d['device_id']]} và {d['name']}")
            owner.setdefault(d["device_id"], d["name"])
        first = group[0]
        for d in group[1:]:
            for k in SERIAL_SHARED:
                if d["serial"].get(k) != first["serial"].get(k):
                    errors.append(f"{d['name']}: serial.{k} = {d['serial'].get(k)} khác {first['name']} "
                                  f"({first['serial'].get(k)}) trên cùng bus {bus}")
            if d.get("timeout") != first.get("timeout"):
                errors.append(f"{d['name']}: timeout khác {first['name']} trên cùng bus {bus}")
    return errors


def _check_shared_addresses(devices: list[dict]) -> list[str]:
    """Thiết bị trùng host:port nằm sau cùng một gateway."""
    groups: dict[tuple, list[dict]] = {}
    for d in devices:
        if not is_rtu(d) and all(f in d for f in CONNECTION):
            groups.setdefault((d["host"], d["port"]), []).append(d)
    errors = _check_shared_bus(devices)
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


def protocol(d: dict) -> str:
    return d.get("protocol", "modbus")


def _check_point_common(key: str, p: dict) -> list[str]:
    errors = _check_bilingual(key, "label", p.get("label"))
    if "unit" not in p:
        errors.append(f"{key}: thiếu unit (dùng unit: \"\" nếu không có đơn vị)")
    return errors


def _check_modbus_points(dev: str, d: dict) -> list[str]:
    errors: list[str] = []
    if d.get("byte_order") not in BYTE_ORDERS:
        errors.append(f"{dev}: byte_order {d.get('byte_order')!r} không hợp lệ (chỉ nhận {', '.join(BYTE_ORDERS)})")
    used: dict[str, list[tuple[int, int, str]]] = {t: [] for t in TABLES}   # bảng -> (ô đầu, số ô, tên)
    for p in d.get("points", []):
        key = f"{dev}.{p.get('name', '?')}"
        missing = [f for f in REQUIRED if f not in p]
        if missing:
            errors.append(f"{key}: thiếu trường bắt buộc {', '.join(missing)}")
        errors += _check_point_common(key, p)
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
    return errors


def _check_ip(dev: str, d: dict) -> list[str]:
    """host, port, timeout của thiết bị SNMP / BACnet (không có device_id kiểu Modbus)."""
    errors = []
    if not isinstance(d.get("host"), str) or not d["host"]:
        errors.append(f"{dev}: host {d.get('host')!r} không hợp lệ")
    if not (_is_int(d.get("port")) and 1 <= d["port"] <= 65535):
        errors.append(f"{dev}: port {d.get('port')!r} không hợp lệ (số nguyên 1-65535)")
    if "timeout" in d and not (isinstance(d["timeout"], (int, float)) and not isinstance(d["timeout"], bool)
                               and d["timeout"] > 0):
        errors.append(f"{dev}: timeout {d['timeout']!r} không hợp lệ (số giây > 0)")
    return errors


def _check_snmp(dev: str, d: dict) -> list[str]:
    errors = _check_ip(dev, d)
    s = d.get("snmp")
    if not isinstance(s, dict):
        errors.append(f"{dev}: thiết bị SNMP cần snmp: {{ version, community }}")
    else:
        if str(s.get("version")) not in SNMP_VERSIONS:
            errors.append(f"{dev}: snmp.version {s.get('version')!r} chưa hỗ trợ (chỉ {', '.join(SNMP_VERSIONS)})")
        if not isinstance(s.get("community"), str) or not s["community"]:
            errors.append(f"{dev}: snmp.community phải là chuỗi khác rỗng")
    seen: dict[str, str] = {}
    for p in d.get("points", []):
        key = f"{dev}.{p.get('name', '?')}"
        errors += _check_point_common(key, p)
        oid = str(p.get("oid", ""))
        if not OID.match(oid):
            errors.append(f"{key}: oid {p.get('oid')!r} không hợp lệ (dạng số chấm, ví dụ 1.3.6.1.2.1.33.1.2.4.0)")
        elif oid in seen:
            errors.append(f"{key}: trùng oid {oid} với {seen[oid]}")
        else:
            seen[oid] = key
        if p.get("type") not in SNMP_TYPES:
            errors.append(f"{key}: type {p.get('type')!r} không hợp lệ cho SNMP (chỉ nhận {', '.join(SNMP_TYPES)})")
        if p.get("writable"):
            errors.append(f"{key}: điểm SNMP chỉ đọc — bỏ writable (lệnh điều khiển đi qua Modbus/BACnet)")
    return errors


def _check_unique_ip(devices: list[dict]) -> list[str]:
    """Thiết bị SNMP / BACnet mỗi cái một địa chỉ riêng (không có kiểu nhiều thiết bị sau gateway)."""
    seen: dict[tuple, str] = {}
    errors = []
    for d in devices:
        if protocol(d) == "modbus" or "host" not in d or "port" not in d:
            continue
        k = (protocol(d), d["host"], d["port"])
        if k in seen:
            errors.append(f"{d['name']}: trùng địa chỉ {_addr(d)} với {seen[k]}")
        seen.setdefault(k, d["name"])
    return errors


def validate(cfg: dict) -> list[str]:
    """Trả về danh sách lỗi; rỗng nghĩa là Point Map hợp lệ."""
    errors: list[str] = []
    if "modbus" in cfg:
        errors.append("khóa modbus: đã bỏ — khai báo host, port, device_id trên từng thiết bị")
    devices = cfg.get("devices", [])
    for d in devices:
        dev = d.get("name", "?")
        errors += _check_bilingual(dev, "label", d.get("label"))
        proto = protocol(d)
        if proto not in PROTOCOLS:
            errors.append(f"{dev}: protocol {proto!r} không hợp lệ (chỉ nhận {', '.join(PROTOCOLS)})")
        elif proto == "snmp":
            errors += _check_snmp(dev, d)
        elif proto == "bacnet":
            errors += _check_bacnet(dev, d)
        else:
            errors += _check_connection(d)
            errors += _check_modbus_points(dev, d)
    errors += _check_shared_addresses([d for d in devices if protocol(d) == "modbus"])
    errors += _check_unique_ip(devices)
    errors += _check_bacnet_site(cfg)
    keys = {f"{d.get('name')}.{p.get('name')}" for d in devices for p in d.get("points", [])}
    for a in cfg.get("alerts", []):
        point = a.get("point", "?")
        if point not in keys:
            errors.append(f"cảnh báo trỏ tới điểm {point} không có trong Point Map")
        errors += _check_bilingual(f"cảnh báo {point}", "message", a.get("message"))
    return errors


def bacnet_object(text) -> tuple[str, int] | None:
    """ "analog-input,1" -> ("analog-input", 1); sai dạng -> None."""
    kind, sep, inst = str(text).partition(",")
    if not sep or kind.strip() not in BACNET_TYPES or not inst.strip().isdigit():
        return None
    n = int(inst)
    return (kind.strip(), n) if 0 <= n <= BACNET_MAX_INSTANCE else None


def _check_bacnet(dev: str, d: dict) -> list[str]:
    errors = _check_ip(dev, d)
    inst = d.get("device_instance")
    if not (_is_int(inst) and 0 <= inst <= BACNET_MAX_INSTANCE):
        errors.append(f"{dev}: device_instance {inst!r} không hợp lệ (số nguyên 0-{BACNET_MAX_INSTANCE})")
    seen: dict[tuple, str] = {}
    for p in d.get("points", []):
        key = f"{dev}.{p.get('name', '?')}"
        errors += _check_point_common(key, p)
        obj = bacnet_object(p.get("object"))
        if obj is None:
            errors.append(f"{key}: object {p.get('object')!r} không hợp lệ (dạng loại,số; loại: {', '.join(BACNET_TYPES)})")
            continue
        if obj in seen:
            errors.append(f"{key}: trùng object {obj[0]},{obj[1]} với {seen[obj]}")
        seen.setdefault(obj, key)
        if not p.get("writable"):
            continue
        if obj[0] not in BACNET_WRITABLE:
            errors.append(f"{key}: {obj[0]} không ghi được (chỉ {', '.join(BACNET_WRITABLE)}) — bỏ writable")
            continue
        errors += _check_writable(key, p)
        if not (_is_int(p.get("priority")) and 1 <= p["priority"] <= 16):
            errors.append(f"{key}: điểm BACnet ghi được cần priority 1-16 (thường 8); lệnh ghi luôn kèm mức ưu tiên")
        if obj[0].startswith("binary") and "allowed" in p and not set(p["allowed"]) <= {0, 1}:
            errors.append(f"{key}: điểm binary chỉ nhận allowed trong [0, 1]")
    return errors


def _check_bacnet_site(cfg: dict) -> list[str]:
    """Có thiết bị BACnet thì phải khai báo địa chỉ của edge trên mạng BACnet; device_instance không trùng."""
    devices = [d for d in cfg.get("devices", []) if protocol(d) == "bacnet"]
    if not devices:
        return []
    errors = []
    client = (cfg.get("bacnet") or {}).get("client")
    if not isinstance(client, str) or ":" not in client:
        errors.append("có thiết bị BACnet: khai báo bacnet: { client: \"IP/mặt nạ:cổng\" } — địa chỉ của edge "
                      "trên mạng BACnet (khác cổng thiết bị nếu cùng máy)")
    seen: dict = {}
    for d in devices:
        inst = d.get("device_instance")
        if inst in seen:
            errors.append(f"trùng device_instance {inst}: {seen[inst]} và {d['name']}")
        seen.setdefault(inst, d["name"])
    return errors


# ---------- mô tả để hiển thị (simulator, collector dùng chung) ----------
def point_ref(d: dict, p: dict) -> str:
    """Chỗ của điểm trong thiết bị, để hiển thị: "HR 4 · int16", "OID 1.3.6...", "analog-value,2"."""
    proto = d.get("protocol", "modbus")
    if proto == "snmp":
        return f"OID {p['oid']}"
    if proto == "bacnet":
        return p["object"]
    return f"{'HR' if p['table'] == 'holding' else 'IR'} {p['address']} · {p['type']}"


def device_meta(d: dict) -> dict:
    """Thông tin kết nối để trang web hiện: giao thức và tham số riêng của nó."""
    proto = d.get("protocol", "modbus")
    if proto == "snmp":
        return {"protocol": "snmp", "version": str(d["snmp"]["version"])}
    if proto == "bacnet":
        return {"protocol": "bacnet", "instance": d.get("device_instance")}
    return {"protocol": "modbus", "id": d["device_id"], "order": d["byte_order"]}
