"""Kiểm thử simulator điều khiển được: đặt giá trị, đọc lại qua Modbus, nhật ký lệnh ghi.

Simulator riêng ở cổng 5022 (môi trường lab, IP 127.0.1.x) để không ảnh hưởng các bài MB-xx;
kênh điều khiển chọn cổng tự do.
"""
import json, subprocess, sys, os, threading, time, urllib.error, urllib.request
import pytest
from pymodbus.client import ModbusTcpClient
from conftest import device, lab_config
from modbus_io import Connections
from sim import start
from simctl import SimControl
from write import find, write_guarded

MODBUS_PORT = 5022


@pytest.fixture(scope="module")
def sim():
    cfg = lab_config(MODBUS_PORT)
    s = start(cfg, control_port=0)
    s.cfg = cfg
    return s


@pytest.fixture
def conns(sim):
    c = Connections()
    yield c
    c.close()


@pytest.fixture
def ctl(sim):
    c = SimControl(sim.control_url)
    c.reset()
    yield c
    c.reset()


@pytest.fixture
def client(sim):
    """Kết nối thô tới gateway điện (dong-ho-dien-01 là device_id 1)."""
    d = device(sim.cfg, "dong-ho-dien-01")
    c = ModbusTcpClient(d["host"], port=d["port"], timeout=1, retries=0)
    c.connect()
    yield c
    c.close()


def modbus_read(sim, conns, key):
    d, p = find(sim.cfg, key)
    return conns.read(d, p)


