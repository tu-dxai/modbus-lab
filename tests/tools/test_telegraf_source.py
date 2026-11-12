"""Kiểm thử nguồn Telegraf của collector: Telegraf thật (Docker telegraf:1.32, cùng bản demo A04) đọc Modbus /
SNMP theo cấu hình sinh từ Point Map rồi gửi về collector (POST /api/telegraf); BACnet và bus RS-485 Telegraf
không mở được vẫn do Python đọc.

Phần đầu không cần Docker (chọn thiết bị, nhận số liệu, lệnh docker). Phần tích hợp chạy Telegraf thật với
simulator riêng (cổng 5027, bus RS-485 qua TCP) và tự bỏ qua khi máy không có Docker hoặc image telegraf:1.32.
"""
import copy, json, shutil, subprocess, time, urllib.error, urllib.request
import pytest
from collector import LATEST, STATUS, serve, snapshot
from conftest import device, lab_config
from modbus_io import Connections
from point_map import serial_over_tcp
from sim import start
from simctl import SimControl
from telegraf_source import IMAGE, docker_command, handled, ingest

SAMPLE = {"metrics": [
    {"fields": {"muc_pin": 80, "nhiet_do_pin": -2}, "name": "modbus", "timestamp": 1794446742000,
     "tags": {"device": "bess-01", "site": "container-01", "slave_id": "1", "type": "input_register"}},
    {"fields": {"dien_ap_pin": 545, "tai_ra": 42}, "name": "snmp", "timestamp": 1794446743000,
     "tags": {"agent_host": "127.0.1.40", "device": "ups-01", "site": "container-01"}},
    {"fields": {"khong_co": 1}, "name": "modbus", "timestamp": 1794446742000, "tags": {"device": "bess-01"}},
    {"fields": {"x": 1}, "name": "modbus", "timestamp": 1794446742000, "tags": {"device": "thiet-bi-la"}},
]}


