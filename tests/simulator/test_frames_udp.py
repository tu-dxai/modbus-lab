"""Kiểm thử khung tin SNMP và BACnet/IP: tách trường từng byte, ghép cặp hỏi/đáp, giải nghĩa ra điểm đo,
và bắt khung tin ở cả hai phía (collector gửi đi / simulator nhận vào).

Phần phân tích dùng đúng các byte bắt được trên đường truyền giữa collector và simulator.
"""
import copy
import pytest
from bacnet_frames import parse_bacnet
from conftest import device
from frames import FrameLog
from modbus_io import Connections, ReadError, address
from snmp_frames import parse_snmp
from write import find, relinquish_guarded, write_guarded

H = bytes.fromhex


def fields(r):
    return " | ".join(f["hex"] for f in r["fields"])


def names(r):
    return [f["name"] for f in r["fields"]]


# ---------- SNMP ----------
SNMP_GET = H("30 2b 02 01 01 04 06 70 75 62 6c 69 63 a0 1e 02 04 00 fb b4 f8 02 01 00 02 01 00"
             " 30 10 30 0e 06 0a 2b 06 01 02 01 21 01 02 04 00 05 00")
SNMP_RESP = H("30 2c 02 01 01 04 06 70 75 62 6c 69 63 a2 1f 02 04 00 fb b4 f8 02 01 00 02 01 00"
              " 30 11 30 0f 06 0a 2b 06 01 02 01 21 01 02 04 00 02 01 64")
SNMP_RESP_SCALED = H("30 2d 02 01 01 04 06 70 75 62 6c 69 63 a2 20 02 04 00 fb b4 fa 02 01 00 02 01 00"
                     " 30 12 30 10 06 0a 2b 06 01 02 01 21 01 02 05 00 02 02 15 4a")
SNMP_NO_OID = H("30 2b 02 01 01 04 06 70 75 62 6c 69 63 a2 1e 02 04 00 fb b4 fc 02 01 00 02 01 00"
                " 30 10 30 0e 06 0a 2b 06 01 02 01 21 01 09 09 00 80 00")


def test_snmp_get_request_like_on_the_wire():
    r = parse_snmp(SNMP_GET, response=False)
    assert names(r) == ["message", "version", "community", "pdu", "request_id", "error_status", "error_index",
                        "varbinds", "varbind", "oid", "value"]
    assert fields(r) == ("30 2b | 02 01 01 | 04 06 70 75 62 6c 69 63 | a0 1e | 02 04 00 fb b4 f8 | 02 01 00 | "
                         "02 01 00 | 30 10 | 30 0e | 06 0a 2b 06 01 02 01 21 01 02 04 00 | 05 00")
    assert (r["protocol"], r["function"], r["transaction"]) == ("snmp", "get", 0xFBB4F8)
    assert r["ref"] == "OID 1.3.6.1.2.1.33.1.2.4.0" and not r["malformed"] and r["exception"] is None
    assert r["summary"] == {"key": "frame.sum.snmp_get", "params": {"oid": "1.3.6.1.2.1.33.1.2.4.0"}}


def test_snmp_response_value():
    r = parse_snmp(SNMP_RESP, response=True)
    assert (r["transaction"], r["value"], r["vtype"], r["vhex"]) == (0xFBB4F8, 100, "integer", "64")
    assert r["summary"]["key"] == "frame.sum.snmp_value" and r["summary"]["params"]["value"] == 100


def test_snmp_no_such_object_is_an_error():
    r = parse_snmp(SNMP_NO_OID, response=True)
    assert r["exception"] == "noSuchObject" and r["summary"]["key"] == "frame.sum.snmp_no_oid"


