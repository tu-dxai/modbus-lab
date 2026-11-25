"""Kiểm thử rào chắn ghi (edge/write-service/write.py): giá trị phải lưu đúng được vào thiết bị, đọc lại so với
đúng giá trị thiết bị lưu, nhật ký kiểm toán không bao giờ mất vết, và BACnet nhả lệnh khi ghi không xác nhận được.

Chỉ chạy với simulator chung của bộ kiểm thử (tests/conftest.py).
"""
import copy, json, urllib.error, urllib.request
import pytest
from audit import AuditLog
from bacnet_io import relinquish_bacnet, write_bacnet
from codec import decode, encode
from collector import serve
from modbus_io import Connections
from write import (AuditFailed, WriteBlocked, WriteFailed, find, relinquish_guarded, stored_value,
                   write_guarded)

SETPOINT = "crah-01.diem_dat_nhiet"                      # BACnet analog-value, priority 8, min 16 max 27


def _writable_copy(cfg, key, **limits):
    """Bản sao Point Map cho phép ghi một điểm (chỉ dùng cho kiểm tra bị chặn trước khi gửi)."""
    c = copy.deepcopy(cfg)
    _, p = find(c, key)
    p.pop("allowed", None)
    p.update(writable=True, **limits)
    return c


# ---------- giá trị phải lưu đúng được ----------
def test_value_finer_than_scale_is_blocked_before_sending(cfg, conns, sim_ctl):
    c = _writable_copy(cfg, "dong-ho-dien-01.nhiet_do_tu", min=-40, max=80)     # int16, scale 0.1
    mark = sim_ctl.last_seq()
    with pytest.raises(WriteBlocked) as e:
        write_guarded(c, conns, "dong-ho-dien-01.nhiet_do_tu", 21.35)
    assert e.value.code == "write.not_representable" and e.value.params["step"] == 0.1
    assert sim_ctl.writes(since=mark) == []               # không gửi gì tới thiết bị


def test_fraction_on_integer_point_is_blocked(cfg, conns, sim_ctl):
    c = _writable_copy(cfg, "bess-01.che_do", min=0, max=100)                   # uint16, scale 1
    mark = sim_ctl.last_seq()
    with pytest.raises(WriteBlocked) as e:
        write_guarded(c, conns, "bess-01.che_do", 50.4)
    assert e.value.code == "write.not_representable"
    assert sim_ctl.writes(since=mark) == []


def test_every_multiple_of_scale_reads_back_equal():
    """Trước đây so `đọc lại != giá trị yêu cầu`: 409/1200 giá trị int16 x0.1 trong -40..80 bị báo thất bại sai
    (ví dụ -39.9 đọc lại -39.900000000000006). Giờ đích so sánh là đúng số thiết bị lưu, đọc lại bằng hệt."""
    d, p = {"byte_order": "ABCD"}, {"type": "int16", "scale": 0.1}
    for raw in range(-400, 800):
        v = round(raw * 0.1, 1)
        expected = stored_value(d, p, v)
        assert expected == decode(encode(v, "int16", "ABCD", 0.1), "int16", "ABCD", 0.1)
        assert expected == pytest.approx(v)


def test_float32_target_is_nearest_float32():
    d, p = {"byte_order": "CDAB"}, {"type": "float32", "scale": 1}
    assert stored_value(d, p, 21.3) == decode(encode(21.3, "float32", "CDAB"), "float32", "CDAB")


def test_value_outside_register_type_is_blocked():
    with pytest.raises(WriteBlocked) as e:
        stored_value({"byte_order": "ABCD"}, {"type": "uint16", "scale": 1}, 70000)
    assert e.value.code == "write.out_of_type_range"


# ---------- BACnet REAL và nhả lệnh khi ghi thất bại ----------
def test_bacnet_setpoint_float32_cannot_hold_exactly(cfg, conns, sim_ctl):
    """21.3 lưu thành REAL 21.299999...: trước đây bị báo "đọc lại không khớp" dù thiết bị đã nhận lệnh."""
    sim_ctl.reset()
    before, after = write_guarded(cfg, conns, SETPOINT, 21.3)
    assert after == pytest.approx(21.3, abs=1e-5)
    relinquish_guarded(cfg, conns, SETPOINT)


def test_bacnet_write_overridden_by_higher_priority_is_relinquished(cfg, conns, sim_ctl, tmp_path):
    """Mức ưu tiên 5 đang giữ 20 °C nên lệnh ở mức 8 không có hiệu lực: báo thất bại VÀ nhả mức 8 ngay, để khi
    mức 5 nhả ra thì thiết bị về giá trị mặc định chứ không âm thầm chạy theo 21.5 của lệnh thất bại."""
    sim_ctl.reset()
    d, p = find(cfg, SETPOINT)
    operator = dict(p, priority=5)
    write_bacnet(d, operator, 20.0)
    log = AuditLog(tmp_path / "a.jsonl")
    try:
        with pytest.raises(WriteFailed) as e:
            write_guarded(cfg, conns, SETPOINT, 21.5, audit=log, actor="t")
        assert e.value.code == "write.readback_mismatch"
        attempt, failed = log.tail()
        assert attempt["outcome"] == "attempt" and failed["outcome"] == "failed" and failed["relinquished"] is True
    finally:
        relinquish_bacnet(d, operator)
    assert conns.read(d, p) == pytest.approx(18.0)        # giá trị mặc định, không phải 21.5


# ---------- nhật ký kiểm toán ----------
def test_write_is_not_sent_when_audit_log_cannot_be_written(cfg, conns, sim_ctl, tmp_path):
    blocker = tmp_path / "khong-phai-thu-muc"
    blocker.write_text("")
    log = AuditLog(blocker / "writes.jsonl")              # không tạo được thư mục: một file nằm ở chỗ đó
    mark = sim_ctl.last_seq()
    with pytest.raises(WriteBlocked) as e:
        write_guarded(cfg, conns, "bess-01.che_do", 1, audit=log, actor="t")
    assert e.value.code == "write.audit_unavailable"
    assert sim_ctl.writes(since=mark) == []


def _fail_result_rows(log, monkeypatch):
    record = log.record

    def record_or_fail(**row):
        if row["outcome"] == "written":
            raise OSError("đĩa đầy")
        return record(**row)
    monkeypatch.setattr(log, "record", record_or_fail)


def test_audit_failure_after_write_says_device_changed(cfg, conns, sim_ctl, tmp_path, monkeypatch):
    log = AuditLog(tmp_path / "a.jsonl")
    _fail_result_rows(log, monkeypatch)
    with pytest.raises(AuditFailed) as e:
        write_guarded(cfg, conns, "bess-01.che_do", 1, audit=log, actor="t")
    assert (e.value.params["before"], e.value.params["after"]) == (0, 1)
    assert sim_ctl.get("bess-01.che_do")["value"] == 1
    assert [r["outcome"] for r in log.tail()] == ["attempt"]   # dòng trước khi gửi vẫn còn


def test_web_reports_written_when_audit_fails_after_write(cfg, sim_ctl, tmp_path, monkeypatch):
    log = AuditLog(tmp_path / "a.jsonl")
    _fail_result_rows(log, monkeypatch)
    c = Connections()
    srv = serve(cfg, c, port=0, audit=log)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/write",
                                     data=json.dumps({"point": "bess-01.che_do", "value": 1}).encode())
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        body = json.loads(e.value.read())
    finally:
        srv.shutdown()
        c.close()
    assert e.value.code == 500
    assert body["written"] is True and body["code"] == "write.audit_failed" and body["after"] == 1
