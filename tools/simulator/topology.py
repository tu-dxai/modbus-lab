"""MÔ HÌNH SƠ ĐỒ DC — dữ liệu cho hai tab "Sơ đồ kiến trúc" và "Sơ đồ đơn tuyến" trên trang simulator.

Thiết bị, hệ thống (EPMS / BMS), kết nối và sơ đồ đơn tuyến lấy từ Point Map (nguồn duy nhất).
Phần mềm (Edge Site Stack, MQTT, DCIM, ITSM) không phải thông tin thiết bị nên mô tả ở đây, kèm trạng thái
trong repo này:
  ready    đã có, chạy được với simulator
  partial  có một phần (ví dụ: cấu hình Telegraf sinh từ Point Map nhưng chưa chạy Telegraf thật)
  planned  chưa có — vẽ mờ trên sơ đồ, sẽ phát triển
Thêm một phần mềm mới = thêm một dòng vào EDGE / CENTER (và nhãn topo.part.<id>, topo.note.<id> trong
i18n/messages.yml); đổi trạng thái khi phần đó được làm.
"""
from point_map import is_rtu, protocol
from sim_state import endpoint

STATUSES = ("ready", "partial", "planned")

# Edge Site Stack: chạy tại container, vẫn chạy khi mất WAN. path: nơi tìm code trong repo.
EDGE = [
    {"id": "point-map", "status": "ready", "path": "edge/point-map/"},
    {"id": "telegraf", "status": "partial", "path": "edge/collectors/telegraf/"},
    {"id": "bacnet-collector", "status": "ready", "path": "edge/collectors/bacnet/"},
    {"id": "write-service", "status": "ready", "path": "edge/write-service/"},
    {"id": "alerts", "status": "partial", "path": "tools/dashboard/collector.py"},
    {"id": "collector", "status": "ready", "path": "tools/dashboard/"},
]
# Đường lên trung tâm và trung tâm (AWS Tokyo).
CENTER = [
    {"id": "mqtt", "status": "planned", "path": None},
    {"id": "dcim", "status": "planned", "path": None},
    {"id": "itsm", "status": "planned", "path": None},
]
# Dòng dữ liệu giữa các phần mềm (thiết bị -> edge đi theo links).
FLOWS = [
    {"from": "telegraf", "to": "mqtt"},
    {"from": "bacnet-collector", "to": "mqtt"},
    {"from": "mqtt", "to": "dcim"},
    {"from": "dcim", "to": "itsm"},
]
# Phần mềm edge đọc từng kiểu kết nối: Telegraf đọc Modbus và SNMP, collector Python đọc BACnet.
READER = {"gateway": "telegraf", "rtu": "telegraf", "direct": "telegraf", "snmp": "telegraf",
          "bacnet": "bacnet-collector"}
SHOW_DEFAULT = 2                                       # số điểm hiện trên nút đơn tuyến khi không khai show


def _link_kind(devs: list[dict]) -> str:
    d = devs[0]
    if protocol(d) in ("snmp", "bacnet"):
        return protocol(d)
    if is_rtu(d):
        return "rtu"
    return "gateway" if len(devs) > 1 else "direct"


def _links(cfg: dict) -> list[dict]:
    """Thiết bị nhóm theo đường kết nối: gateway, bus RS-485, IP riêng, SNMP, BACnet."""
    groups: dict[str, list[dict]] = {}
    for d in cfg["devices"]:
        groups.setdefault(endpoint(d), []).append(d)
    out = []
    for ep, devs in groups.items():
        kind = _link_kind(devs)
        out.append({"id": f"link:{ep}", "kind": kind, "endpoint": ep,
                    "site_endpoint": devs[0].get("site_address", ep), "devices": [d["name"] for d in devs],
                    "to": READER[kind]})
    return out


def _systems(cfg: dict) -> list[dict]:
    order = ["EPMS", "BMS", "other"]
    groups: dict[str, list[str]] = {}
    for d in cfg["devices"]:
        groups.setdefault(d.get("system", "other"), []).append(d["name"])
    return [{"id": s, "devices": groups[s]} for s in order if s in groups]


def _power(cfg: dict) -> list[dict]:
    """Nút đơn tuyến: thêm parent, depth, nhãn theo thiết bị, và danh sách điểm (khóa đầy đủ) để hiện."""
    devices = {d["name"]: d for d in cfg["devices"]}
    nodes = cfg.get("topology", {}).get("power", [])
    parent = {n["id"]: n.get("from") for n in nodes}

    def depth(nid: str) -> int:
        n = 0
        while parent.get(nid) is not None:
            nid, n = parent[nid], n + 1
        return n

    out = []
    for n in nodes:
        attached = ([n["device"]] if "device" in n else []) + list(n.get("meters", []))
        label = n.get("label") or devices[n["device"]]["label"]
        if "show" in n:
            show = [f"{next(a for a in attached if any(p['name'] == s for p in devices[a]['points']))}.{s}"
                    for s in n["show"]]
        else:
            show = [f"{a}.{p['name']}" for a in attached[:1] for p in devices[a]["points"][:SHOW_DEFAULT]]
        out.append({"id": n["id"], "kind": n["kind"], "label": label, "parent": n.get("from"),
                    "depth": depth(n["id"]), "device": n.get("device"), "meters": list(n.get("meters", [])),
                    "show": show})
    return out


def build(cfg: dict) -> dict:
    """Toàn bộ dữ liệu cho hai tab sơ đồ. cfg đã qua kiểm tra Point Map."""
    topo = cfg.get("topology", {})
    return {
        "site": cfg.get("site"),
        "assumed": bool(topo.get("assumed", False)),
        "systems": _systems(cfg),
        "links": _links(cfg),
        "edge": [dict(p) for p in EDGE],
        "center": [dict(p) for p in CENTER],
        "flows": [dict(f) for f in FLOWS],
        "power": _power(cfg),
        "cooling": [{"device": c["device"], "serves": c["serves"]} for c in topo.get("cooling", [])],
    }