def test_snmp_explain_applies_scale():
    cfg_d = {"name": "ups-01", "points": [{"name": "dien_ap_pin", "oid": "1.3.6.1.2.1.33.1.2.5.0", "scale": 0.1,
                                           "unit": "V", "label": {"vi": "Điện áp pin"}}]}
    log = FrameLog({("ep", None): cfg_d})
    req = parse_snmp(SNMP_GET.replace(H("2b 06 01 02 01 21 01 02 04 00"), H("2b 06 01 02 01 21 01 02 05 00"))
                     .replace(H("00 fb b4 f8"), H("00 fb b4 fa")), response=False)
    log.add_request("ep", "site", req)
    log.add_response("ep", parse_snmp(SNMP_RESP_SCALED, response=True))
    (e,) = log.query()
    (v,) = e["values"]
    assert (v["kind"], v["hex"], v["raw"], v["value"], v["unit"]) == ("snmp", "15 4a", 5450, 545.0, "V")
    assert e["protocol"] == "snmp" and e["fc_key"] == "frame.fc.snmp_get"


@pytest.mark.parametrize("data", [SNMP_GET[:10], H("02 01 00"), SNMP_GET[:-1], b""])
def test_snmp_malformed_never_raises(data):
    r = parse_snmp(data, response=False)
    assert r["malformed"] and r["fields"] == [{"name": "raw", "hex": data.hex(" ")}]


# ---------- BACnet/IP ----------
BAC_RP = H("81 0a 00 11 01 04 02 44 00 0c 0c 00 00 00 01 19 55")
BAC_RP_ACK = H("81 0a 00 17 01 00 30 00 0c 0c 00 00 00 01 19 55 3e 44 41 90 00 00 3f")
BAC_RP_ACK_BINARY = H("81 0a 00 14 01 00 30 01 0c 0c 00 c0 00 01 19 55 3e 91 01 3f")
BAC_WP = H("81 0a 00 1a 01 04 02 44 03 0f 0c 00 80 00 01 19 55 3e 44 41 ac 00 00 3f 49 08")
BAC_WP_NULL = H("81 0a 00 16 01 04 02 44 06 0f 0c 00 80 00 01 19 55 3e 00 3f 49 08")
BAC_ACK = H("81 0a 00 09 01 00 20 03 0f")
BAC_DENIED = H("81 0a 00 0d 01 00 50 0f 0f 91 02 91 28")
BAC_UNKNOWN = H("81 0a 00 0d 01 00 50 10 0c 91 01 91 1f")


def test_bacnet_read_property_like_on_the_wire():
    r = parse_bacnet(BAC_RP, response=False)
    assert names(r) == ["bvlc_type", "bvlc_function", "bvlc_length", "npdu_version", "npdu_control",
                        "apdu_type", "max_apdu", "invoke_id", "service", "object", "property"]
    assert fields(r) == "81 | 0a | 00 11 | 01 | 04 | 02 | 44 | 00 | 0c | 0c 00 00 00 01 | 19 55"
    assert (r["protocol"], r["function"], r["transaction"], r["ref"]) == ("bacnet", "read-property", 0, "analog-input,1")
    assert r["summary"] == {"key": "frame.sum.bacnet_read",
                            "params": {"object": "analog-input,1", "property": "present-value"}}


def test_bacnet_read_ack_real_and_binary():
    r = parse_bacnet(BAC_RP_ACK, response=True)
    assert names(r)[-3:] == ["open_tag", "value", "close_tag"]
    assert (r["transaction"], r["value"], r["vtype"], r["vhex"]) == (0, 18.0, "REAL", "41 90 00 00")
    b = parse_bacnet(BAC_RP_ACK_BINARY, response=True)
    assert (b["ref"], b["value"], b["vtype"]) == ("binary-input,1", 1, "ENUMERATED")
    assert b["summary"]["params"]["value"] == "active"


def test_bacnet_write_with_priority_and_relinquish():
    w = parse_bacnet(BAC_WP, response=False)
    assert names(w)[-1] == "priority" and w["function"] == "write-property"
    assert w["write"] == {"value": 21.5, "priority": 8} and w["summary"]["key"] == "frame.sum.bacnet_write"
    n = parse_bacnet(BAC_WP_NULL, response=False)
    assert n["write"] == {"value": None, "priority": 8} and n["summary"]["key"] == "frame.sum.bacnet_relinquish"
    a = parse_bacnet(BAC_ACK, response=True)
    assert (a["transaction"], a["exception"], a["summary"]["key"]) == (3, None, "frame.sum.bacnet_ack")