def http(url, data=None, method=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            raw = r.read()
            return r.status, json.loads(raw) if "json" in r.headers["Content-Type"] else raw.decode()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ---------- giá trị đứng yên, do người kiểm thử đặt ----------
def test_values_stay_put(sim, ctl, conns):
    first = modbus_read(sim, conns, "dong-ho-dien-01.dien_ap")
    time.sleep(0.3)
    assert modbus_read(sim, conns, "dong-ho-dien-01.dien_ap") == first == pytest.approx(230.0)


def test_set_value_is_read_over_modbus(sim, ctl, conns):
    ctl.set("dong-ho-dien-01.dien_ap", 231.5)
    assert modbus_read(sim, conns, "dong-ho-dien-01.dien_ap") == pytest.approx(231.5)


@pytest.mark.parametrize("key,value", [
    ("bess-01.muc_pin", 15.25),               # float32, byte order CDAB
    ("bess-01.nhiet_do_pin", -5.3),           # int16 có dấu, hệ số 0.1
    ("dong-ho-dien-01.cong_suat", 41250.5),   # float32, byte order ABCD
])
def test_set_value_respects_type_byte_order_and_scale(sim, ctl, conns, key, value):
    ctl.set(key, value)
    assert modbus_read(sim, conns, key) == pytest.approx(value, abs=0.01)


def test_set_many_at_once(sim, ctl, conns):
    ctl.set_many({"bess-01.muc_pin": 18.0, "dong-ho-dien-01.nhiet_do_tu": 31.2})
    assert modbus_read(sim, conns, "bess-01.muc_pin") == pytest.approx(18.0)
    assert modbus_read(sim, conns, "dong-ho-dien-01.nhiet_do_tu") == pytest.approx(31.2)


def test_set_writable_point_is_read_over_modbus(sim, ctl, conns):
    ctl.set("bess-01.che_do", 1)                # mô phỏng người vận hành đổi tại chỗ
    assert modbus_read(sim, conns, "bess-01.che_do") == 1


def test_state_lists_every_point(sim, ctl):
    state = ctl.get()
    keys = [f"{d['name']}.{p['name']}" for d in sim.cfg["devices"] for p in d["points"]]
    assert sorted(state) == sorted(keys)
    assert state["bess-01.muc_pin"]["value"] == pytest.approx(80.0)
    assert state["bess-01.che_do"]["writable"] is True


def test_set_unknown_point_is_rejected(sim, ctl):
    code, r = http(sim.control_url + "/api/state", {"khong-co.diem_nao": 1})
    assert code == 404 and "khong-co.diem_nao" in r["error"]
    assert r["code"] == "sim.unknown_points" and r["params"]["keys"] == ["khong-co.diem_nao"]


def test_set_value_that_does_not_fit_register_is_rejected(sim, ctl, conns):
    code, r = http(sim.control_url + "/api/state", {"dong-ho-dien-01.dien_ap": 7000})   # 70000 > uint16
    assert code == 400 and "dong-ho-dien-01.dien_ap" in r["error"]
    assert r["code"] == "sim.bad_value" and r["params"]["key"] == "dong-ho-dien-01.dien_ap"
    assert modbus_read(sim, conns, "dong-ho-dien-01.dien_ap") == pytest.approx(230.0)


def test_failed_batch_changes_nothing(sim, ctl, conns):
    code, _ = http(sim.control_url + "/api/state", {"bess-01.muc_pin": 50.0, "dong-ho-dien-01.dien_ap": 7000})
    assert code == 400
    assert modbus_read(sim, conns, "bess-01.muc_pin") == pytest.approx(80.0)


def test_reset_restores_initial_values(sim, ctl, conns):
    ctl.set("bess-01.muc_pin", 5.0)
    ctl.reset()
    assert modbus_read(sim, conns, "bess-01.muc_pin") == pytest.approx(80.0)


# ---------- nhân chứng: mọi lệnh ghi của client ----------
def test_accepted_write_is_logged_and_updates_state(sim, ctl, conns, client):
    write_guarded(sim.cfg, conns, "bess-01.che_do", 1)
    (w,) = ctl.writes()
    bess = device(sim.cfg, "bess-01")
    assert w["accepted"] is True and w["device"] == "bess-01" and w["device_id"] == 1
    assert w["endpoint"] == f"{bess['host']}:{bess['port']}" and w["site_endpoint"] == "10.20.0.30:502"
    assert w["address"] == 10 and w["exception"] is None
    assert w["points"] == [{"key": "bess-01.che_do", "before": 0, "value": 1}]
    assert ctl.get("bess-01.che_do")["value"] == 1


def test_write_to_readonly_point_is_logged_as_rejected(sim, ctl, client):
    client.write_register(0, 999, device_id=1)
    (w,) = ctl.writes()
    assert w["accepted"] is False and w["exception"] == 2
    assert [p["key"] for p in w["points"]] == ["dong-ho-dien-01.dien_ap"]
    assert ctl.get("dong-ho-dien-01.dien_ap")["value"] == pytest.approx(230.0)


def test_write_to_undeclared_address_is_logged(sim, ctl, client):
    client.write_register(50, 1, device_id=1)   # client cấu hình sai địa chỉ
    (w,) = ctl.writes()
    assert w["accepted"] is False and w["address"] == 50 and w["points"] == []


def test_write_to_unknown_device_is_logged(sim, ctl, client):
    client.write_register(10, 1, device_id=9)   # client cấu hình sai device_id
    (w,) = ctl.writes()
    assert w["accepted"] is False and w["device_id"] == 9 and w["device"] is None
    assert w["site_endpoint"] == "10.20.0.21:502"                # gateway điện


def test_writes_filtered_by_point_and_since(sim, ctl, conns, client):
    write_guarded(sim.cfg, conns, "bess-01.che_do", 1)
    client.write_register(0, 999, device_id=1)
    assert len(ctl.writes(point="bess-01.che_do")) == 1
    first = ctl.writes()[0]["seq"]
    assert [w["seq"] for w in ctl.writes(since=first)] == [first + 1]


def test_clear_writes(sim, ctl, conns, client):
    write_guarded(sim.cfg, conns, "bess-01.che_do", 1)
    ctl.clear_writes()
    assert ctl.writes() == []


def test_wait_for_write_returns_when_client_writes(sim, ctl):
    def later():
        time.sleep(0.3)
        c = Connections()
        write_guarded(sim.cfg, c, "bess-01.che_do", 1)
        c.close()
    threading.Thread(target=later).start()
    w = ctl.wait_for_write("bess-01.che_do", timeout=3)
    assert w["points"][0]["value"] == 1


def test_wait_for_write_times_out(sim, ctl):
    with pytest.raises(TimeoutError):
        ctl.wait_for_write("bess-01.che_do", timeout=0.3)


# ---------- trang điều khiển và dòng lệnh ----------
def test_control_page(sim):
    code, html = http(sim.control_url + "/")
    assert code == 200 and "<title>Simulator</title>" in html


def test_control_serves_shared_stylesheet(sim):
    r = urllib.request.urlopen(sim.control_url + "/ui.css", timeout=3)
    assert "text/css" in r.headers["Content-Type"] and ".workspace" in r.read().decode()
    r = urllib.request.urlopen(sim.control_url + "/ui.js", timeout=3)
    assert "javascript" in r.headers["Content-Type"] and "function renderSidebar" in r.read().decode()


def test_control_serves_dictionary(sim):
    code, d = http(sim.control_url + "/i18n.json")
    assert code == 200 and set(d) == {"vi", "ja"} and d["ja"]["sim.bad_value"]


def test_state_carries_bilingual_labels(sim, ctl):
    row = ctl.get("bess-01.muc_pin")
    assert set(row["label"]) == {"vi", "ja"} and set(row["device_label"]) == {"vi", "ja"}


def test_cli_set_and_get(sim, ctl):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), SIM_URL=sim.control_url)
    run = lambda *a: subprocess.run([sys.executable, "tools/simulator/simctl.py", *a],
                                    capture_output=True, text=True, timeout=10, env=env)
    r = run("set", "bess-01.muc_pin", "42.5")
    assert r.returncode == 0, r.stderr
    assert ctl.get("bess-01.muc_pin")["value"] == pytest.approx(42.5)
    r = run("set", "khong-co.diem_nao", "1")
    assert r.returncode != 0 and "khong-co.diem_nao" in r.stdout + r.stderr