def call(url, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ---------- không cần Docker ----------
def test_handled_devices_are_those_telegraf_can_open(cfg):
    assert handled(cfg) == ["dong-ho-dien-01", "dong-ho-dien-02", "bess-01", "ups-01"]   # RS-485 cổng ảo: Python
    c = copy.deepcopy(cfg)
    serial_over_tcp(c, {"/dev/ttyUSB0": "127.0.1.60:7000"})                              # bus qua TCP: Telegraf
    assert "dong-ho-rs485-03" in handled(c) and "crah-01" not in handled(c)


def test_ingest_maps_metrics_to_points(cfg):
    rows = ingest(SAMPLE, cfg)
    assert set(rows) == {"bess-01.muc_pin", "bess-01.nhiet_do_pin", "ups-01.dien_ap_pin", "ups-01.tai_ra"}
    r = rows["bess-01.nhiet_do_pin"]
    assert (r["value"], r["ok"], r["source"], r["unit"]) == (-2, True, "telegraf", "°C")
    assert r["ts"] == pytest.approx(1794446742.0)


def test_ingest_accepts_single_metric_and_json_lines(cfg):
    one = SAMPLE["metrics"][0]
    assert set(ingest(one, cfg)) == {"bess-01.muc_pin", "bess-01.nhiet_do_pin"}
    lines = "\n".join(json.dumps(m) for m in SAMPLE["metrics"][:2])
    assert len(ingest(lines, cfg)) == 4


def test_docker_command(tmp_path):
    cmd = docker_command("modbus-lab-telegraf-8080", tmp_path, "http://127.0.0.1:8080/api/telegraf", 2)
    assert cmd[:2] == ["docker", "run"] and IMAGE == "telegraf:1.32" and IMAGE in cmd
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "host"
    assert "COLLECTOR_URL=http://127.0.0.1:8080/api/telegraf" in cmd and "TELEGRAF_INTERVAL=2s" in cmd


@pytest.fixture
def web(cfg):
    c = Connections()
    srv = serve(cfg, c, port=0)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    c.close()


def test_api_telegraf_updates_points(web):
    code, r = call(web + "/api/telegraf", SAMPLE)
    assert code == 200 and r["ok"] and r["points"] == 4
    assert LATEST["ups-01.tai_ra"]["source"] == "telegraf" and LATEST["ups-01.tai_ra"]["value"] == 42


@pytest.mark.parametrize("body", [{"source": "influx"}, {}, {"source": 1}])
def test_api_source_rejects_bad_request(web, body):
    code, r = call(web + "/api/source", body)
    assert code == 400 and r["code"] == "api.bad_source_request"


def test_stale_telegraf_point_is_an_error(cfg):
    LATEST["bess-01.muc_pin"] = dict(ingest(SAMPLE, cfg)["bess-01.muc_pin"], ts=time.time() - 60)
    STATUS["telegraf"] = dict(STATUS.get("telegraf") or {}, interval=2)
    row = snapshot(cfg)["points"]["bess-01.muc_pin"]
    assert not row["ok"] and row["code"] == "telegraf.stale" and row["params"]["s"] >= 59


# ---------- Telegraf thật (Docker) ----------
def _docker_ready() -> str | None:
    if not shutil.which("docker"):
        return "máy không có docker"
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return None if r.returncode == 0 else f"chưa có image {IMAGE} (docker pull {IMAGE})"


needs_docker = pytest.mark.skipif(_docker_ready() is not None, reason=_docker_ready() or "")
RS485_TCP = "127.0.1.60:5027"


@pytest.fixture(scope="module")
def tg_sim():
    cfg = lab_config(5027)
    serial_over_tcp(cfg, {"/dev/ttyUSB0": RS485_TCP})
    sim = start(cfg, control_port=0)
    return cfg, SimControl(sim.control_url)


@pytest.fixture(scope="module")
def tg_web(tg_sim):
    cfg, _ = tg_sim
    c = Connections()
    srv = serve(cfg, c, port=0)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    code, r = call(url + "/api/source", {"source": "telegraf", "interval": 1})
    assert code == 200, r
    yield url, cfg
    call(url + "/api/source", {"source": "python"})
    srv.shutdown()
    c.close()


def wait_for(url, check, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        _, s = call(url + "/api/points")
        if check(s):
            return s
        time.sleep(0.5)
    return s


@needs_docker
def test_real_telegraf_reads_every_modbus_and_snmp_point(tg_sim, tg_web):
    cfg, ctl = tg_sim
    url, _ = tg_web
    keys = [f"{n}.{p['name']}" for n in handled(cfg) for p in device(cfg, n)["points"]]
    assert "dong-ho-rs485-03.dien_ap" in keys                                       # RTU over TCP qua Telegraf
    s = wait_for(url, lambda s: all(s["points"].get(k, {}).get("source") == "telegraf" for k in keys))
    sim = ctl.get()
    for k in keys:                                                                   # byte order, số âm, hệ số
        row = s["points"][k]
        assert row["source"] == "telegraf" and row["ok"], (k, row)
        assert row["value"] == pytest.approx(sim[k]["value"], abs=0.01), k
    assert s["status"]["source"] == "telegraf" and s["status"]["telegraf"]["running"]


@needs_docker
def test_bacnet_still_read_by_python_in_telegraf_mode(tg_web):
    url, _ = tg_web
    s = wait_for(url, lambda s: s["points"].get("crah-01.nhiet_do_cap", {}).get("ok"))
    assert s["points"]["crah-01.nhiet_do_cap"]["source"] == "python"


@needs_docker
def test_value_set_on_simulator_reaches_telegraf(tg_sim, tg_web):
    _, ctl = tg_sim
    url, _ = tg_web
    ctl.set("bess-01.muc_pin", 63.5)
    s = wait_for(url, lambda s: s["points"]["bess-01.muc_pin"]["value"] == pytest.approx(63.5))
    assert s["points"]["bess-01.muc_pin"]["value"] == pytest.approx(63.5)


@needs_docker
def test_device_switched_off_goes_stale(tg_sim, tg_web):
    _, ctl = tg_sim
    url, _ = tg_web
    ctl.power("bess-01", False)
    try:
        s = wait_for(url, lambda s: s["points"]["bess-01.muc_pin"].get("code") == "telegraf.stale", timeout=15)
        assert s["points"]["bess-01.muc_pin"]["code"] == "telegraf.stale"
    finally:
        ctl.power("bess-01", True)


@needs_docker
def test_collector_killed_with_sigterm_removes_its_telegraf_container(tg_sim):
    """timeout, docker stop, systemd... dừng collector bằng SIGTERM: container Telegraf cũng phải được gỡ."""
    import os, signal, sys
    port = 8097
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), SIM_URL=tg_sim[1].url)
    p = subprocess.Popen([sys.executable, "tools/dashboard/collector.py", "--web-port", str(port),
                          "--source", "telegraf"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    name = f"modbus-lab-telegraf-{port}"
    alive = lambda: subprocess.run(["docker", "ps", "-aq", "--filter", f"name={name}"],
                                   capture_output=True, text=True).stdout.strip()
    try:
        end = time.time() + 20
        while not alive() and time.time() < end:
            time.sleep(0.5)
        assert alive(), "collector không chạy được Telegraf"
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=20)
        assert not alive()
    finally:
        p.kill()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
