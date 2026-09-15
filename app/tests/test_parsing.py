"""engine.parsing 테스트 — 작은 PDF(직접 생성·pypdf 생성)·HWPX(zip+최소 XML)·TXT 파싱과 intake."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import config
from engine import parsing
from engine.parsing import ParseError, intake, parse_document


# ---------------------------------------------------------------- 도우미
def _make_pdf(path: Path, pages: list[str]) -> None:
    """외부 라이브러리 없이 최소 PDF 를 만든다. 각 원소가 한 쪽의 본문(ASCII)."""
    page_objs, page_ids = [], []
    oid = 4
    for text in pages:
        pid, cid = oid, oid + 1
        oid += 2
        page_ids.append(pid)
        stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("latin-1") if text else b""
        page_objs.append((pid, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
                                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>").encode()))
        page_objs.append((cid, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"))
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objs = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
            (2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()),
            (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")] + page_objs
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for o, body in objs:
        offsets[o] = len(out)
        out += f"{o} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    total = len(objs) + 1
    out += f"xref\n0 {total}\n".encode() + b"0000000000 65535 f \n"
    for o in range(1, total):
        out += f"{offsets[o]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


_HWPX_SECTION = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"
        xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">
  <hp:p id="1" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0">
    <hp:run charPrIDRef="0"><hp:secPr id="" textDirection="HORIZONTAL"/><hp:t>첫 문단입니다.</hp:t></hp:run>
    <hp:linesegarray><hp:lineseg textpos="0" vertpos="0"/></hp:linesegarray>
  </hp:p>
  <hp:p id="2" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0">
    <hp:run charPrIDRef="0"><hp:t>둘째 </hp:t></hp:run><hp:run charPrIDRef="1"><hp:t>문단</hp:t></hp:run>
  </hp:p>
  <hp:p id="3" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0">
    <hp:run charPrIDRef="0">
      <hp:tbl id="9" rowCnt="2" colCnt="2">
        <hp:tr>
          <hp:tc><hp:subList><hp:p><hp:run><hp:t>항목</hp:t></hp:run></hp:p></hp:subList></hp:tc>
          <hp:tc><hp:subList><hp:p><hp:run><hp:t>값</hp:t></hp:run></hp:p></hp:subList></hp:tc>
        </hp:tr>
        <hp:tr>
          <hp:tc><hp:subList><hp:p><hp:run><hp:t>가입자</hp:t></hp:run></hp:p></hp:subList></hp:tc>
          <hp:tc><hp:subList><hp:p><hp:run><hp:t>100</hp:t></hp:run></hp:p></hp:subList></hp:tc>
        </hp:tr>
      </hp:tbl>
    </hp:run>
  </hp:p>
  <hp:p id="4" paraPrIDRef="0" styleIDRef="0" pageBreak="1" columnBreak="0">
    <hp:run charPrIDRef="0"><hp:t>둘째 쪽 본문</hp:t></hp:run>
  </hp:p>
</hs:sec>
"""


def _make_hwpx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("version.xml", '<?xml version="1.0" encoding="UTF-8"?><hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version"/>')
        z.writestr("Contents/content.hpf", "<opf:package xmlns:opf=\"http://www.idpf.org/2007/opf/\"/>")
        z.writestr("Contents/section0.xml", _HWPX_SECTION)


# ---------------------------------------------------------------- PDF
def test_pdf_text_pages_and_filename_guess(tmp_path):
    pdf = tmp_path / "09_[2021.03]_전파_연구_테스트.pdf"
    _make_pdf(pdf, ["KCA report page one", "second page here"])
    text, meta = parse_document(pdf)
    assert "<!-- page 1 -->" in text and "<!-- page 2 -->" in text
    assert "page one" in text and "second page" in text
    assert text.index("<!-- page 1 -->") < text.index("page one") < text.index("<!-- page 2 -->")
    assert meta["pages"] == 2 and meta["format"] == "pdf" and meta["scanned"] is False
    assert meta["chars"] == len(text) and meta["chars"] > 0
    assert meta["published_guess"] == "2021-03"
    assert meta["title_guess"] == "전파 연구 테스트"


