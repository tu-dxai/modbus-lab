"""Kiểm thử khung tin Modbus: phân tích byte thô, ghép cặp hỏi/đáp, giải nghĩa, API và dòng lệnh.

Phần phân tích dùng đúng các byte thật bắt được trên đường truyền. Phần tích hợp dùng simulator
riêng ở cổng 5023 (môi trường lab), kênh điều khiển cổng tự do.
"""
import os, subprocess, sys
import pytest
from conftest import device, lab_config
from frames import parse_adu, split_adus
from i18n import LANGS, t
from modbus_io import Connections
from pymodbus.client import ModbusTcpClient
from sim import start
from simctl import SimControl
from write import find, write_guarded

H = bytes.fromhex


def fields(r):
    return " | ".join(f["hex"] for f in r["fields"])


def names(r):
    return [f["name"] for f in r["fields"]]


# ---------- phân tích byte thô ----------
def test_read_request_like_on_the_wire():
    r = parse_adu(H("00 01 00 00 00 06 01 03 00 00 00 01"), response=False)
    assert fields(r) == "00 01 | 00 00 | 00 06 | 01 | 03 | 00 00 | 00 01"
    assert names(r) == ["transaction", "protocol", "length", "unit", "function", "start", "quantity"]
    assert (r["transaction"], r["unit"], r["function"], r["start"], r["quantity"]) == (1, 1, 3, 0, 1)


def test_read_response_like_on_the_wire():
    r = parse_adu(H("00 01 00 00 00 05 01 03 02 09 01"), response=True)
    assert fields(r) == "00 01 | 00 00 | 00 05 | 01 | 03 | 02 | 09 01"
    assert names(r)[-2:] == ["byte_count", "data"]
    assert r["registers"] == [0x0901] and r["exception"] is None


def test_exception_response():
    r = parse_adu(H("00 02 00 00 00 03 01 83 02"), response=True)
    assert fields(r) == "00 02 | 00 00 | 00 03 | 01 | 83 | 02"
    assert names(r)[-1] == "exception"
    assert r["function"] == 3 and r["exception"] == 2


def test_write_single_request():
    r = parse_adu(H("00 03 00 00 00 06 01 06 00 00 03 e7"), response=False)
    assert names(r)[-2:] == ["address", "value"]
    assert (r["function"], r["start"], r["registers"]) == (6, 0, [999])


def test_write_multiple_request_and_ack():
    r = parse_adu(H("00 04 00 00 00 09 01 10 00 0a 00 01 02 00 01"), response=False)
    assert fields(r) == "00 04 | 00 00 | 00 09 | 01 | 10 | 00 0a | 00 01 | 02 | 00 01"
    assert names(r)[-4:] == ["start", "quantity", "byte_count", "values"]
    assert (r["start"], r["quantity"], r["registers"]) == (10, 1, [1])
    ack = parse_adu(H("00 04 00 00 00 06 01 10 00 0a 00 01"), response=True)
    assert names(ack)[-2:] == ["start", "quantity"] and ack["start"] == 10


def test_split_several_frames_in_one_packet():
    data = H("00 01 00 00 00 06 01 03 00 00 00 01" "00 02 00 00 00 06 01 03 00 01 00 01")
    assert [a.hex(" ") for a in split_adus(data)] == ["00 01 00 00 00 06 01 03 00 00 00 01",
                                                     "00 02 00 00 00 06 01 03 00 01 00 01"]


def test_malformed_bytes_do_not_crash():
    r = parse_adu(H("00 01 00"), response=False)
    assert r["malformed"] and fields(r) == "00 01 00"


# ---------- simulator thật ----------
MODBUS_PORT = 5023


@pytest.fixture(scope="module")
def sim():
    cfg = lab_config(MODBUS_PORT)
    s = start(cfg, control_port=0)
    s.cfg = cfg
    return s


@pytest.fixture
def ctl(sim):
    c = SimControl(sim.control_url)
    c.reset()
    yield c
    c.reset()


@pytest.fixture
def conns(sim):
    c = Connections()
    yield c
    c.close()


def read(sim, conns, key):
    d, p = find(sim.cfg, key)
    return conns.read(d, p)


def test_read_frame_pairs_request_and_response(sim, ctl, conns):
    ctl.set("dong-ho-dien-01.dien_ap", 230.5)
    read(sim, conns, "dong-ho-dien-01.dien_ap")
    (f,) = ctl.frames()
    assert fields(f["request"]).endswith("| 00 00 | 00 06 | 01 | 03 | 00 00 | 00 01")
    assert fields(f["response"]).endswith("| 00 00 | 00 05 | 01 | 03 | 02 | 09 01")
    assert f["request"]["transaction"] == f["response"]["transaction"]
    assert f["device"] == "dong-ho-dien-01" and f["site_endpoint"] == "10.20.0.21:502"
    assert f["function"] == 3 and f["exception"] is None and f["ms"] >= 0


