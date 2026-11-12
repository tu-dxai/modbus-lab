"""Kiểm thử bộ kiểm tra Point Map và cơ chế môi trường (edge/point-map/point_map.py).

Mỗi bài lấy devices.yml thật, cố ý làm hỏng một chỗ, rồi xem lỗi có nêu đúng thiết bị và điểm không.
"""
import copy, os, subprocess, sys
import pytest
import yaml
from point_map import PointMapError, load, read, validate

PATH = "edge/point-map/devices.yml"
GOOD = load(PATH)                                  # môi trường lab (mặc định)
SITE = read(PATH, env="site")                      # địa chỉ thật, không ánh xạ


def broken(base=GOOD):
    return copy.deepcopy(base)


def device(cfg, name):
    return next(d for d in cfg["devices"] if d["name"] == name)


def point(cfg, dev, name):
    return next(p for p in device(cfg, dev)["points"] if p["name"] == name)


def one_error(cfg):
    errors = validate(cfg)
    assert len(errors) == 1, errors
    return errors[0]


def test_real_point_map_is_valid():
    assert validate(GOOD) == []
    assert validate(SITE) == []


# ---------- ô nhớ đè nhau ----------
def test_overlap_same_address():
    cfg = broken()
    point(cfg, "dong-ho-dien-01", "dong_dien")["address"] = 0          # trùng ô của dien_ap
    e = one_error(cfg)
    assert "dong-ho-dien-01.dien_ap" in e and "dong-ho-dien-01.dong_dien" in e


def test_overlap_second_register_of_32bit():
    cfg = broken()
    point(cfg, "dong-ho-dien-01", "nhiet_do_tu")["address"] = 3        # cong_suat float32 chiếm ô 2-3
    e = one_error(cfg)
    assert "dong-ho-dien-01.cong_suat" in e and "dong-ho-dien-01.nhiet_do_tu" in e and "2-3" in e


def test_same_address_in_different_tables_is_not_overlap():
    cfg = broken()
    point(cfg, "bess-01", "che_do")["address"] = 100                   # holding 100, muc_pin là input 100
    assert validate(cfg) == []


def test_same_register_on_different_devices_is_not_overlap():
    cfg = broken()
    point(cfg, "bess-01", "che_do")["address"] = 0                     # dien_ap holding 0 nhưng ở thiết bị khác
    assert validate(cfg) == []


# ---------- byte order ----------
def test_invalid_byte_order():
    cfg = broken()
    device(cfg, "bess-01")["byte_order"] = "ABDC"
    e = one_error(cfg)
    assert "bess-01" in e and "ABDC" in e


# ---------- kiểu dữ liệu ----------
def test_invalid_type():
    cfg = broken()
    point(cfg, "bess-01", "muc_pin")["type"] = "float64"
    e = one_error(cfg)
    assert "bess-01.muc_pin" in e and "float64" in e


# ---------- điểm ghi được ----------
def test_writable_without_allowed_or_range():
    cfg = broken()
    del point(cfg, "bess-01", "che_do")["allowed"]
    e = one_error(cfg)
    assert "bess-01.che_do" in e and "allowed" in e


def test_writable_with_range_is_valid():
    cfg = broken()
    p = point(cfg, "bess-01", "che_do")
    del p["allowed"]
    p.update(min=0, max=1)
    assert validate(cfg) == []


@pytest.mark.parametrize("bounds", [{"min": 0}, {"max": 1}, {"min": 5, "max": 1}])
def test_writable_with_incomplete_or_inverted_range(bounds):
    cfg = broken()
    p = point(cfg, "bess-01", "che_do")
    del p["allowed"]
    p.update(bounds)
    e = one_error(cfg)
    assert "bess-01.che_do" in e


# ---------- đơn vị ----------
def test_missing_unit():
    cfg = broken()
    del point(cfg, "dong-ho-dien-01", "dien_ap")["unit"]
    e = one_error(cfg)
    assert "dong-ho-dien-01.dien_ap" in e and "unit" in e


