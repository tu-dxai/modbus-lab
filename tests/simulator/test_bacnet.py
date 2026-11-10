"""Kiểm thử BACnet/IP: Point Map, thiết bị BACnet của simulator, collector đọc/ghi kèm mức ưu tiên và nhả lệnh.

Thiết bị mẫu crah-01 (điều hòa CRAH). Simulator chung ở tests/conftest.py; client BACnet của bộ kiểm thử
dùng cổng riêng (khác cổng thiết bị — cùng cổng thì gói tin quay về chính client).
"""
import copy
import pytest
from audit import AuditLog
from collector import LATEST, poll_once
from conftest import device
from generate import generate
from modbus_io import Connections
from point_map import read, validate
from simctl import SimControl
from write import WriteBlocked, WriteFailed, find, relinquish_guarded, write_guarded

CRAH = "crah-01"
PATH = "edge/point-map/devices.yml"


def bacnet_point(cfg, name):
    return next(p for p in device(cfg, CRAH)["points"] if p["name"] == name)


# ---------- Point Map ----------
def test_crah_in_point_map():
    cfg = read(PATH, env="site")
    d = device(cfg, CRAH)
    assert d["protocol"] == "bacnet" and d["device_instance"] == 5001 and (d["host"], d["port"]) == ("10.20.0.50", 47808)
    assert bacnet_point(cfg, "diem_dat_nhiet")["priority"] == 8
    assert cfg["bacnet"]["client"]


@pytest.mark.parametrize("change,word", [
    ({"object": "analog-input"}, "object"),
    ({"object": "pump,1"}, "object"),
    ({"writable": True, "min": 0, "max": 1}, "writable"),          # analog-input không ghi được
])
def test_bad_bacnet_point(change, word):
    cfg = read(PATH, env="site")
    bacnet_point(cfg, "nhiet_do_cap").update(change)
    errors = validate(cfg)
    assert len(errors) == 1 and f"{CRAH}.nhiet_do_cap" in errors[0] and word in errors[0]


def test_writable_bacnet_point_needs_priority():
    cfg = read(PATH, env="site")
    del bacnet_point(cfg, "diem_dat_nhiet")["priority"]
    (e,) = validate(cfg)
    assert f"{CRAH}.diem_dat_nhiet" in e and "priority" in e


def test_duplicate_bacnet_object():
    cfg = read(PATH, env="site")
    bacnet_point(cfg, "nhiet_do_hoi")["object"] = bacnet_point(cfg, "nhiet_do_cap")["object"]
    (e,) = validate(cfg)
    assert CRAH in e and "analog-input,1" in e


def test_bacnet_needs_client_address():
    cfg = read(PATH, env="site")
    del cfg["bacnet"]
    (e,) = validate(cfg)
    assert "bacnet" in e and "client" in e


def test_telegraf_skips_bacnet():
    text = generate(read(PATH, env="site"))
    assert CRAH in text.split("\n", 8)[5]                      # ghi chú ở đầu file: collector Python đọc BACnet
    assert "10.20.0.50" not in text


# ---------- đọc ----------
def test_read_analog_and_binary(cfg, conns):
    for name, expected in (("nhiet_do_cap", 18.0), ("trang_thai_quat", 1)):
        d, p = find(cfg, f"{CRAH}.{name}")
        assert conns.read(d, p) == pytest.approx(expected)


def test_value_set_on_simulator_is_read_over_bacnet(cfg, conns, sim_ctl):
    sim_ctl.set(f"{CRAH}.nhiet_do_hoi", 31.5)
    d, p = find(cfg, f"{CRAH}.nhiet_do_hoi")
    assert conns.read(d, p) == pytest.approx(31.5)


def test_poll_reads_whole_crah(cfg):
    poll_once(Connections(), cfg, device=CRAH)
    crah = {k: r for k, r in LATEST.items() if k.startswith(CRAH + ".")}
    assert len(crah) == len(device(cfg, CRAH)["points"]) and all(r["ok"] for r in crah.values())


# ---------- ghi kèm mức ưu tiên, nhả lệnh ----------
def test_write_setpoint_with_priority_then_relinquish(cfg, conns, tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    before, after = write_guarded(cfg, conns, f"{CRAH}.diem_dat_nhiet", 21.5, audit=log, actor="t")
    assert (before, after) == (pytest.approx(18.0), pytest.approx(21.5))
    released = relinquish_guarded(cfg, conns, f"{CRAH}.diem_dat_nhiet", audit=log, actor="t")
    assert released == pytest.approx(18.0)                     # về giá trị mặc định của thiết bị
    assert [e["outcome"] for e in log.tail()] == ["written", "released"]
    assert log.tail()[1]["priority"] == 8


def test_binary_command(cfg, conns):
    before, after = write_guarded(cfg, conns, f"{CRAH}.lenh_chay", 0)
    assert (before, after) == (1, 0)
    relinquish_guarded(cfg, conns, f"{CRAH}.lenh_chay")


@pytest.mark.parametrize("key,value", [(f"{CRAH}.diem_dat_nhiet", 35), (f"{CRAH}.nhiet_do_cap", 20)])
def test_guard_blocks_bacnet(cfg, conns, key, value):
    with pytest.raises(WriteBlocked):
        write_guarded(cfg, conns, key, value)


def test_device_rejects_write_to_input(cfg, conns):
    c = copy.deepcopy(cfg)
    _, p = find(c, f"{CRAH}.nhiet_do_cap")
    p.update(writable=True, min=0, max=50, priority=8)        # Point Map cho ghi, thiết bị không cho
    with pytest.raises(WriteFailed) as e:
        write_guarded(c, conns, f"{CRAH}.nhiet_do_cap", 20)
    assert e.value.code == "write.device_rejected"


def test_bacnet_write_is_witnessed_by_simulator(cfg, conns, sim_ctl):
    mark = sim_ctl.last_seq()
    write_guarded(cfg, conns, f"{CRAH}.diem_dat_nhiet", 20.0)
    relinquish_guarded(cfg, conns, f"{CRAH}.diem_dat_nhiet")
    writes = sim_ctl.writes(point=f"{CRAH}.diem_dat_nhiet", since=mark)
    assert [w["points"][0]["value"] for w in writes] == [20.0, None]
    assert all(w["accepted"] and w["priority"] == 8 for w in writes)
