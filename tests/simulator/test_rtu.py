"""Kiểm thử Modbus RTU qua cổng serial ảo: Point Map, đọc/ghi, khung tin có CRC, Telegraf.

Simulator chung ở tests/conftest.py mở bus RS-485 ảo cho các thiết bị transport: rtu; collector đọc
qua cổng serial đó như qua cổng USB-RS485 thật.
"""
import copy, tomllib
import pytest
from collector import poll_once, LATEST
from conftest import device, lab_config
from frames import FrameLog, parse_rtu
from generate import generate
from modbus_io import Connections, address
from point_map import read, serial_over_tcp, validate
from sim import start
from simctl import SimControl
from write import find, write_guarded

RTU = "dong-ho-rs485-03"
PATH = "edge/point-map/devices.yml"


# ---------- Point Map ----------
def test_rtu_device_in_point_map():
    d = device(read(PATH, env="site"), RTU)
    assert d["transport"] == "rtu" and d["serial"]["port"] == "/dev/ttyUSB0" and "host" not in d


def test_lab_maps_serial_port_to_virtual_port():
    d = device(read(PATH), RTU)
    assert d["serial"]["port"].startswith("var/serial/") and d["site_address"] == "rtu:/dev/ttyUSB0"
    assert address(d) == f"rtu:{d['serial']['port']}"


@pytest.mark.parametrize("change,word", [
    ({"baudrate": 12345}, "baudrate"), ({"parity": "X"}, "parity"), ({"stop_bits": 3}, "stop_bits"),
])
def test_bad_serial_settings(change, word):
    cfg = read(PATH, env="site")
    device(cfg, RTU)["serial"].update(change)
    errors = validate(cfg)
    assert len(errors) == 1 and RTU in errors[0] and word in errors[0]


def test_rtu_device_needs_serial_port():
    cfg = read(PATH, env="site")
    del device(cfg, RTU)["serial"]
    (e,) = validate(cfg)
    assert RTU in e and "serial" in e


def test_devices_on_one_bus_share_settings():
    cfg = read(PATH, env="site")
    twin = copy.deepcopy(device(cfg, RTU))
    twin.update(name="dong-ho-rs485-04", device_id=4)
    twin["serial"]["baudrate"] = 19200                     # cùng cổng nhưng khác tốc độ: sai
    cfg["devices"].append(twin)
    (e,) = validate(cfg)
    assert "dong-ho-rs485-04" in e and "baudrate" in e


def test_device_id_on_bus_is_rtu_address():
    cfg = read(PATH, env="site")
    device(cfg, RTU)["device_id"] = 0
    (e,) = validate(cfg)
    assert RTU in e and "1-247" in e


# ---------- đọc / ghi qua cổng serial ảo ----------
def test_read_over_rtu(cfg, conns):
    d, p = find(cfg, f"{RTU}.dien_ap")
    assert conns.read(d, p) == pytest.approx(231.0)


def test_write_over_rtu_with_readback(cfg, conns):
    before, after = write_guarded(cfg, conns, f"{RTU}.che_do_dem", 1)
    assert after == 1
    write_guarded(cfg, conns, f"{RTU}.che_do_dem", before)


def test_poll_reads_rtu_alongside_tcp(cfg):
    c = Connections()
    poll_once(c, cfg, device=RTU)
    c.close()                                          # một bus RS-485 chỉ có một master: đóng để bài sau mở được
    assert all(r["ok"] for k, r in LATEST.items() if k.startswith(RTU + "."))


# ---------- khung tin RTU ----------
def test_parse_rtu_request_and_response():
    req = parse_rtu(bytes.fromhex("01 03 00 00 00 02 c4 0b"), response=False)
    assert [f["name"] for f in req["fields"]] == ["unit", "function", "start", "quantity", "crc"]
    assert (req["unit"], req["function"], req["start"], req["quantity"]) == (1, 3, 0, 2)
    resp = parse_rtu(bytes.fromhex("01 03 04 09 01 00 78 a8 4d"), response=True)
    assert resp["registers"] == [0x0901, 0x78] and not resp["malformed"]
    exc = parse_rtu(bytes.fromhex("01 83 02 c0 f1"), response=True)
    assert exc["exception"] == 2


