"""Kiểm thử trang xem số liệu (tools/dashboard): API đọc và ghi qua rào chắn.

Không phải bài nghiệm thu MB-xx; chạy cùng simulator ở tests/conftest.py.
"""
import json, urllib.error, urllib.request
import pytest
from collector import poll_once, serve
from modbus_io import Connections


@pytest.fixture(scope="module")
def web(cfg):
    c = Connections()
    poll_once(c, cfg)
    srv = serve(cfg, c, port=0)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    c.close()


def call(url, data=None):
    """GET (data=None) hoặc POST JSON; trả về (mã HTTP, nội dung)."""
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            raw = r.read()
            return r.status, json.loads(raw) if "json" in r.headers["Content-Type"] else raw.decode()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_web_index_page(web):
    code, html = call(web + "/")
    assert code == 200 and "<title>Modbus lab</title>" in html


@pytest.mark.parametrize("path", ["/?lang=ja", "/?lang=vi", "/api/points?lang=ja"])
def test_web_accepts_query_string(web, path):
    code, _ = call(web + path)
    assert code == 200


def test_web_api_points(cfg, web):
    code, s = call(web + "/api/points")
    assert code == 200
    keys = [p["key"] for d in s["devices"] for p in d["points"]]
    assert keys == [f"{d['name']}.{p['name']}" for d in cfg["devices"] for p in d["points"]]
    assert s["points"]["bess-01.muc_pin"]["value"] == pytest.approx(80.0)
    assert s["history"]["bess-01.muc_pin"] and s["status"]["round"] >= 1
    assert len(s["alert_rules"]) == len(cfg["alerts"])
    bess = next(d for d in s["devices"] if d["name"] == "bess-01")
    assert bess["site_endpoint"] == "10.20.0.30:502" and s["env"] == "lab"


def test_web_valid_write_and_readback(web):
    code, r = call(web + "/api/write", {"point": "bess-01.che_do", "value": 1})
    assert code == 200 and r["ok"] and r["after"] == 1
    call(web + "/api/write", {"point": "bess-01.che_do", "value": r["before"]})   # trả lại như cũ


@pytest.mark.parametrize("key,value", [
    ("bess-01.che_do", 5),                    # giá trị ngoài danh sách cho phép
    ("dong-ho-dien-01.dien_ap", 999),         # điểm chỉ đọc
])
def test_web_guard_rejects(web, key, value):
    code, r = call(web + "/api/write", {"point": key, "value": value})
    assert code == 403 and r["blocked"] and not r["ok"]
    assert r["code"].startswith("write.") and r["error"]          # trang dịch theo code, dòng lệnh dùng error


def test_web_blocked_write_returns_code_and_params(web):
    code, r = call(web + "/api/write", {"point": "bess-01.che_do", "value": 5})
    assert r["code"] == "write.not_allowed" and r["params"] == {"value": 5.0, "allowed": [0, 1]}


def test_web_malformed_request(web):
    code, r = call(web + "/api/write", {"diem": "x"})
    assert code == 400 and not r["ok"] and r["code"] == "api.bad_write_request"


def test_web_serves_dictionary(web):
    code, d = call(web + "/i18n.json")
    assert code == 200 and set(d) == {"vi", "ja"}
    assert d["ja"]["write.not_allowed"] and d["vi"]["write.not_allowed"]
    req = urllib.request.urlopen(web + "/i18n.js", timeout=3)
    assert "function initI18n" in req.read().decode() and "javascript" in req.headers["Content-Type"]


def test_web_points_carry_bilingual_labels(web):
    _, s = call(web + "/api/points")
    bess = next(d for d in s["devices"] if d["name"] == "bess-01")
    assert set(bess["label"]) == {"vi", "ja"}
    assert all(set(p["label"]) == {"vi", "ja"} for p in bess["points"])
    assert all(set(a["message"]) == {"vi", "ja"} for a in s["alert_rules"])