def test_empty_unit_is_allowed():
    assert point(GOOD, "bess-01", "che_do")["unit"] == ""             # chế độ: không có đơn vị
    assert validate(GOOD) == []


# ---------- nhãn hiển thị song ngữ ----------
@pytest.mark.parametrize("target", ["device", "point"])
def test_missing_label(target):
    cfg = broken()
    obj = device(cfg, "bess-01") if target == "device" else point(cfg, "bess-01", "muc_pin")
    del obj["label"]
    e = one_error(cfg)
    assert ("bess-01.muc_pin" if target == "point" else "bess-01") in e and "label" in e


@pytest.mark.parametrize("lang", ["vi", "ja"])
def test_label_missing_one_language(lang):
    cfg = broken()
    del point(cfg, "bess-01", "che_do")["label"][lang]
    e = one_error(cfg)
    assert "bess-01.che_do" in e and lang in e


def test_label_must_not_be_empty():
    cfg = broken()
    point(cfg, "bess-01", "che_do")["label"]["ja"] = "  "
    e = one_error(cfg)
    assert "bess-01.che_do" in e and "ja" in e


def test_alert_message_needs_both_languages():
    cfg = broken()
    cfg["alerts"][0]["message"] = "Tủ điện quá nóng"               # chỉ một chuỗi tiếng Việt
    e = one_error(cfg)
    assert "dong-ho-dien-01.nhiet_do_tu" in e and "message" in e


def test_alert_on_unknown_point():
    cfg = broken()
    cfg["alerts"][0]["point"] = "khong-co.diem_nao"
    e = one_error(cfg)
    assert "khong-co.diem_nao" in e


# ---------- device_id và địa chỉ ----------
def test_duplicate_device_id_on_same_address():
    cfg = broken(SITE)
    device(cfg, "dong-ho-dien-02")["device_id"] = 1                    # cùng gateway 10.20.0.21:502
    e = one_error(cfg)
    assert "dong-ho-dien-01" in e and "dong-ho-dien-02" in e and "10.20.0.21:502" in e


def test_same_device_id_on_different_addresses_is_allowed():
    assert device(GOOD, "dong-ho-dien-01")["device_id"] == device(GOOD, "bess-01")["device_id"] == 1
    assert validate(GOOD) == []


def test_gateway_device_id_must_be_rtu_address():
    cfg = broken(SITE)
    device(cfg, "dong-ho-dien-02")["device_id"] = 250                  # sau gateway: chỉ 1-247
    e = one_error(cfg)
    assert "dong-ho-dien-02" in e and "250" in e and "1-247" in e


def test_direct_device_may_use_255():
    cfg = broken(SITE)
    device(cfg, "bess-01")["device_id"] = 255                          # một mình một địa chỉ
    assert validate(cfg) == []


@pytest.mark.parametrize("field,value", [("device_id", 256), ("device_id", -1), ("device_id", "1"),
                                         ("port", 0), ("port", 70000), ("port", "502"),
                                         ("host", ""), ("timeout", 0), ("timeout", "3")])
def test_invalid_connection_field(field, value):
    cfg = broken(SITE)
    device(cfg, "bess-01")[field] = value
    e = one_error(cfg)
    assert "bess-01" in e and field in e


@pytest.mark.parametrize("field", ["host", "port", "device_id"])
def test_missing_connection_field(field):
    cfg = broken(SITE)
    del device(cfg, "bess-01")[field]
    e = one_error(cfg)
    assert "bess-01" in e and field in e


def test_timeout_is_optional():
    cfg = broken(SITE)
    del device(cfg, "bess-01")["timeout"]
    assert validate(cfg) == []


def test_different_timeout_behind_same_gateway():
    cfg = broken(SITE)
    device(cfg, "dong-ho-dien-02")["timeout"] = 5
    e = one_error(cfg)
    assert "dong-ho-dien-01" in e and "dong-ho-dien-02" in e and "timeout" in e