def test_read_frame_explains_value(sim, ctl, conns):
    ctl.set("dong-ho-dien-01.dien_ap", 230.5)
    read(sim, conns, "dong-ho-dien-01.dien_ap")
    (v,) = ctl.frames()[0]["values"]
    assert v == {"key": "dong-ho-dien-01.dien_ap", "label": {"vi": "Điện áp", "ja": "電圧"},
                 "hex": "09 01", "raw": 2305, "value": 230.5, "unit": "V",
                 "type": "uint16", "byte_order": "ABCD", "scale": 0.1}


@pytest.mark.parametrize("key,hexs,raw,value", [
    ("bess-01.muc_pin", "00 00 42 a0", 80.0, 80.0),       # float32 CDAB: word thấp trước
    ("bess-01.nhiet_do_pin", "ff ec", -20, -2.0),         # int16 âm, bù hai
])
def test_read_frame_explains_byte_order_and_sign(sim, ctl, conns, key, hexs, raw, value):
    read(sim, conns, key)
    (v,) = ctl.frames()[0]["values"]
    assert (v["hex"], v["raw"], v["value"]) == (hexs, raw, value)


def test_exception_frame(sim, ctl):
    d = device(sim.cfg, "dong-ho-dien-01")
    c = ModbusTcpClient(d["host"], port=d["port"], timeout=1, retries=0)
    c.connect()
    c.read_holding_registers(50, count=1, device_id=1)    # ô không khai báo
    c.close()
    (f,) = ctl.frames()
    assert f["exception"] == 2 and f["response"]["fields"][4]["hex"] == "83"
    assert f["values"] == []


def test_write_frame_explains_written_value(sim, ctl, conns):
    write_guarded(sim.cfg, conns, "bess-01.che_do", 1)    # đọc trước, ghi, đọc lại
    writes = ctl.frames(function=16)
    assert len(writes) == 1
    assert writes[0]["values"][0]["key"] == "bess-01.che_do" and writes[0]["values"][0]["value"] == 1


def test_frames_filters(sim, ctl, conns):
    read(sim, conns, "dong-ho-dien-01.dien_ap")
    read(sim, conns, "bess-01.muc_pin")
    assert [f["device"] for f in ctl.frames(device="bess-01")] == ["bess-01"]
    first = ctl.frames()[0]["seq"]
    assert len(ctl.frames(since=first)) == 1
    assert ctl.frames(errors=True) == []
    assert len(ctl.frames(limit=1)) == 1


def test_clear_and_reset_empty_the_frames(sim, ctl, conns):
    read(sim, conns, "dong-ho-dien-01.dien_ap")
    ctl.clear_frames()
    assert ctl.frames() == []
    read(sim, conns, "dong-ho-dien-01.dien_ap")
    ctl.reset()
    assert ctl.frames() == []


def test_frame_summaries_translate_in_every_language(sim, ctl, conns):
    read(sim, conns, "dong-ho-dien-01.dien_ap")
    write_guarded(sim.cfg, conns, "bess-01.che_do", 1)
    for f in ctl.frames():
        assert all(t(f["fc_key"], lang) for lang in LANGS)
        for part in ("request", "response"):          # tên trường trang web hiện dưới từng nhóm byte
            assert all(t(f"frame.f.{x['name']}", lang) for x in f[part]["fields"] for lang in LANGS)
        for part in ("request", "response"):
            s = f[part]["summary"]
            for lang in LANGS:
                assert t(s["key"], lang, **s["params"])


def test_only_last_frames_are_kept():
    cfg = lab_config(5024)
    s = start(cfg, control_port=0, frames=3)
    c = Connections()
    d, p = find(cfg, "dong-ho-dien-01.dien_ap")
    for _ in range(5):
        c.read(d, p)
    c.close()
    assert [f["seq"] for f in SimControl(s.control_url).frames()] == [3, 4, 5]


def test_cli_prints_wire_bytes_and_meaning(sim, ctl, conns):
    ctl.set("dong-ho-dien-01.dien_ap", 230.5)
    read(sim, conns, "dong-ho-dien-01.dien_ap")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), SIM_URL=sim.control_url)
    r = subprocess.run([sys.executable, "tools/simulator/simctl.py", "frames"],
                       capture_output=True, text=True, timeout=10, env=env)
    assert r.returncode == 0, r.stderr
    assert "| 00 00 | 00 06 | 01 | 03 | 00 00 | 00 01" in r.stdout
    assert "| 00 00 | 00 05 | 01 | 03 | 02 | 09 01" in r.stdout
    assert "09 01 = 2305" in r.stdout and "Điện áp" in r.stdout