@pytest.mark.parametrize("data,exc", [(BAC_DENIED, "property: write-access-denied"),
                                      (BAC_UNKNOWN, "object: unknown-object")])
def test_bacnet_error_pdu(data, exc):
    r = parse_bacnet(data, response=True)
    assert r["exception"] == exc and names(r)[-2:] == ["error_class", "error_code"]
    assert r["summary"]["key"] == "frame.sum.bacnet_error"


@pytest.mark.parametrize("data", [BAC_RP[:7], H("81 0a 00 20") + BAC_RP[4:], H("82") + BAC_RP[1:], b""])
def test_bacnet_malformed_never_raises(data):
    r = parse_bacnet(data, response=False)
    assert r["malformed"] and r["fields"] == [{"name": "raw", "hex": data.hex(" ")}]


# ---------- bắt khung tin thật: collector (client) ----------
@pytest.fixture
def traced(cfg):
    log = FrameLog({(address(d), d.get("device_id")): d for d in cfg["devices"]})
    c = Connections()
    c.trace(log)
    yield c, log
    c.close()


def test_collector_records_snmp_read(cfg, traced):
    c, log = traced
    d, p = find(cfg, "ups-01.muc_pin")
    assert c.read(d, p) == 100
    (e,) = log.query(device="ups-01")
    assert e["function"] == "get" and e["site_endpoint"] == "10.20.0.40:161"
    assert e["values"][0]["key"] == "ups-01.muc_pin" and e["values"][0]["value"] == 100


def test_collector_records_bacnet_write_and_relinquish(cfg, traced):
    c, log = traced
    write_guarded(cfg, c, "crah-01.diem_dat_nhiet", 21.5)
    relinquish_guarded(cfg, c, "crah-01.diem_dat_nhiet")
    writes = log.query(device="crah-01", function="write-property")
    assert [e["request"]["write"] for e in writes] == [{"value": 21.5, "priority": 8}, {"value": None, "priority": 8}]
    assert all(e["response"]["summary"]["key"] == "frame.sum.bacnet_ack" for e in writes)
    reads = log.query(device="crah-01", function="read-property")
    assert reads and all(e["values"] for e in reads)


def test_collector_records_bacnet_error(cfg, traced):
    c, log = traced
    d, p = find(cfg, "crah-01.nhiet_do_cap")
    with pytest.raises(Exception):
        c.read(d, dict(p, object="analog-input,99"))
    (e,) = log.query(errors=True)
    assert e["exception"] == "object: unknown-object"


def test_collector_records_snmp_timeout(cfg, traced):
    c, log = traced
    d = copy.deepcopy(device(cfg, "ups-01"))
    d.update(port=5999, timeout=0.3)                     # không có agent nào ở cổng này
    with pytest.raises(ReadError):
        c.read(d, d["points"][0])
    (e,) = log.query(errors=True)
    assert e["status"]["key"] == "frame.status.timeout" and e["request"]["function"] == "get" and e["response"] is None


# ---------- bắt khung tin thật: simulator (thiết bị) ----------
def test_simulator_records_snmp_and_bacnet(cfg, conns, sim_ctl):
    sim_ctl.clear_frames()
    for key in ("ups-01.tai_ra", "crah-01.nhiet_do_hoi"):
        conns.read(*find(cfg, key))
    snmp = sim_ctl.frames(device="ups-01")
    bac = sim_ctl.frames(device="crah-01")
    assert [e["function"] for e in snmp] == ["get"] and snmp[0]["values"][0]["key"] == "ups-01.tai_ra"
    assert [e["function"] for e in bac] == ["read-property"] and bac[0]["values"][0]["key"] == "crah-01.nhiet_do_hoi"
