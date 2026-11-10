"""NHẬT KÝ KIỂM TOÁN LỆNH GHI — mỗi lệnh ghi qua rào chắn để lại một dòng JSON, chỉ ghi thêm.

Ghi lại cả lệnh bị rào chắn chặn và lệnh bị thiết bị từ chối, để trả lời được: ai ghi gì, vào đâu,
lúc nào, kết quả ra sao. Mỗi dòng gồm:
  at, actor (cli:<user> | web:<ip>), env, site, point, device, device_id, site_endpoint,
  value (giá trị yêu cầu), outcome (written | released | blocked | failed), before, after,
  priority (BACnet), code, error

Xem nhanh:  make audit            (20 dòng cuối)
            make audit ARGS="-n 100 --file var/audit/writes.jsonl"
"""
import argparse, json, sys, threading
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = "var/audit/writes.jsonl"


class AuditLog:
    """File JSON Lines chỉ ghi thêm; an toàn khi nhiều luồng (web) cùng ghi."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.lock = threading.Lock()

    def record(self, **entry) -> dict:
        row = {"at": datetime.now().astimezone().isoformat(timespec="milliseconds"), **entry}
        line = json.dumps(row, ensure_ascii=False, default=str)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
        return row

    def tail(self, n: int | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(x) for x in lines if x.strip()]
        return rows[-n:] if n else rows


OUTCOME_VI = {"written": "ĐÃ GHI", "released": "NHẢ LỆNH", "blocked": "BỊ CHẶN", "failed": "THẤT BẠI"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Xem nhật ký kiểm toán lệnh ghi")
    ap.add_argument("--file", default=DEFAULT_PATH)
    ap.add_argument("-n", type=int, default=20, help="số dòng cuối (mặc định 20)")
    args = ap.parse_args(argv)
    rows = AuditLog(args.file).tail(args.n)
    if not rows:
        print(f"(chưa có lệnh ghi nào trong {args.file})")
    for r in rows:
        change = f"{r['before']} -> {r['after']}" if r["outcome"] in ("written", "released") \
            else (r.get("error") or r.get("code"))
        if r.get("priority"):
            change += f"  (ưu tiên {r['priority']})"
        print(f"{r['at'][:23]}  {r['actor']:<18} {r['env']:<5} {OUTCOME_VI.get(r['outcome'], r['outcome']):<9} "
              f"{r['point']} = {'relinquish' if r['outcome'] == 'released' else r['value']}  @ {r.get('site_endpoint') or '-'}  {change}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