# ---------- nhân chứng ghi lại mọi kiểu lệnh ghi; đầu vào xấu không làm hỏng simulator ----------
def test_mask_write_and_read_write_registers_are_logged(sim, ctl):
    """FC23 và FC22 cũng đổi giá trị thanh ghi, nên phải có trong nhật ký như FC6/FC16; lệnh ghi coil cũng vậy."""
    d = device(sim.cfg, "bess-01")
    mark = ctl.last_seq()
    c = ModbusTcpClient(d["host"], port=d["port"], timeout=1, retries=0)
    c.connect()
    try:
        assert not c.readwrite_registers(read_address=10, read_count=1, write_address=10, values=[1],
                                         device_id=d["device_id"]).isError()
        assert not c.mask_write_register(address=10, and_mask=0x0000, or_mask=0x0000,
                                         device_id=d["device_id"]).isError()
        c.write_coil(0, True, device_id=d["device_id"])
    finally:
        c.close()
    fc23, fc22, fc5 = ctl.writes(since=mark)
    assert fc23["function"] == 23 and fc23["accepted"]
    assert fc23["points"] == [{"key": "bess-01.che_do", "before": 0, "value": 1}]
    assert fc22["function"] == 22 and fc22["accepted"]
    assert fc22["points"] == [{"key": "bess-01.che_do", "before": 1, "value": 0}]
    assert fc5["function"] == 5 and fc5["points"] == [] and fc5["coils"] == [True]
    assert ctl.get("bess-01.che_do")["value"] == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_set_nan_is_rejected_and_state_stays_valid_json(sim, ctl, value):
    code, r = http(sim.control_url + "/api/state", {"bess-01.muc_pin": value})
    assert code == 400 and r["code"] == "sim.bad_value"
    with urllib.request.urlopen(sim.control_url + "/api/state", timeout=3) as resp:   # json.loads nhận NaN:
        raw = resp.read()                                                              # kiểm chuỗi thô
    assert b"NaN" not in raw and b"Infinity" not in raw


@pytest.mark.parametrize("length", ["-1", "abc", str(10 ** 9)])
def test_bad_content_length_is_rejected_without_hanging(sim, length):
    import http.client
    from urllib.parse import urlparse
    u = urlparse(sim.control_url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=3)
    try:
        conn.putrequest("POST", "/api/state")
        conn.putheader("Content-Length", length)
        conn.endheaders()
        assert conn.getresponse().status == 400
    finally:
        conn.close()
