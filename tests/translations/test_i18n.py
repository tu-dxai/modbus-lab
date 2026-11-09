"""Kiểm thử từ điển song ngữ (i18n/messages.yml) và cách dùng nó trong code.

Bắt lỗi thường gặp khi dịch: thiếu một ngôn ngữ, lệch tham số {tên} giữa vi và ja,
và khóa dùng trong code hay trang web mà từ điển không có.
"""
import re
from pathlib import Path
import pytest
from i18n import LANGS, Translatable, catalog, t

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "tools/dashboard/collector.html", ROOT / "tools/simulator/control.html"]
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# Mã lỗi trong code Python: lớp lỗi dịch được, gọi với chuỗi mã làm đối số đầu tiên.
PY_CODE = re.compile(r"\b(?:WriteBlocked|WriteFailed|ReadError|BadValue|UnknownPoint|ApiError)\(\s*\"([a-z0-9_.]+)\"")
JS_KEY = re.compile(r"""data-i18n(?:-title|-placeholder)?="([a-z0-9_.]+)"|\bt\(\s*'([a-z0-9_.]+)'""")


def test_every_key_has_both_languages():
    for key, texts in catalog().items():
        for lang in LANGS:
            assert isinstance(texts.get(lang), str) and texts[lang].strip(), f"{key}: thiếu bản {lang}"


def test_placeholders_match_between_languages():
    for key, texts in catalog().items():
        assert set(PLACEHOLDER.findall(texts["vi"])) == set(PLACEHOLDER.findall(texts["ja"])), key


def test_format_fills_params():
    assert "5" in t("write.not_allowed", "ja", value=5, allowed=[0, 1])
    assert "(0, 1)" in t("write.not_allowed", "vi", value=5, allowed=[0, 1])


def test_unknown_key_is_an_error():
    with pytest.raises(KeyError):
        t("khong.co.khoa.nay")


def test_translatable_error_carries_code_and_vietnamese_text():
    e = Translatable("write.not_writable", key="dong-ho-dien-01.dien_ap")
    assert e.code == "write.not_writable" and e.params == {"key": "dong-ho-dien-01.dien_ap"}
    assert str(e) == t("write.not_writable", "vi", key="dong-ho-dien-01.dien_ap")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_page_keys_exist(page):
    keys = {a or b for a, b in JS_KEY.findall(page.read_text(encoding="utf-8"))}
    assert keys, f"{page.name} chưa dùng từ điển"
    assert sorted(keys - catalog().keys()) == []


def test_python_error_codes_exist():
    codes = set()
    for f in list((ROOT / "edge").rglob("*.py")) + list((ROOT / "tools").rglob("*.py")):
        codes |= set(PY_CODE.findall(f.read_text(encoding="utf-8")))
    assert codes, "chưa có mã lỗi nào dùng từ điển"
    assert sorted(codes - catalog().keys()) == []


def test_export_lists_dictionary_and_point_map_labels():
    from export import rows
    got = {(src, key): (vi, ja) for src, key, vi, ja in rows()}
    assert got[("messages.yml", "write.not_allowed")][1]
    assert got[("Point Map: điểm đo", "bess-01.che_do")] == ("Chế độ vận hành", "運転モード")
    assert ("Point Map: cảnh báo", "bess-01.muc_pin") in got
