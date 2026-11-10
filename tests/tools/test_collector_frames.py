"""Kiểm thử khung tin phía client (collector): byte collector gửi đi và nhận về, kể cả sự cố.

Phía client thấy được điều simulator không thấy: yêu cầu không có phản hồi (timeout)
và địa chỉ không kết nối được.
"""
import copy, json, socket, threading, time, urllib.error, urllib.request
import pytest
from collector import poll_once, serve
from frames import FrameLog
from modbus_io import Connections, address


def call(url, data=None, method=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read()
            return r.status, json.loads(raw) if "json" in r.headers["Content-Type"] else raw.decode()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def fields(part):
    return " | ".join(f["hex"] for f in part["fields"])


@pytest.fixture(scope="module")
def web(cfg):
    c = Connections()
    srv = serve(cfg, c, port=0)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    c.close()


@pytest.fixture
def frames_url(web):
    call(web + "/api/frames", method="DELETE")
    return web + "/api/frames"


def test_read_is_captured_on_the_client_side(web, frames_url):
    call(web + "/api/read", {"point": "dong-ho-dien-01.dien_ap"})
    _, r = call(frames_url)
    (f,) = r["frames"]
    assert fields(f["request"]).endswith("| 00 00 | 00 06 | 01 | 03 | 00 00 | 00 01")
    assert fields(f["response"]).endswith("| 00 00 | 00 05 | 01 | 03 | 02 | 08 fc")    # 2300 = 230,0 V
    assert f["device"] == "dong-ho-dien-01" and f["site_endpoint"] == "10.20.0.21:502"
    assert f["values"][0]["value"] == pytest.approx(230.0) and f["status"] is None and f["ms"] >= 0


def test_read_all_gives_one_pair_per_point(cfg, web, frames_url):
    call(web + "/api/read", {})
    _, r = call(frames_url)
    modbus = [d for d in cfg["devices"] if d.get("protocol", "modbus") == "modbus"]   # khung tin chỉ bắt Modbus
    assert len(r["frames"]) == sum(len(d["points"]) for d in modbus)
    assert [f["seq"] for f in r["frames"]] == sorted(f["seq"] for f in r["frames"])


def test_write_is_captured_with_readback(web, frames_url):
    call(web + "/api/write", {"point": "bess-01.che_do", "value": 1})
    call(web + "/api/write", {"point": "bess-01.che_do", "value": 0})
    _, r = call(frames_url + "?function=16")
    assert [f["values"][0]["value"] for f in r["frames"]] == [1, 0]


def test_frames_filters_and_clear(web, frames_url):
    call(web + "/api/read", {})
    _, r = call(frames_url + "?device=bess-01")
    assert r["frames"] and {f["device"] for f in r["frames"]} == {"bess-01"}
    _, r = call(frames_url + "?limit=2")
    assert len(r["frames"]) == 2
    code, _ = call(frames_url, method="DELETE")
    _, r = call(frames_url)
    assert code == 200 and r["frames"] == []


def test_bad_frames_query(web):
    code, r = call(web + "/api/frames?since=x")
    assert code == 400 and r["code"] == "api.bad_frames_query"


def log_for(cfg):
    return FrameLog({(address(d), d.get("device_id")): d for d in cfg["devices"]})


def test_silent_device_is_recorded_as_timeout(cfg):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]

    def silent():                                    # nhận kết nối, đọc yêu cầu, không bao giờ trả lời
        conn, _ = srv.accept()
        conn.recv(100)
        time.sleep(2)
        conn.close()
    threading.Thread(target=silent, daemon=True).start()

    one = copy.deepcopy(cfg)
    d = next(x for x in one["devices"] if x["name"] == "bess-01")
    d.update(host="127.0.0.1", port=port, timeout=0.3)
    one["devices"] = [d]
    log = log_for(one)
    poll_once(Connections(frames=log), one, point="bess-01.muc_pin")
    (f,) = log.query()
    assert fields(f["request"]).endswith("| 00 00 | 00 06 | 01 | 04 | 00 64 | 00 02")
    assert f["response"] is None and f["status"]["key"] == "frame.status.timeout"
    assert f["device"] == "bess-01" and f["ms"] >= 250
    srv.close()


def test_unreachable_address_is_recorded(cfg):
    one = copy.deepcopy(cfg)
    one["devices"] = [d for d in one["devices"] if d["name"] == "bess-01"]
    one["devices"][0].update(port=5999, timeout=0.3)
    log = log_for(one)
    poll_once(Connections(frames=log), one)
    (f,) = log.query()                               # một mục cho cả thiết bị, không lặp theo từng điểm
    assert f["request"] is None and f["response"] is None
    assert f["status"]["key"] == "read.unreachable" and f["device"] == "bess-01"


def test_collector_page_has_frames_and_simulator_page_does_not(web, cfg):
    _, html = call(web + "/")
    assert 'id="frames"' in html
    from pathlib import Path
    sim_page = Path("tools/simulator/control.html").read_text(encoding="utf-8")
    assert 'id="frames"' not in sim_page
    assert 'id="writes"' not in sim_page          # lệnh ghi xem ở khung tin collector (FC06/FC16), API vẫn giữ
