"""Kiểm thử cấu trúc mạng: mỗi địa chỉ host:port một server, nhiều thiết bị sau một gateway.

Dùng simulator chung ở tests/conftest.py (môi trường lab, cổng 5021):
  gateway điện 127.0.1.21 — dong-ho-dien-01 (device_id 1), dong-ho-dien-02 (device_id 2)
  bess-01      127.0.1.30 — device_id 1
"""
import copy
import pytest
from pymodbus.client import ModbusTcpClient
from collector import LATEST, poll_once
from conftest import device
from modbus_io import Connections
from write import find


def test_gateway_serves_two_devices_by_device_id(cfg, conns):
    for key, expected in (("dong-ho-dien-01.dien_ap", 230.0), ("dong-ho-dien-02.dien_ap", 229.0)):
        d, p = find(cfg, key)
        assert conns.read(d, p) == pytest.approx(expected)


def test_same_device_id_on_another_address_is_another_device(cfg, conns):
    meter, bess = device(cfg, "dong-ho-dien-01"), device(cfg, "bess-01")
    assert meter["device_id"] == bess["device_id"] == 1
    assert (meter["host"], meter["port"]) != (bess["host"], bess["port"])
    r = conns.client(bess).read_holding_registers(0, count=1, device_id=1)   # ô của đồng hồ, hỏi nhầm sang BESS
    assert r.isError() and r.exception_code == 2


def test_devices_behind_gateway_share_one_connection(cfg, conns):
    d1, d2, bess = (device(cfg, n) for n in ("dong-ho-dien-01", "dong-ho-dien-02", "bess-01"))
    assert conns.client(d1) is conns.client(d2)
    assert conns.client(d1) is not conns.client(bess)
    assert len(conns.clients) == 2


def test_each_address_is_its_own_server(cfg):
    c = ModbusTcpClient("127.0.0.1", port=cfg["devices"][0]["port"], timeout=0.5, retries=0)
    assert not c.connect()                     # không có "một server chung" ở 127.0.0.1
    c.close()


def test_one_address_down_does_not_affect_others(cfg):
    broken = copy.deepcopy(cfg)
    for d in broken["devices"]:
        if d["name"].startswith("dong-ho-dien"):
            d.update(port=5999, timeout=0.5)   # gateway điện mất kết nối
    poll_once(Connections(), broken)
    assert all(not r["ok"] and "127.0.1.21:5999" in r["error"] and r["code"] == "read.unreachable"
               for k, r in LATEST.items() if k.startswith("dong-ho-dien"))
    assert all(r["ok"] for k, r in LATEST.items() if k.startswith("bess-01"))


def test_startup_banner_lists_every_protocol():
    """Dòng chữ khi `make sim` khởi động: đủ mọi thiết bị, kể cả RTU / SNMP / BACnet (không có device_id)."""
    from point_map import read
    from sim import banner
    cfg = read("edge/point-map/devices.yml", env="lab")
    text = "\n".join(banner(cfg))
    for d in cfg["devices"]:
        assert d["name"] in text
        for p in d["points"]:
            assert p["name"] in text
    for word in ("Modbus TCP", "Modbus RTU", "SNMP", "BACnet/IP", "OID 1.3.6.1.2.1.33", "analog-value,1"):
        assert word in text