def test_legacy_modbus_key_is_rejected():
    cfg = broken(SITE)
    cfg["modbus"] = {"host": "127.0.0.1", "port": 5020}
    e = one_error(cfg)
    assert "modbus" in e and "host" in e


# ---------- thiếu trường bắt buộc: báo lỗi thay vì sập ----------
def test_missing_required_field():
    cfg = broken()
    del point(cfg, "bess-01", "muc_pin")["address"]
    e = one_error(cfg)
    assert "bess-01.muc_pin" in e and "address" in e


def test_reports_all_errors_at_once():
    cfg = broken(SITE)
    device(cfg, "dong-ho-dien-02")["device_id"] = 1
    point(cfg, "bess-01", "muc_pin")["type"] = "float64"
    del point(cfg, "dong-ho-dien-01", "dien_ap")["unit"]
    assert len(validate(cfg)) == 3


# ---------- môi trường ----------
def test_site_keeps_real_addresses():
    d = device(SITE, "bess-01")
    assert (d["host"], d["port"]) == ("10.20.0.30", 502)


def test_lab_maps_every_device_to_simulator():
    d1, d2, b = (device(GOOD, n) for n in ("dong-ho-dien-01", "dong-ho-dien-02", "bess-01"))
    assert (d1["host"], d1["port"]) == (d2["host"], d2["port"]) == ("127.0.1.21", 5020)   # cùng gateway
    assert (b["host"], b["port"]) == ("127.0.1.30", 5020)
    assert b["site_address"] == "10.20.0.30:502"


def test_default_environment_is_lab():
    assert GOOD["env"] == "lab" and read(PATH)["env"] == "lab"


# Ánh xạ thật của môi trường lab: thêm thiết bị vào Point Map không làm vỡ các bài dưới đây.
_LAB_ENV = yaml.safe_load(open("edge/point-map/environments/lab.yml", encoding="utf-8"))
LAB_SERIAL = dict(_LAB_ENV["serial"])


def write_site(tmp_path, cfg, addresses, serial=LAB_SERIAL):
    (tmp_path / "devices.yml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "lab.yml").write_text(
        yaml.safe_dump({"addresses": addresses, "serial": serial}), encoding="utf-8")
    return str(tmp_path / "devices.yml")


LAB = dict(_LAB_ENV["addresses"])


def env_errors(tmp_path, addresses):
    with pytest.raises(PointMapError) as e:
        read(write_site(tmp_path, SITE, addresses))
    return e.value.errors


def test_environment_missing_an_address(tmp_path):
    (e,) = env_errors(tmp_path, {k: v for k, v in LAB.items() if k != "10.20.0.30:502"})
    assert "10.20.0.30:502" in e and "bess-01" in e


def test_environment_with_unused_address(tmp_path):
    (e,) = env_errors(tmp_path, {**LAB, "10.20.0.99:502": "127.0.1.99:5020"})
    assert "10.20.0.99:502" in e


def test_environment_maps_two_addresses_to_one(tmp_path):
    (e,) = env_errors(tmp_path, {**LAB, "10.20.0.30:502": "127.0.1.21:5020"})
    assert "127.0.1.21:5020" in e


def test_environment_bad_address_format(tmp_path):
    (e,) = env_errors(tmp_path, {**LAB, "10.20.0.30:502": "127.0.1.30"})
    assert "127.0.1.30" in e


def test_environment_missing_a_serial_port(tmp_path):
    with pytest.raises(PointMapError) as e:
        read(write_site(tmp_path, SITE, LAB, serial={}))
    (err,) = e.value.errors
    assert "/dev/ttyUSB0" in err and "dong-ho-rs485-03" in err


def test_missing_environment_file(tmp_path):
    with pytest.raises(PointMapError) as e:
        read(write_site(tmp_path, SITE, LAB), env="staging")
    assert "staging" in e.value.errors[0]


