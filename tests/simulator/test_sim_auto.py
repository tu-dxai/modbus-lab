"""Kiểm thử chế độ tự thay đổi giá trị của simulator.

0 = chỉ thay đổi bằng tay. N giây: mỗi nhịp, điểm có sim.noise dao động quanh giá trị đặt gần nhất
(lúc đầu là sim.base), trong biên độ ±noise; điểm writable (giá trị client ghi vào) không tự đổi.
Simulator riêng ở cổng 5025; nhịp 1 giây cho kiểm thử nhanh.
"""
import json, time, urllib.error, urllib.request
import pytest
from conftest import lab_config
from sim import start
from simctl import SimControl

NOISY = {"dong-ho-dien-01.dien_ap": (230.0, 1.5), "dong-ho-dien-01.dong_dien": (12.0, 0.8),
         "dong-ho-dien-01.cong_suat": (2800.0, 60.0)}


@pytest.fixture(scope="module")
def sim():
    return start(lab_config(5025), control_port=0)


@pytest.fixture
def ctl(sim):
    c = SimControl(sim.control_url)
    c.set_auto(0)
    c.reset()
    yield c
    c.set_auto(0)
    c.reset()


def values(ctl):
    return {k: p["value"] for k, p in ctl.get().items()}


def test_manual_by_default(ctl):
    assert ctl.auto() == 0
    before = values(ctl)
    time.sleep(1.2)
    assert values(ctl) == before


def test_auto_changes_noisy_points_within_noise(ctl):
    before = values(ctl)
    ctl.set_auto(1)
    time.sleep(2.5)
    after = values(ctl)
    assert any(after[k] != before[k] for k in NOISY)
    for k, (base, noise) in NOISY.items():
        assert abs(after[k] - base) <= noise + 0.1
    assert after["bess-01.che_do"] == before["bess-01.che_do"]          # writable: không tự đổi


def test_auto_covers_snmp_and_bacnet_points(ctl):
    """Điểm SNMP / BACnet (không có type Modbus) cũng tự đổi, không làm dừng luồng tự thay đổi."""
    keys = ("ups-01.dien_ap_pin", "crah-01.do_am_hoi")
    before = values(ctl)
    ctl.set_auto(1)
    time.sleep(2.5)
    after = values(ctl)
    assert any(after[k] != before[k] for k in keys)


def test_auto_fluctuates_around_value_set_by_hand(ctl):
    ctl.set("dong-ho-dien-01.nhiet_do_tu", 31.5)
    ctl.set_auto(1)
    time.sleep(1.5)
    assert abs(ctl.get("dong-ho-dien-01.nhiet_do_tu")["value"] - 31.5) <= 0.3 + 0.05


def test_switching_off_freezes_values(ctl):
    ctl.set_auto(1)
    time.sleep(1.3)
    ctl.set_auto(0)
    frozen = values(ctl)
    time.sleep(1.3)
    assert values(ctl) == frozen


def test_state_reports_auto_interval(sim, ctl):
    ctl.set_auto(5)
    with urllib.request.urlopen(sim.control_url + "/api/state", timeout=3) as r:
        assert json.loads(r.read())["auto"] == 5


@pytest.mark.parametrize("interval", [-1, 0.5, 5000, "x"])
def test_bad_interval_is_rejected(sim, interval):
    req = urllib.request.Request(sim.control_url + "/api/auto", data=json.dumps({"interval": interval}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 400 and json.loads(e.value.read())["code"] == "api.bad_auto"