def test_parse_rtu_rejects_bad_crc():
    r = parse_rtu(bytes.fromhex("01 03 00 00 00 02 c4 0c"), response=False)
    assert r["malformed"] and r["fields"][-1]["name"] == "crc"


def test_client_frames_over_rtu(cfg):
    d = device(cfg, RTU)
    log = FrameLog({(address(x), x.get("device_id")): x for x in cfg["devices"]})
    c = Connections(frames=log)
    poll_once(c, cfg, point=f"{RTU}.dien_ap")
    c.close()
    (f,) = log.query()
    assert f["device"] == RTU and f["site_endpoint"] == "rtu:/dev/ttyUSB0"
    assert [x["name"] for x in f["request"]["fields"]] == ["unit", "function", "start", "quantity", "crc"]
    assert f["values"][0]["value"] == pytest.approx(231.0) and f["status"] is None


# ---------- Telegraf ----------
def test_telegraf_rtu_controller():
    conf = tomllib.loads(generate(read(PATH, env="site")))
    inp = next(i for i in conf["inputs"]["modbus"] if i["controller"] == "file:///dev/ttyUSB0")
    assert inp["transmission_mode"] == "RTU" and inp["baud_rate"] == 9600 and inp["parity"] == "N"
    assert inp["request"][0]["slave_id"] == 3


# ---------- Bus RS-485 qua TCP (bộ chuyển serial ↔ Ethernet, RTU over TCP) ----------
RS485_TCP = "127.0.0.1:5035"                           # địa chỉ riêng của bài này


def test_serial_over_tcp_maps_bus_to_socket_url():
    cfg = read(PATH, env="site")
    assert serial_over_tcp(cfg, {"/dev/ttyUSB0": "10.20.0.60:7000"}) == []
    d = device(cfg, RTU)
    assert d["serial"]["port"] == "socket://10.20.0.60:7000" and d["site_address"] == "rtu:/dev/ttyUSB0"
    assert validate(cfg) == []


@pytest.mark.parametrize("mapping,word", [({"/dev/ttyUSB9": "10.20.0.60:7000"}, "/dev/ttyUSB9"),
                                          ({"/dev/ttyUSB0": "khong-co-cong"}, "host:port")])
def test_serial_over_tcp_rejects_bad_mapping(mapping, word):
    errors = serial_over_tcp(read(PATH, env="site"), mapping)
    assert len(errors) == 1 and word in errors[0]


@pytest.fixture(scope="module")
def rtu_over_tcp():
    """Simulator riêng chỉ có bus RS-485, mở qua TCP như sau một bộ chuyển serial ↔ Ethernet."""
    cfg = lab_config(5034)
    cfg["devices"], cfg["alerts"] = [device(cfg, RTU)], []
    assert serial_over_tcp(cfg, {"/dev/ttyUSB0": RS485_TCP}) == []
    sim = start(cfg, control_port=0)
    return cfg, sim


def test_read_rtu_device_through_tcp_bus(rtu_over_tcp):
    cfg, sim = rtu_over_tcp
    SimControl(sim.control_url).set(f"{RTU}.dien_ap", 228.4)
    c = Connections()
    try:
        assert c.read(device(cfg, RTU), next(p for p in device(cfg, RTU)["points"] if p["name"] == "dien_ap")) == 228.4
    finally:
        c.close()


def test_environment_from_simulator_reaches_tcp_bus(rtu_over_tcp):
    env = SimControl(rtu_over_tcp[1].control_url).environment()
    assert env["serial"] == {"/dev/ttyUSB0": f"socket://{RS485_TCP}"} and env["unreachable"] == {}


def test_telegraf_reads_tcp_bus_as_rtu_over_tcp():
    cfg = read(PATH, env="site")
    serial_over_tcp(cfg, {"/dev/ttyUSB0": "10.20.0.60:7000"})
    inp = next(i for i in tomllib.loads(generate(cfg))["inputs"]["modbus"] if i["controller"] == "tcp://10.20.0.60:7000")
    assert inp["transmission_mode"] == "RTUoverTCP" and "baud_rate" not in inp
    assert inp["request"][0]["slave_id"] == 3
