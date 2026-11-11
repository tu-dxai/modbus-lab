"""Collector tự tìm thiết bị qua simulator đang chạy (cổng điều khiển, mặc định 5080).

Simulator có thể chạy bằng make sim (môi trường lab, 127.0.1.x) hoặc trong Docker của demo A04
(môi trường site, đúng IP 10.20.0.x). Collector hỏi simulator thiết bị đang nghe ở đâu, nên đọc được
cả hai mà không phải sửa environments/*.yml. Không kết nối thiết bị thật.
"""
import collector
from collector import load_config, poll_once
from conftest import device
from modbus_io import Connections
from point_map import load, read
from simctl import SimControl, environment_from_state

PATH = "edge/point-map/devices.yml"
BACNET_PORT = 47829          # client BACnet riêng của bài này: không đụng collector đang chạy (47809)


def test_environment_follows_running_simulator(_sim):
    cfg, sim = _sim
    env = SimControl(sim.control_url).environment(bacnet_port=BACNET_PORT)
    gw, rtu = device(cfg, "dong-ho-dien-01"), device(cfg, "dong-ho-rs485-03")
    assert env["addresses"]["10.20.0.21:502"] == f"{gw['host']}:{gw['port']}"
    assert env["serial"]["/dev/ttyUSB0"] == rtu["serial"]["port"]      # cổng ảo simulator tạo trên máy này
    assert env["bacnet_client"] == f"127.0.0.1/32:{BACNET_PORT}"
    assert env["unreachable"] == {}


def test_collector_reads_every_device_found_via_simulator(_sim, sim_ctl):
    cfg = load(PATH, env="sim", env_cfg=SimControl(_sim[1].control_url).environment(bacnet_port=BACNET_PORT))
    sim_ctl.set("bess-01.muc_pin", 55.5)
    c = Connections()
    try:
        r = poll_once(c, cfg)
    finally:
        c.close()
    assert r["read"] == sum(len(d["points"]) for d in cfg["devices"])
    assert r["ok_count"] == r["read"]
    assert collector.LATEST["bess-01.muc_pin"]["value"] == 55.5


# Simulator trong Docker của demo A04 (--env site): nghe đúng địa chỉ site; cổng serial nằm trong container
DOCKER_STATE = {
    "dong-ho-dien-01.dien_ap": {"protocol": "modbus", "endpoint": "10.20.0.21:502", "site_endpoint": "10.20.0.21:502"},
    "bess-01.muc_pin": {"protocol": "modbus", "endpoint": "10.20.0.30:502", "site_endpoint": "10.20.0.30:502"},
    "ups-01.tai_ra": {"protocol": "snmp", "endpoint": "10.20.0.40:161", "site_endpoint": "10.20.0.40:161"},
    "dong-ho-rs485-03.dien_ap": {"protocol": "modbus", "endpoint": "rtu:/dev/ttyUSB0",
                                 "site_endpoint": "rtu:/dev/ttyUSB0"},
}


def test_docker_simulator_keeps_site_addresses_and_skips_serial_inside_container():
    env = environment_from_state(DOCKER_STATE, bacnet_port=BACNET_PORT)
    assert env["addresses"] == {"10.20.0.21:502": "10.20.0.21:502", "10.20.0.30:502": "10.20.0.30:502",
                                "10.20.0.40:161": "10.20.0.40:161"}
    assert env["serial"] == {}                     # không bao giờ mở /dev/ttyUSB0 thật của máy này
    assert "rtu:/dev/ttyUSB0" in env["unreachable"]
    assert "bacnet_client" not in env              # không có thiết bị BACnet


def test_point_map_drops_unreachable_devices_with_reason():
    site = read(PATH, env="site")
    env = {"addresses": {f"{d['host']}:{d['port']}": f"{d['host']}:{d['port']}"
                         for d in site["devices"] if d.get("transport") != "rtu"},
           "unreachable": {"rtu:/dev/ttyUSB0": "nằm trong container"},
           "bacnet_client": f"127.0.0.1/32:{BACNET_PORT}"}
    cfg = load(PATH, env="sim", env_cfg=env)
    assert "dong-ho-rs485-03" not in {d["name"] for d in cfg["devices"]}
    assert cfg["unreachable"] == {"dong-ho-rs485-03": "nằm trong container"}
    assert cfg["env"] == "sim"


def test_auto_uses_running_simulator_then_falls_back_to_lab(_sim):
    assert load_config(PATH, "auto", sim_url=_sim[1].control_url, bacnet_port=BACNET_PORT)["env"] == "sim"
    assert load_config(PATH, "auto", sim_url="http://127.0.0.1:9", bacnet_port=BACNET_PORT)["env"] == "lab"


def test_auto_picks_up_simulator_started_after_collector(_sim):
    """Collector chạy trước, simulator chạy sau (hoặc khởi động lại ở chỗ khác): lượt đọc kế tiếp theo kịp."""
    cfg = load_config(PATH, "auto", sim_url="http://127.0.0.1:9", bacnet_port=BACNET_PORT)
    assert cfg["env"] == "lab"
    cfg["auto"]["sim_url"] = _sim[1].control_url       # simulator giờ đã trả lời ở đây
    c = Connections()
    try:
        r = poll_once(c, cfg)
    finally:
        c.close()
    assert cfg["env"] == "sim"
    assert r["read"] > 0 and r["ok_count"] == r["read"]


def test_lab_config_never_switches_environment(cfg):
    """Chỉ cấu hình nạp bằng --env auto mới hỏi lại simulator; lab / site giữ nguyên địa chỉ."""
    assert "auto" not in cfg
