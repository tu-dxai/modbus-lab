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


def write_site(tmp_path, cfg, addresses):
    (tmp_path / "devices.yml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "lab.yml").write_text(
        yaml.safe_dump({"addresses": addresses}), encoding="utf-8")
    return str(tmp_path / "devices.yml")


LAB = {"10.20.0.21:502": "127.0.1.21:5020", "10.20.0.30:502": "127.0.1.30:5020"}


def env_errors(tmp_path, addresses):
    with pytest.raises(PointMapError) as e:
        read(write_site(tmp_path, SITE, addresses))
    return e.value.errors


def test_environment_missing_an_address(tmp_path):
    (e,) = env_errors(tmp_path, {"10.20.0.21:502": "127.0.1.21:5020"})
    assert "10.20.0.30:502" in e and "bess-01" in e


def test_environment_with_unused_address(tmp_path):
    (e,) = env_errors(tmp_path, {**LAB, "10.20.0.99:502": "127.0.1.99:5020"})
    assert "10.20.0.99:502" in e


def test_environment_maps_two_addresses_to_one(tmp_path):
    (e,) = env_errors(tmp_path, {"10.20.0.21:502": "127.0.1.21:5020", "10.20.0.30:502": "127.0.1.21:5020"})
    assert "127.0.1.21:5020" in e


def test_environment_bad_address_format(tmp_path):
    (e,) = env_errors(tmp_path, {**LAB, "10.20.0.30:502": "127.0.1.30"})
    assert "127.0.1.30" in e


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
    bad = write_site(tmp_path, cfg, {"10.20.0.21:502": "127.0.1.21:5031", "10.20.0.30:502": "127.0.1.30:5031"})
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    r = subprocess.run([sys.executable, script, "--config", bad, *extra],
                       capture_output=True, text=True, timeout=10, env=env)
    assert r.returncode != 0
    assert "ABDC" in r.stdout + r.stderr
