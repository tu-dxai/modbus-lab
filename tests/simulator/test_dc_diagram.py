"""Kiểm thử mô hình sơ đồ DC (tools/simulator/topology.py) và API /api/topology của simulator.

Tab "Sơ đồ kiến trúc": thiết bị nhóm theo hệ thống (EPMS, BMS) -> kết nối -> Edge Site Stack -> trung tâm.
Tab "Sơ đồ đơn tuyến": nút điện theo Point Map mục topology (giả định), kèm làm mát.
Mọi thứ về thiết bị lấy từ Point Map; phần mềm (edge, MQTT, DCIM, ITSM) mô tả trong topology.py kèm trạng thái.
"""
import json, urllib.request
import pytest
from topology import STATUSES, build


@pytest.fixture(scope="module")
def model(cfg):
    return build(cfg)


def ids(items):
    return [x["id"] for x in items]


def test_devices_grouped_by_system(model):
    systems = {s["id"]: s["devices"] for s in model["systems"]}
    assert systems == {"EPMS": ["dong-ho-dien-01", "dong-ho-dien-02", "dong-ho-rs485-03", "bess-01", "ups-01"],
                       "BMS": ["crah-01"]}


def test_links_follow_how_devices_are_connected(model):
    kinds = {l["kind"]: l["devices"] for l in model["links"]}
    assert kinds == {"gateway": ["dong-ho-dien-01", "dong-ho-dien-02"], "rtu": ["dong-ho-rs485-03"],
                     "direct": ["bess-01"], "snmp": ["ups-01"], "bacnet": ["crah-01"]}
    gw = next(l for l in model["links"] if l["kind"] == "gateway")
    assert gw["site_endpoint"] == "10.20.0.21:502"


def test_links_feed_the_edge_component_that_reads_them(model):
    to = {l["kind"]: l["to"] for l in model["links"]}
    assert to == {"gateway": "telegraf", "rtu": "telegraf", "direct": "telegraf", "snmp": "telegraf",
                  "bacnet": "bacnet-collector"}
    assert set(to.values()) <= set(ids(model["edge"]))


def test_software_parts_carry_status(model):
    parts = model["edge"] + model["center"]
    assert all(p["status"] in STATUSES for p in parts)
    status = {p["id"]: p["status"] for p in parts}
    assert status["bacnet-collector"] == "ready" and status["write-service"] == "ready"
    assert status["telegraf"] == "ready"                         # Telegraf 1.32 thật đọc simulator (nguồn Telegraf)
    assert status["mqtt"] == status["dcim"] == status["itsm"] == "planned"


def test_flows_only_reference_known_parts(model):
    known = set(ids(model["edge"]) + ids(model["center"]))
    assert model["flows"] and all(f["from"] in known and f["to"] in known for f in model["flows"])


def test_power_nodes_take_device_labels_and_points(model):
    nodes = {n["id"]: n for n in model["power"]}
    assert nodes["ups-01"]["label"]["vi"] == "UPS 01"            # nút gắn thiết bị: lấy nhãn của thiết bị
    assert nodes["tu-chinh"]["meters"] == ["dong-ho-dien-01"] and nodes["luoi"]["parent"] is None
    assert nodes["tu-rack"]["parent"] == "ups-01" and nodes["day-rack"]["depth"] == 4
    assert model["assumed"] is True
    assert model["cooling"] == [{"device": "crah-01", "serves": "day-rack"}]


def test_power_nodes_list_points_to_show(model):
    nodes = {n["id"]: n for n in model["power"]}
    assert nodes["ups-01"]["show"] == ["ups-01.tai_ra", "ups-01.nguon_ra"]        # chọn trong Point Map
    assert nodes["tu-rack"]["show"] == ["dong-ho-dien-02.cong_suat"]


def test_api_topology(sim_ctl):
    with urllib.request.urlopen(sim_ctl.url + "/api/topology", timeout=3) as r:
        body = json.loads(r.read())
    assert body["site"] == "container-01" and {s["id"] for s in body["systems"]} == {"EPMS", "BMS"}
    with urllib.request.urlopen(sim_ctl.url + "/diagram.js", timeout=3) as r:
        assert "renderArchitecture" in r.read().decode()
