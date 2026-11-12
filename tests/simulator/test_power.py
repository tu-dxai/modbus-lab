"""Kiểm thử bật / tắt thiết bị giả: thiết bị tắt phản ứng giống thiết bị thật mất điện, theo kiểu kết nối.

  - thiết bị có IP riêng (bess-01):            từ chối kết nối TCP, kết nối đang mở bị cắt
  - thiết bị sau gateway (dong-ho-dien-02):     gateway vẫn chạy, trả mã lỗi 0B; thiết bị cùng gateway vẫn đọc được
  - RS-485 (dong-ho-rs485-03), SNMP, BACnet:   im lặng, client chờ hết timeout
Thiết bị đang tắt không thực thi lệnh nào (lệnh ghi không đổi giá trị). Đặt lại simulator thì bật lại tất cả.
Dùng simulator chung ở tests/conftest.py; sim_ctl đặt lại (bật mọi thiết bị) sau mỗi bài.
"""
import copy, json, os, socket, subprocess, sys, time, urllib.error, urllib.request
import pytest
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException
from collector import LATEST, poll_once
from conftest import device
from modbus_io import Connections, ReadError
from write import find


def raw_client(d):
    return ModbusTcpClient(d["host"], port=d["port"], timeout=1, retries=0)


def quick(cfg, name, timeout=0.5):
    """Bản sao thiết bị với timeout ngắn để bài kiểm thử không phải chờ lâu."""
    return dict(copy.deepcopy(device(cfg, name)), timeout=timeout)


def test_power_state_is_reported(sim_ctl):
    assert sim_ctl.power("bess-01", False) == {"ok": True, "device": "bess-01", "on": False}
    rows = sim_ctl.get()
    assert all(not r["on"] for r in rows.values() if r["device"] == "bess-01")
    assert all(r["on"] for r in rows.values() if r["device"] != "bess-01")


def test_direct_device_refuses_connection_then_comes_back(cfg, sim_ctl):
    d = device(cfg, "bess-01")
    before = raw_client(d)
    assert before.connect()
    sim_ctl.power("bess-01", False)
    with pytest.raises(ConnectionException):                                   # kết nối đang mở bị cắt
        before.read_holding_registers(10, count=1, device_id=1)
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection((d["host"], d["port"]), timeout=1).close()
    assert not Connections().reachable(d)
    sim_ctl.power("bess-01", True)
    c = Connections()
    assert c.read(*find(cfg, "bess-01.muc_pin")) == pytest.approx(80.0)
    c.close()
    before.close()


def test_device_behind_gateway_gets_exception_0b(cfg, sim_ctl):
    sim_ctl.power("dong-ho-dien-02", False)
    c = raw_client(device(cfg, "dong-ho-dien-02"))
    r = c.read_holding_registers(0, count=1, device_id=2)
    assert r.isError() and r.exception_code == 0x0B
    w = c.write_register(0, 1234, device_id=2)                   # không thực thi: 0B, không phải 02 (ô chỉ đọc)
    assert w.isError() and w.exception_code == 0x0B
    assert not c.read_holding_registers(0, count=1, device_id=1).isError()      # cùng gateway, vẫn chạy
    c.close()
    sim_ctl.power("dong-ho-dien-02", True)
    assert sim_ctl.get("dong-ho-dien-02.dien_ap")["value"] != 123.4


def test_write_to_device_behind_gateway_is_logged_as_0b(cfg, sim_ctl):
    sim_ctl.power("dong-ho-dien-02", False)
    mark = sim_ctl.last_seq()
    c = raw_client(device(cfg, "dong-ho-dien-02"))
    c.write_register(0, 1234, device_id=2)
    c.close()
    (w,) = sim_ctl.writes(since=mark)
    assert not w["accepted"] and w["exception"] == 0x0B


