"""XUẤT BẢN DỊCH ĐỂ DUYỆT — mọi cặp vi/ja ra bảng TSV (mở bằng Excel hoặc Google Sheets).

Chạy:  make i18n-export > ban-dich.tsv

Cột: nguồn, khóa, vi, ja. Nguồn là i18n/messages.yml (chữ giao diện, thông báo lỗi) hoặc
Point Map (nhãn thiết bị, nhãn điểm đo, câu cảnh báo).
"""
import sys
from i18n import catalog
from point_map import DEFAULT_PATH, SITE_ENV, read


def rows(point_map_path: str = DEFAULT_PATH) -> list[tuple[str, str, str, str]]:
    out = [("messages.yml", key, v["vi"], v["ja"]) for key, v in catalog().items()]
    cfg = read(point_map_path, env=SITE_ENV)       # chỉ đọc nhãn, không cần ánh xạ địa chỉ
    for d in cfg.get("devices", []):
        out.append(("Point Map: thiết bị", d["name"], d["label"]["vi"], d["label"]["ja"]))
        for p in d.get("points", []):
            out.append(("Point Map: điểm đo", f"{d['name']}.{p['name']}", p["label"]["vi"], p["label"]["ja"]))
    for a in cfg.get("alerts", []):
        out.append(("Point Map: cảnh báo", a["point"], a["message"]["vi"], a["message"]["ja"]))
    return out


def main() -> None:
    w = sys.stdout
    w.write("nguồn\tkhóa\tvi\tja\n")
    for row in rows():
        w.write("\t".join(cell.replace("\t", " ").replace("\n", " ") for cell in row) + "\n")


if __name__ == "__main__":
    main()
