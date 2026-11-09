"""SONG NGỮ vi / ja — đọc từ điển messages.yml, định dạng thông báo, và lỗi mang mã dịch được.

Server không chọn ngôn ngữ cho trang web: lỗi trả về gồm `error` (tiếng Việt, cho dòng lệnh và log),
`code` và `params`; trang web tự dịch `code` theo ngôn ngữ người dùng chọn, dùng /i18n.json.
"""
from pathlib import Path
import yaml

LANGS = ("vi", "ja")
DEFAULT_LANG = "vi"
FILE = Path(__file__).with_name("messages.yml")
SCRIPT = Path(__file__).with_name("i18n.js")       # mã song ngữ dùng chung cho các trang web, phục vụ ở /i18n.js
_catalog: dict[str, dict[str, str]] | None = None


def catalog() -> dict[str, dict[str, str]]:
    """Khóa -> {"vi": ..., "ja": ...}; đọc một lần."""
    global _catalog
    if _catalog is None:
        _catalog = yaml.safe_load(FILE.read_text(encoding="utf-8")) or {}
    return _catalog


def by_language() -> dict[str, dict[str, str]]:
    """Dạng trang web dùng: {"vi": {khóa: chữ}, "ja": {khóa: chữ}}."""
    return {lang: {k: v[lang] for k, v in catalog().items()} for lang in LANGS}


def _show(v) -> str:
    return ", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)


def t(key: str, lang: str = DEFAULT_LANG, /, **params) -> str:
    """Chữ của `key` theo `lang`, điền {tên} bằng params. Khóa không có -> KeyError (bắt lỗi gõ nhầm)."""
    return catalog()[key][lang].format(**{k: _show(v) for k, v in params.items()})


class Translatable(Exception):
    """Lỗi có mã trong từ điển: str(e) là tiếng Việt; trang web dịch lại theo code và params."""

    def __init__(self, code: str, /, **params):
        self.code, self.params = code, params
        super().__init__(t(code, DEFAULT_LANG, **params))

    def as_json(self) -> dict:
        return {"error": str(self), "code": self.code, "params": self.params}


class ApiError(Translatable):
    """Lỗi yêu cầu HTTP (sai dạng, sai đường dẫn)."""
