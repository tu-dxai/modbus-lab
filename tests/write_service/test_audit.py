"""Kiểm thử nhật ký kiểm toán lệnh ghi (edge/write-service/audit.py).

Mọi lệnh ghi đi qua rào chắn đều để lại một dòng: đã ghi, bị rào chắn chặn, hay bị thiết bị từ chối.
"""
import copy, json, urllib.error, urllib.request
import pytest
from audit import AuditLog
from collector import serve
from modbus_io import Connections
from write import WriteBlocked, WriteFailed, find, write_guarded


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit" / "writes.jsonl")


def test_successful_write_is_audited(cfg, conns, log):
    write_guarded(cfg, conns, "bess-01.che_do", 1, audit=log, actor="cli:tester")
    write_guarded(cfg, conns, "bess-01.che_do", 0, audit=log, actor="cli:tester")
    first = log.tail()[0]
    assert first["outcome"] == "written" and first["actor"] == "cli:tester"
    assert first["point"] == "bess-01.che_do" and first["device"] == "bess-01"
    assert first["site_endpoint"] == "10.20.0.30:502" and first["env"] == "lab"
    assert (first["value"], first["before"], first["after"]) == (1, 0, 1)
    assert first["at"] and first["code"] is None


@pytest.mark.parametrize("key,value,code", [
    ("bess-01.che_do", 5, "write.not_allowed"),
    ("dong-ho-dien-01.dien_ap", 999, "write.not_writable"),
    ("khong-co.diem_nao", 1, "write.unknown_point"),
])
def test_blocked_write_is_audited(cfg, conns, log, key, value, code):
    with pytest.raises(WriteBlocked):
        write_guarded(cfg, conns, key, value, audit=log, actor="cli:tester")
    (e,) = log.tail()
    assert e["outcome"] == "blocked" and e["code"] == code and e["point"] == key and e["error"]
    assert e["before"] is None and e["after"] is None


def test_device_rejection_is_audited(cfg, conns, log):
    c = copy.deepcopy(cfg)
    _, p = find(c, "dong-ho-dien-01.dien_ap")
    p.update(writable=True, min=0, max=300)              # Point Map cho ghi, nhưng thiết bị coi ô này chỉ đọc
    with pytest.raises(WriteFailed):
        write_guarded(c, conns, "dong-ho-dien-01.dien_ap", 231, audit=log, actor="cli:tester")
    (e,) = log.tail()
    assert e["outcome"] == "failed" and e["code"] == "write.device_rejected"
    assert e["before"] == pytest.approx(230.0)


def test_log_is_append_only_across_restarts(cfg, conns, tmp_path):
    path = tmp_path / "writes.jsonl"
    for actor in ("a", "b"):
        with pytest.raises(WriteBlocked):
            write_guarded(cfg, conns, "bess-01.che_do", 5, audit=AuditLog(path), actor=actor)
    assert [e["actor"] for e in AuditLog(path).tail()] == ["a", "b"]
    assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def test_tail_limits_entries(cfg, conns, log):
    for _ in range(3):
        with pytest.raises(WriteBlocked):
            write_guarded(cfg, conns, "bess-01.che_do", 5, audit=log, actor="x")
    assert len(log.tail(2)) == 2


def test_web_write_is_audited_with_client_address(cfg, tmp_path):
    log = AuditLog(tmp_path / "w.jsonl")
    c = Connections()
    srv = serve(cfg, c, port=0, audit=log)
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/write"
    for value in (1, 0):
        req = urllib.request.Request(url, data=json.dumps({"point": "bess-01.che_do", "value": value}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    srv.shutdown()
    c.close()
    entries = log.tail()
    assert [e["outcome"] for e in entries] == ["written", "written"]
    assert all(e["actor"] == "web:127.0.0.1" for e in entries)
