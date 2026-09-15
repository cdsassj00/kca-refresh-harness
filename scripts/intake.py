"""접수: PDF -> 페이지별 Markdown 텍스트 + 메타(01_meta.json). 사용: python scripts/intake.py <report_id> <pdf>"""
import json, re, sys
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

def main(rid: str, pdf: str) -> int:
    out_dir = ROOT / "reports" / rid / "00_source"; out_dir.mkdir(parents=True, exist_ok=True)
    r = PdfReader(pdf); pages = []
    for i, p in enumerate(r.pages, 1):
        try: t = p.extract_text() or ""
        except Exception: t = ""
        pages.append(f"\n\n<!-- page {i} -->\n" + t)
    text = "".join(pages)
    (out_dir / f"{rid}.md").write_text(text, encoding="utf-8")
    m = re.search(r"^(?:예비)?\d{2}_\[(\d{4})\.(\d{2})\]_(.+)\.pdf$", Path(pdf).name)
    meta = {"report_id": rid, "source_pdf": Path(pdf).name, "pages": len(r.pages), "chars": len(text),
            "published": f"{m.group(1)}-{m.group(2)}" if m else None,
            "title": m.group(3).replace("_", " ") if m else Path(pdf).stem}
    (ROOT / "reports" / rid / "01_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False)); return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