def test_rtu_device_is_silent(cfg, sim_ctl, conns):
    d, p = find(cfg, "dong-ho-rs485-03.dien_ap")
    sim_ctl.power("dong-ho-rs485-03", False)
    with pytest.raises(Exception):
        conns.read(d, p)
    sim_ctl.power("dong-ho-rs485-03", True)
    assert conns.read(d, p) == pytest.approx(231.0)


@pytest.mark.parametrize("name,code", [("ups-01", "read.snmp_no_answer"), ("crah-01", "read.bacnet_no_answer")])
def test_udp_device_is_silent(cfg, sim_ctl, conns, name, code):
    d = quick(cfg, name)
    sim_ctl.power(name, False)
    with pytest.raises(ReadError) as e:
        conns.read(d, d["points"][0])
    assert e.value.code == code
    sim_ctl.power(name, True)
    assert conns.read(d, d["points"][0]) is not None


def test_reset_turns_every_device_on(sim_ctl):
    for name in ("bess-01", "ups-01", "dong-ho-dien-02"):
        sim_ctl.power(name, False)
    sim_ctl.reset()
    assert all(r["on"] for r in sim_ctl.get().values())


def test_values_set_while_off_are_served_after_power_on(cfg, sim_ctl, conns):
    sim_ctl.power("bess-01", False)
    sim_ctl.set("bess-01.muc_pin", 55.5)
    sim_ctl.power("bess-01", True)
    assert conns.read(*find(cfg, "bess-01.muc_pin")) == pytest.approx(55.5)


@pytest.mark.parametrize("body,status,code", [
    ({"device": "khong-co", "on": False}, 404, "sim.unknown_device"),
    ({"device": "bess-01", "on": "off"}, 400, "api.bad_power_request"),
    ({"on": False}, 400, "api.bad_power_request"),
])
def test_power_api_rejects_bad_requests(sim_ctl, body, status, code):
    req = urllib.request.Request(sim_ctl.url + "/api/power", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == status and json.loads(e.value.read())["code"] == code


def test_collector_skips_rest_of_silent_device(cfg, sim_ctl):
    c = copy.deepcopy(cfg)
    ups = device(c, "ups-01")
    ups["timeout"] = 0.5
    sim_ctl.power("ups-01", False)
    t0 = time.perf_counter()
    conns = Connections()
    try:
        r = poll_once(conns, c, device="ups-01")
    finally:
        conns.close()
    assert time.perf_counter() - t0 < 2.5                      # 7 điểm nhưng chỉ chờ timeout một lần
    rows = [LATEST[f"ups-01.{p['name']}"] for p in ups["points"]]
    assert r["ok_count"] == 0 and rows[0]["code"] == "read.snmp_no_answer"
    assert all(x["code"] == "read.skipped" for x in rows[1:])


def test_cli_power(sim_ctl):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), SIM_URL=sim_ctl.url)
    run = lambda *a: subprocess.run([sys.executable, "tools/simulator/simctl.py", *a],
                                    capture_output=True, text=True, timeout=10, env=env)
    r = run("power", "ups-01", "off")
    assert r.returncode == 0, r.stderr
    assert not sim_ctl.get("ups-01.muc_pin")["on"]
    r = run("power")
    assert "ups-01" in r.stdout and r.returncode == 0
    assert run("power", "ups-01", "on").returncode == 0 and sim_ctl.get("ups-01.muc_pin")["on"]


def test_collector_round_survives_exception_0b(cfg, sim_ctl):
    """Mã lỗi Modbus (ở đây 0B từ gateway) chỉ làm lỗi đúng điểm đó; lượt đọc vẫn xong, thiết bị khác vẫn đọc được."""
    sim_ctl.power("dong-ho-dien-02", False)
    c = Connections()
    try:
        r = poll_once(c, cfg, device=None)
    finally:
        c.close()                                    # nhả cổng serial: một bus RS-485 chỉ có một master
    row = LATEST["dong-ho-dien-02.dien_ap"]
    assert row["code"] == "read.modbus_exception" and row["params"] == {"code": 11}
    assert LATEST["dong-ho-dien-01.dien_ap"]["ok"] and r["ok_count"] == r["read"] - 4
