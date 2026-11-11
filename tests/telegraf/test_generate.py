"""Kiểm thử bộ sinh cấu hình Telegraf từ Point Map (edge/collectors/telegraf/generate.py).

Không chạy Telegraf thật: kiểm cấu hình đúng cú pháp TOML và khớp từng điểm trong Point Map.
"""
import copy, subprocess, sys, os, tomllib
import pytest
from generate import TelegrafError, generate
from point_map import read

PATH = "edge/point-map/devices.yml"


def conf(env="site", cfg=None):
    return tomllib.loads(generate(cfg or read(PATH, env=env)))


def modbus_inputs(c):
    return {i["controller"]: i for i in c["inputs"]["modbus"]}


def request(inp, device, register):
    return next(r for r in inp["request"] if r["tags"]["device"] == device and r["register"] == register)


def test_output_is_valid_toml_with_header():
    text = generate(read(PATH, env="site"))
    assert text.startswith("#") and "SINH TỰ ĐỘNG" in text
    tomllib.loads(text)


def test_one_modbus_input_per_address():
    inputs = modbus_inputs(conf())
    assert set(inputs) == {"tcp://10.20.0.21:502", "tcp://10.20.0.30:502",      # gateway điện: một kết nối
                           "file:///dev/ttyUSB0"}                               # bus RS-485: một cổng
    gw = inputs["tcp://10.20.0.21:502"]
    assert gw["configuration_type"] == "request" and gw["timeout"] == "3s"
    assert {r["slave_id"] for r in gw["request"]} == {1, 2}


def test_fields_match_point_map():
    gw = modbus_inputs(conf())["tcp://10.20.0.21:502"]
    r = request(gw, "dong-ho-dien-01", "holding")
    assert r["byte_order"] == "ABCD" and r["tags"]["site"] == "container-01"
    fields = {f["name"]: f for f in r["fields"]}
    assert fields["dien_ap"] == {"address": 0, "name": "dien_ap", "type": "UINT16", "scale": 0.1}
    assert fields["cong_suat"]["type"] == "FLOAT32" and fields["cong_suat"]["address"] == 2
    assert fields["nhiet_do_tu"]["type"] == "INT16"


def test_holding_and_input_are_separate_requests():
    bess = modbus_inputs(conf())["tcp://10.20.0.30:502"]
    assert request(bess, "bess-01", "input")["byte_order"] == "CDAB"
    assert [f["name"] for f in request(bess, "bess-01", "input")["fields"]] == ["muc_pin", "nhiet_do_pin"]
    assert [f["name"] for f in request(bess, "bess-01", "holding")["fields"]] == ["che_do"]


def test_lab_environment_points_at_simulator():
    assert set(modbus_inputs(conf("lab"))) == {"tcp://127.0.1.21:5020", "tcp://127.0.1.30:5020",
                                               "file://var/serial/ttyUSB0"}


def test_every_point_appears_exactly_once():
    cfg = read(PATH, env="site")
    names = [(r["tags"]["device"], f["name"]) for i in conf()["inputs"]["modbus"] for r in i["request"] for f in r["fields"]]
    expected = [(d["name"], p["name"]) for d in cfg["devices"] if d.get("protocol", "modbus") == "modbus"
                for p in d["points"]]
    assert sorted(names) == sorted(expected)


def test_inputs_only_leaves_agent_and_outputs_to_the_edge():
    """Edge thật có [agent] và output MQTT riêng; file thiết bị ghép vào chỉ được chứa inputs."""
    cfg = read(PATH, env="site")
    c = tomllib.loads(generate(cfg, inputs_only=True))
    assert set(c) == {"inputs"}
    assert c["inputs"] == conf(cfg=cfg)["inputs"]


def test_unsupported_scale_type_is_an_error():
    cfg = read(PATH, env="site")
    cfg["devices"][0]["points"][0]["type"] = "bitfield"
    with pytest.raises(TelegrafError) as e:
        generate(cfg)
    assert "dong-ho-dien-01.dien_ap" in str(e.value)


def test_cli_writes_file(tmp_path):
    out = tmp_path / "telegraf.conf"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    r = subprocess.run([sys.executable, "edge/collectors/telegraf/generate.py", "--env", "site", "--out", str(out)],
                       capture_output=True, text=True, timeout=20, env=env)
    assert r.returncode == 0, r.stderr
    assert "tcp://10.20.0.21:502" in out.read_text(encoding="utf-8")
