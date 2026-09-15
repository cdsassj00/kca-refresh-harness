"""보고서 레지스트리(registry.csv). 사용: python scripts/registry.py init | list"""
from __future__ import annotations
import argparse, csv, re, sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "registry.csv"
SAMPLES = ROOT / "samples" / "pdf"
COLUMNS = ["id", "title", "published", "years_since", "domain", "types", "maturity", "updated_at", "source_pdf"]
# 예: 01_[2023.04]_제목.pdf, 예비06_[2019.08]_제목.pdf
FN = re.compile(r"^(?:예비)?(\d{2})_\[(\d{4})\.(\d{2})\]_(.+)\.pdf$")

def years_since(published: str, today: Optional[date] = None) -> Optional[int]:
    """발간 연월(YYYY-MM)로부터 오늘까지 만으로 몇 년이 지났는지(정수). 값이 없거나 형식이 다르면 None."""
    m = re.match(r"^(\d{4})-(\d{2})", published or "")
    if not m: return None
    today = today or date.today()
    y, mo = int(m.group(1)), int(m.group(2))
    return (today.year - y) - (1 if today.month < mo else 0)

def load_registry(path: Path = DEFAULT) -> list[dict]:
    if not Path(path).exists(): return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]

def save_registry(rows: list[dict], path: Path = DEFAULT) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS); w.writeheader()
        for r in rows: w.writerow({c: r.get(c, "") for c in COLUMNS})

def _with_years(row: dict, today: Optional[date] = None) -> dict:
    ys = years_since(row.get("published", ""), today)
    row["years_since"] = "" if ys is None else str(ys)
    return row

def upsert(path: Path, row: dict, today: Optional[date] = None) -> None:
    rows = load_registry(path); row = dict(row); row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, r in enumerate(rows):
        if r["id"] == row["id"]:
            rows[i] = _with_years({**r, **row}, today); break
    else:
        rows.append(_with_years({c: row.get(c, "") for c in COLUMNS}, today))
    save_registry(sorted(rows, key=lambda r: r["id"]), path)

def set_maturity(path: Path, rid: str, level: str) -> None:
    upsert(path, {"id": rid, "maturity": level})

def init_from_reports(reports_dir: Path, path: Path, today: Optional[date] = None) -> list[dict]:
    """samples/pdf/*.pdf 파일명에서 번호·연월·제목을 읽어 R01~ 행을 등록(이미 있으면 갱신)한다."""
    for pdf in sorted(Path(reports_dir).glob("*.pdf")):
        m = FN.match(pdf.name)
        if not m: continue
        num, y, mo, title = m.groups()
        upsert(path, {"id": f"R{int(num):02d}", "title": title.replace("_", " "), "published": f"{y}-{mo}",
                      "domain": "", "types": "", "maturity": "-", "source_pdf": pdf.name}, today)
    return load_registry(path)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="보고서 레지스트리")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="samples/pdf/*.pdf에서 R01~ 등록"); sub.add_parser("list", help="현황 출력")
    a = ap.parse_args(argv)
    if a.cmd == "init":
        rows = init_from_reports(SAMPLES, DEFAULT); print(f"{len(rows)}건 등록")
    for r in load_registry(DEFAULT):
        print(f"{r['id']}  {r['maturity']:<4} {r['published']}  {r['years_since']:>2}년  {r['title']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