def test_pdf_blank_pages_marked_scanned(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(3):
        w.add_blank_page(width=200, height=200)
    pdf = tmp_path / "scan.pdf"
    with pdf.open("wb") as f:
        w.write(f)
    text, meta = parse_document(pdf)
    assert meta["pages"] == 3 and meta["scanned"] is True
    assert text.count("<!-- page ") == 3
    assert meta["published_guess"] is None and meta["title_guess"] == "scan"


def test_pdf_half_text_not_scanned(tmp_path):
    pdf = tmp_path / "half.pdf"
    _make_pdf(pdf, ["has text", ""])  # 빈 쪽 50% — 50% 초과가 아니므로 스캔본 아님
    _, meta = parse_document(pdf)
    assert meta["scanned"] is False


# ---------------------------------------------------------------- HWPX
def test_hwpx_paragraphs_tables_pages(tmp_path):
    p = tmp_path / "예비12_[2020.11]_한글_보고서.hwpx"
    _make_hwpx(p)
    text, meta = parse_document(p)
    assert "첫 문단입니다." in text
    assert "둘째 문단" in text                       # 같은 문단의 run 두 개가 이어짐
    assert "| 항목 | 값 |" in text and "| 가입자 | 100 |" in text
    assert "<!-- page 1 -->" in text and "<!-- page 2 -->" in text
    assert text.index("| 가입자 | 100 |") < text.index("<!-- page 2 -->") < text.index("둘째 쪽 본문")
    assert meta["format"] == "hwpx" and meta["pages"] == 2 and meta["scanned"] is False
    assert meta["published_guess"] == "2020-11" and meta["title_guess"] == "한글 보고서"


def test_hwp_named_but_actually_hwpx_is_parsed(tmp_path):
    p = tmp_path / "renamed.hwp"
    _make_hwpx(p)
    text, meta = parse_document(p)
    assert meta["format"] == "hwpx" and "첫 문단입니다." in text


def test_hwpx_without_sections_raises(tmp_path):
    p = tmp_path / "empty.hwpx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
    with pytest.raises(ParseError) as ei:
        parse_document(p)
    assert "section" in str(ei.value)


# ---------------------------------------------------------------- HWP / TXT / 기타
@pytest.mark.skipif(parsing.hwp_available(), reason="pyhwp 가 설치되어 있으면 실제 파싱을 시도한다")
def test_hwp_without_pyhwp_gives_korean_error(tmp_path):
    p = tmp_path / "old.hwp"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)  # OLE 헤더 흉내
    with pytest.raises(ParseError) as ei:
        parse_document(p)
    assert "pyhwp" in str(ei.value) and "PDF" in str(ei.value)


def test_txt_passthrough(tmp_path):
    p = tmp_path / "보고서_초안.txt"
    p.write_text("가나다\n라마바\n", encoding="utf-8")
    text, meta = parse_document(p)
    assert text.startswith("\n\n<!-- page 1 -->\n")
    assert "가나다\n라마바" in text
    assert meta["format"] == "txt" and meta["pages"] == 1 and meta["chars"] == len(text)
    assert meta["title_guess"] == "보고서 초안" and meta["published_guess"] is None


def test_md_and_cp949(tmp_path):
    p = tmp_path / "memo.md"
    p.write_bytes("# 제목\n본문 한글".encode("cp949"))
    text, meta = parse_document(p)
    assert "본문 한글" in text and meta["format"] == "md"


def test_unsupported_and_missing(tmp_path):
    p = tmp_path / "x.xyz"
    p.write_text("a", encoding="utf-8")
    with pytest.raises(ParseError) as ei:
        parse_document(p)
    assert "지원하지 않는 형식" in str(ei.value)
    with pytest.raises(ParseError):
        parse_document(tmp_path / "없는파일.pdf")


def test_normalize_published():
    assert parsing.normalize_published("2023.04") == "2023-04"
    assert parsing.normalize_published("2023-4") == "2023-04"
    assert parsing.normalize_published("2023-04-20") == "2023-04"
    assert parsing.normalize_published("") is None
    with pytest.raises(ValueError):
        parsing.normalize_published("2023")
    with pytest.raises(ValueError):
        parsing.normalize_published("2023-13")


# ---------------------------------------------------------------- intake
def test_intake_writes_source_meta_registry(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    registry = tmp_path / "registry.csv"
    monkeypatch.setattr(config, "REPORTS_DIR", reports)
    monkeypatch.setattr(config, "REGISTRY_CSV", registry)

    src = tmp_path / "10_[2022.07]_접수_테스트.txt"
    src.write_text("본문입니다.", encoding="utf-8")
    meta = intake("R09", src, title="  ", published="2020.05")

    assert set(meta) >= {"report_id", "source_pdf", "pages", "chars", "published", "title", "format", "scanned"}
    assert meta["report_id"] == "R09" and meta["source_pdf"] == src.name
    assert meta["published"] == "2020-05"          # 명시값이 파일명 추정(2022-07)보다 우선
    assert meta["title"] == "접수 테스트"           # 빈 제목이면 파일명 추정
    assert meta["format"] == "txt" and meta["scanned"] is False

    assert (reports / "R09" / "00_source" / "R09.md").read_text(encoding="utf-8").endswith("본문입니다.")
    saved = json.loads((reports / "R09" / "01_meta.json").read_text(encoding="utf-8"))
    assert saved == meta

    from scripts.registry import load_registry
    rows = {r["id"]: r for r in load_registry(registry)}
    assert rows["R09"]["title"] == "접수 테스트" and rows["R09"]["published"] == "2020-05"
    assert rows["R09"]["maturity"] == "-" and rows["R09"]["source_pdf"] == src.name
    assert rows["R09"]["years_since"] != ""


def test_intake_rejects_bad_id_and_date(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "REGISTRY_CSV", tmp_path / "registry.csv")
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        intake("bad-id", src)
    with pytest.raises(ValueError):
        intake("R11", src, published="언젠가")
    assert not (tmp_path / "reports" / "R11").exists()  # 검증 실패 시 아무것도 쓰지 않음