# ---------- simulator và collector từ chối khởi động với Point Map hỏng ----------
@pytest.mark.parametrize("script,extra", [
    ("tools/simulator/sim.py", []),
    ("tools/dashboard/collector.py", ["--once"]),
])
def test_startup_rejects_invalid_point_map(tmp_path, script, extra):
    cfg = broken(SITE)
    device(cfg, "bess-01")["byte_order"] = "ABDC"
    ports = {k: v.rsplit(":", 1)[0] + ":5031" for k, v in LAB.items()}      # không đụng simulator đang chạy
    bad = write_site(tmp_path, cfg, ports, serial={k: str(tmp_path / "tty") for k in LAB_SERIAL})
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    r = subprocess.run([sys.executable, script, "--config", bad, *extra],
                       capture_output=True, text=True, timeout=10, env=env)
    assert r.returncode != 0
    assert "ABDC" in r.stdout + r.stderr


# ---------- sơ đồ DC: hệ thống của thiết bị, đơn tuyến điện, làm mát ----------
def node(cfg, node_id):
    return next(n for n in cfg["topology"]["power"] if n["id"] == node_id)


def test_every_device_belongs_to_a_system():
    assert {d["name"]: d["system"] for d in GOOD["devices"]} == {
        "dong-ho-dien-01": "EPMS", "dong-ho-dien-02": "EPMS", "dong-ho-rs485-03": "EPMS",
        "bess-01": "EPMS", "ups-01": "EPMS", "crah-01": "BMS"}


def test_power_topology_is_marked_assumed():
    assert GOOD["topology"]["assumed"] is True
    roots = [n for n in GOOD["topology"]["power"] if "from" not in n]
    assert [n["kind"] for n in roots] == ["grid"]


def test_unknown_system():
    cfg = broken()
    device(cfg, "bess-01")["system"] = "SCADA"
    e = one_error(cfg)
    assert "bess-01" in e and "SCADA" in e


@pytest.mark.parametrize("change,word", [
    (lambda c: node(c, "tu-rack").update(meters=["dong-ho-khong-co"]), "dong-ho-khong-co"),
    (lambda c: node(c, "ups-01").update(device="ups-99"), "ups-99"),
    (lambda c: node(c, "ups-01").update({"from": "tu-khong-co"}), "tu-khong-co"),
    (lambda c: node(c, "ups-01").update(kind="nha-may"), "nha-may"),
    (lambda c: node(c, "tu-chinh").update({"from": "tu-rack"}), "vòng"),
    (lambda c: c["topology"]["power"].append(dict(node(c, "day-rack"))), "day-rack"),
    (lambda c: node(c, "day-rack").pop("label"), "label"),
    (lambda c: c["topology"]["cooling"][0].update(serves="phong-khac"), "phong-khac"),
    (lambda c: c["topology"]["cooling"][0].update(device="crah-99"), "crah-99"),
])
def test_bad_topology(change, word):
    cfg = broken()
    change(cfg)
    e = one_error(cfg)
    assert "topology" in e and word in e


def test_device_may_appear_only_once_in_power_topology():
    cfg = broken()
    node(cfg, "tu-phu")["meters"].append("dong-ho-dien-01")       # đã là đồng hồ của tu-chinh
    e = one_error(cfg)
    assert "dong-ho-dien-01" in e


def test_topology_is_optional():
    cfg = broken()
    del cfg["topology"]
    for d in cfg["devices"]:
        del d["system"]
    assert validate(cfg) == []


def test_unreachable_device_is_removed_from_topology_but_node_stays():
    env = {"addresses": {k: v for k, v in LAB.items()}, "serial": {},
           "unreachable": {"rtu:/dev/ttyUSB0": "cổng serial nằm trong container"},
           "bacnet_client": "127.0.0.1/8:47809"}
    cfg = load(PATH, env="sim", env_cfg=env)
    tu_phu = node(cfg, "tu-phu")
    assert tu_phu["meters"] == [] and tu_phu["show"] == [] and tu_phu["label"]["vi"]
