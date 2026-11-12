"""Kiểm thử tự động giai đoạn 1 — mã MB-xx khớp với tài liệu nghiên cứu.

Chạy:  make test
Simulator được bật tự động theo môi trường lab, cổng 5021 (xem tests/conftest.py).
`conns` tự chọn đúng địa chỉ của từng thiết bị; `client` là kết nối thô tới gateway điện.
"""
import copy
import pytest
from codec import decode, encode
from collector import LATEST, poll_once
from modbus_io import Connections, read_point
from write import WriteBlocked, find, write_guarded


def read_value(cfg, conns, key):
    d, p = find(cfg, key)
    return conns.read(d, p)


# ---------- MB-01: đọc một thanh ghi có giá trị biết trước ----------
def test_mb01_read_single_register(cfg, conns):
    assert read_value(cfg, conns, "dong-ho-dien-01.dien_ap") == pytest.approx(230.0)


# ---------- MB-02: bốn kiểu byte order ----------
@pytest.mark.parametrize("order", ["ABCD", "CDAB", "BADC", "DCBA"])
def test_mb02_codec_four_byte_orders(order):
    regs = encode(23.5, "float32", order)
    assert decode(regs, "float32", order) == pytest.approx(23.5)
    if order != "ABCD":                      # đọc nhầm thành ABCD thì phải ra số khác
        assert decode(regs, "float32", "ABCD") != pytest.approx(23.5)


def test_mb02_device_uses_cdab(cfg, conns):
    d, p = find(cfg, "bess-01.muc_pin")
    regs = conns.client(d).read_input_registers(p["address"], count=2, device_id=d["device_id"]).registers
    assert decode(regs, "float32", "CDAB") == pytest.approx(80.0)
    assert decode(regs, "float32", "ABCD") != pytest.approx(80.0)


# ---------- MB-03: lệch địa chỉ một ô ----------
def test_mb03_offset_shift_reads_wrong_point(cfg, client):
    d, p = find(cfg, "dong-ho-dien-01.dien_ap")
    shifted = dict(p, address=p["address"] + 1)  # cấu hình sai: lệch 1 ô
    assert read_point(client, d, shifted) != pytest.approx(230.0)   # đọc phải dòng điện


# ---------- MB-04: hệ số và số có dấu ----------
def test_mb04_signed_and_scale(cfg, conns):
    d, p = find(cfg, "bess-01.nhiet_do_pin")
    assert conns.read(d, p) == pytest.approx(-2.0)
    wrong = dict(p, type="uint16")             # cấu hình sai: không dấu
    assert conns.read(d, wrong) == pytest.approx(6551.6)   # -20 lưu dạng bù hai = 65516, x0.1


# ---------- MB-05: địa chỉ không tồn tại ----------
def test_mb05_nonexistent_address(client):
    r = client.read_holding_registers(50, count=1, device_id=1)
    assert r.isError() and r.exception_code == 2


# ---------- MB-06: sai slave address ----------
def test_mb06_wrong_device_id(client):
    r = client.read_holding_registers(0, count=1, device_id=9)
    assert r.isError()     # simulator trả mã 04; thiết bị thật có thể chỉ im lặng tới timeout


# ---------- MB-07: mất kết nối không làm sập collector ----------
def test_mb07_connection_lost(cfg):
    wrong = copy.deepcopy(cfg)
    for d in wrong["devices"]:
        d.update(port=5999, timeout=0.5)       # không còn thiết bị nào trả lời
        if d.get("transport") == "rtu":
            d["serial"] = dict(d["serial"], port="var/serial/khong-co-cong-nay")
    c = Connections()
    try:
        poll_once(c, wrong)
    finally:
        c.close()
    assert LATEST and all(not r["ok"] for r in LATEST.values())


# ---------- MB-10: ghi qua rào chắn ----------
def test_mb10_valid_write_and_readback(cfg, conns):
    before, after = write_guarded(cfg, conns, "bess-01.che_do", 1)
    assert after == 1
    write_guarded(cfg, conns, "bess-01.che_do", before)   # trả lại như cũ


@pytest.mark.parametrize("key,value", [
    ("bess-01.che_do", 5),                    # giá trị ngoài danh sách cho phép
    ("dong-ho-dien-01.dien_ap", 999),         # điểm chỉ đọc
    ("khong-co.diem_nao", 1),                 # không có trong Point Map
])
def test_mb10_guard_rejects(cfg, conns, key, value):
    with pytest.raises(WriteBlocked):
        write_guarded(cfg, conns, key, value)


def with_bounds(cfg, **bounds):
    """Bản sao Point Map trong đó che_do khai báo khoảng (hoặc không gì cả) thay cho allowed."""
    c = copy.deepcopy(cfg)
    _, p = find(c, "bess-01.che_do")
    del p["allowed"]
    p.update(bounds)
    return c


@pytest.mark.parametrize("value", [-1, 2])
def test_mb10_guard_rejects_out_of_range(cfg, conns, value):
    with pytest.raises(WriteBlocked):
        write_guarded(with_bounds(cfg, min=0, max=1), conns, "bess-01.che_do", value)


def test_mb10_guard_accepts_in_range(cfg, conns):
    c = with_bounds(cfg, min=0, max=1)
    before, after = write_guarded(c, conns, "bess-01.che_do", 1)
    assert after == 1
    write_guarded(c, conns, "bess-01.che_do", before)      # trả lại như cũ


def test_mb10_guard_rejects_writable_without_limits(cfg, conns):
    with pytest.raises(WriteBlocked):                       # thiếu cả allowed lẫn min/max: không cho ghi
        write_guarded(with_bounds(cfg), conns, "bess-01.che_do", 1)


def test_mb10_device_rejects_readonly_write(client):
    r = client.write_register(0, 999, device_id=1)   # vượt rào chắn, ghi thẳng
    assert r.isError() and r.exception_code == 2
