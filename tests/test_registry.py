from datetime import date
from scripts.registry import COLUMNS, load_registry, upsert, set_maturity, init_from_reports, years_since

def test_columns_have_years_since_right_after_published():
    assert COLUMNS.index("years_since") == COLUMNS.index("published") + 1

def test_years_since_is_full_years_elapsed():
    today = date(2026, 9, 15)
    assert years_since("2023-04", today) == 3     # 3년 5개월 → 3
    assert years_since("2019-08", today) == 7     # 7년 1개월 → 7
    assert years_since("2019-12", today) == 6     # 6년 9개월 → 6
    assert years_since("2026-09", today) == 0
    assert years_since("", today) is None

def test_init_from_reports_maps_filenames(tmp_path):
    pdf_dir = tmp_path / "samples" / "pdf"; pdf_dir.mkdir(parents=True)
    (pdf_dir / "01_[2023.04]_디지털전환_5G.pdf").write_bytes(b"%PDF")
    (pdf_dir / "예비06_[2019.08]_미래전략.pdf").write_bytes(b"%PDF")
    (pdf_dir / "무관한_파일.pdf").write_bytes(b"%PDF")
    csv_path = tmp_path / "registry.csv"
    rows = init_from_reports(pdf_dir, csv_path)
    ids = {r["id"]: r for r in rows}
    assert set(ids) == {"R01", "R06"}
    assert ids["R01"]["published"] == "2023-04" and ids["R01"]["title"] == "디지털전환 5G"
    assert ids["R01"]["years_since"] == str(years_since("2023-04"))
    assert ids["R06"]["published"] == "2019-08" and ids["R06"]["maturity"] == "-"
    assert ids["R06"]["source_pdf"] == "예비06_[2019.08]_미래전략.pdf"
    assert list(load_registry(csv_path)[0].keys()) == COLUMNS

def test_upsert_and_maturity(tmp_path):
    p = tmp_path / "r.csv"
    upsert(p, {"id": "R01", "title": "t", "published": "2023-04", "domain": "spectrum", "types": "F;M", "maturity": "-", "source_pdf": "x.pdf"})
    upsert(p, {"id": "R01", "title": "t2"})
    set_maturity(p, "R01", "L0")
    r = load_registry(p)[0]
    assert r["title"] == "t2" and r["maturity"] == "L0" and r["updated_at"]
    assert r["years_since"] == str(years_since("2023-04"))
