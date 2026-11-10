"""Kiểm thử SNMP: Point Map, agent SNMP của simulator (đọc bằng SNMP GET thật), collector, Telegraf.

Thiết bị mẫu ups-01 dùng OID chuẩn UPS-MIB (RFC 1628). Simulator chung ở tests/conftest.py.
"""
import asyncio, copy, tomllib
import pytest
from pysnmp.hlapi.v3arch.asyncio import (CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine,
                                          UdpTransportTarget, get_cmd)
from collector import LATEST, poll_once
from conftest import device
from generate import generate
from modbus_io import Connections
from point_map import read, validate
from write import WriteBlocked, find, write_guarded

UPS = "ups-01"
PATH = "edge/point-map/devices.yml"
CHARGE = "1.3.6.1.2.1.33.1.2.4.0"            # upsEstimatedChargeRemaining (%)
BATT_V = "1.3.6.1.2.1.33.1.2.5.0"            # upsBatteryVoltage (0,1 V DC)


def snmp_get(d, oid, community="public"):
    async def go():
        target = await UdpTransportTarget.create((d["host"], d["port"]), timeout=1, retries=0)
        err, status, _, vbs = await get_cmd(SnmpEngine(), CommunityData(community, mpModel=1), target, ContextData(),
                                            ObjectType(ObjectIdentity(oid)))
        return err, status, vbs
    return asyncio.run(go())


# ---------- Point Map ----------
def test_ups_in_point_map():
    d = device(read(PATH, env="site"), UPS)
    assert d["protocol"] == "snmp" and (d["host"], d["port"]) == ("10.20.0.40", 161)
    assert next(p for p in d["points"] if p["name"] == "muc_pin")["oid"] == CHARGE


@pytest.mark.parametrize("change,word", [
    ({"oid": "1.3.6.x"}, "oid"), ({"type": "float32"}, "type"), ({"writable": True, "min": 0, "max": 1}, "writable"),
])
def test_bad_snmp_point(change, word):
    cfg = read(PATH, env="site")
    next(p for p in device(cfg, UPS)["points"] if p["name"] == "muc_pin").update(change)
    errors = validate(cfg)
    assert len(errors) == 1 and f"{UPS}.muc_pin" in errors[0] and word in errors[0]


def test_duplicate_oid():
    cfg = read(PATH, env="site")
    pts = device(cfg, UPS)["points"]
    pts[1]["oid"] = pts[0]["oid"]
    (e,) = validate(cfg)
    assert UPS in e and pts[0]["oid"] in e


def test_bad_snmp_version():
    cfg = read(PATH, env="site")
    device(cfg, UPS)["snmp"]["version"] = "3"
    (e,) = validate(cfg)
    assert UPS in e and "version" in e


# ---------- agent SNMP của simulator ----------
def test_snmp_get_from_simulator(cfg):
    err, status, vbs = snmp_get(device(cfg, UPS), CHARGE)
    assert err is None and int(status) == 0 and int(vbs[0][1]) == 100


def test_scaled_value_is_stored_as_integer(cfg):
    _, _, vbs = snmp_get(device(cfg, UPS), BATT_V)
    assert int(vbs[0][1]) == 5450                     # 545,0 V lưu theo đơn vị 0,1 V


def test_unknown_oid(cfg):
    _, _, vbs = snmp_get(device(cfg, UPS), "1.3.6.1.2.1.33.1.9.9.0")
    assert "No Such" in vbs[0][1].prettyPrint()


def test_wrong_community_gets_no_answer(cfg):
    err, _, _ = snmp_get(device(cfg, UPS), CHARGE, community="sai")
    assert err is not None and "timeout" in str(err).lower()


# ---------- collector ----------
def test_collector_reads_snmp(cfg, conns):
    d, p = find(cfg, f"{UPS}.dien_ap_pin")
    assert conns.read(d, p) == pytest.approx(545.0)


def test_poll_reads_whole_ups(cfg):
    c = Connections()
    poll_once(c, cfg, device=UPS)
    c.close()
    ups = {k: r for k, r in LATEST.items() if k.startswith(UPS + ".")}
    assert len(ups) == len(device(cfg, UPS)["points"]) and all(r["ok"] for r in ups.values())


def test_snmp_points_are_read_only(cfg, conns):
    with pytest.raises(WriteBlocked):
        write_guarded(cfg, conns, f"{UPS}.muc_pin", 50)


# ---------- Telegraf ----------
def test_telegraf_snmp_input():
    conf = tomllib.loads(generate(read(PATH, env="site")))
    (snmp,) = conf["inputs"]["snmp"]
    assert snmp["agents"] == ["udp://10.20.0.40:161"] and snmp["version"] == 2 and snmp["tags"]["device"] == UPS
    fields = {f["name"]: f for f in snmp["field"]}
    assert fields["muc_pin"]["oid"] == CHARGE and "conversion" not in fields["muc_pin"]
    assert fields["dien_ap_pin"]["conversion"] == "float(1)"
