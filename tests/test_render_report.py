"""render_report 테스트: 최소 JSON 세트로 8개 절이 모두 생성되는지, 파일이 없을 때 미생성 표시가 들어가는지."""
import json

from scripts import render_report as rr


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _minimal_set(base):
    """실제 R01 산출물과 같은 뼈대의 최소 JSON 세트."""
    _w(base / "01_meta.json", {"report_id": "RX", "title": "테스트 보고서", "published": "2023-04", "source_pdf": "x.pdf", "pages": 3})
    _w(base / "02_classification.json", {"title": "테스트 보고서", "publisher": "KCA", "published": "2023-04", "domains": ["spectrum"],
                                          "type_mix": {"F": 1.0},
                                          "research_design": {"rq": "무엇이 달라졌는가", "methods": ["방법1"], "data": ["데이터1"], "limits": ["한계1"], "sample": "표본"}})
    _w(base / "03_argument_chains.json", {"conclusions": [{"conclusion_id": "RX-K-F-01", "kind": "F", "page": 10, "printed_page": 2,
                                                            "statement": "원 결론", "method": "집계", "premises": ["P-01"], "evidence_refs": ["RX-S-001"], "rerun_grade": "R1"}],
                                           "premises": [{"premise_id": "P-01"}], "claims": [{"claim_id": "RX-S-001"}], "edges": [{"from": "P-01", "to": "RX-K-F-01"}]})
    _w(base / "L0" / "events.json", [{"event_id": "E-1", "domain": "spectrum", "date": "2024-01-01", "title": "사건", "affected_indicators": ["지표"],
                                      "sources": [{"url": "https://example.org/a", "title": "출처"}], "grade": "A"}])
    (base / "L0" / "environment_delta.md").write_text("# 델타\n\n## 확인 실패\n\n1. **항목**: 못 찾음\n", encoding="utf-8")
    _w(base / "L0" / "provisional_verdicts.json", [{"conclusion_id": "RX-K-F-01", "hit_premises": [], "provisional": {"expected_direction": "유지"}, "grade": "C"}])
    _w(base / "L1" / "verdicts.json", [{"claim_id": "RX-S-001", "conclusion_id": "RX-K-F-01", "level": "claim", "verdict": "적중",
                                        "original_value": {"metric": "개소", "value": 26, "unit": "개소", "year": 2022},
                                        "current_value": {"value": 104, "unit": "개소", "asof": "2025-12"}, "error_pct": 0.0, "reason": "일치",
                                        "evidence": [{"url": "https://example.org/b", "grade": "A"}]}])
    _w(base / "L2" / "traced" / "traced_conclusions.json", [{"conclusion_id": "RX-K-F-01", "method_applied": "같은 방법",
                                                              "inputs_now": [{"name": "입력", "value": 1, "unit": "개", "asof": "2025", "source_url": "https://example.org/c", "grade": "A"}],
                                                              "rederived": "재도출", "delta_vs_original": "+0%", "changed_locus": ["E"], "grade": "C",
                                                              "calc_note": "메모", "series": {"s": {"2025": 1, "2026": 2}}}])
    _w(base / "L2" / "blind_output" / "blind_conclusions.json", [{"item_id": "Q1", "question": "질문", "conclusion": "블라인드 결론", "method_used": "방법",
                                                                   "inputs": [{"name": "i", "value": 1, "source_url": "https://example.org/d", "grade": "B"}],
                                                                   "confidence": "높음", "caveats": ["유의"], "grade": "B"},
                                                                  {"files_opened": ["prompts/05_blind.md", "reports/RX/L2/blind_input/brief.md"], "note": "격리"}])
    _w(base / "comparison_table.json", {"report_id": "RX", "title": "테스트 보고서", "published": "2023-04", "generated_at": "2026-09-15", "maturity": "L2",
                                        "summary": {"동일": 1, "신규결론": 1},
                                        "conclusion_rows": [
                                            {"row_id": "K-F-01", "conclusion_id": "RX-K-F-01", "kind": "F", "location": "p.10", "old": "원 결론", "new": "새 결론",
                                             "blind_new": "블라인드 결론", "verdict": "동일", "reason_locus": ["E"], "reason": "같음",
                                             "evidence": [{"url": "https://example.org/b", "grade": "A", "note": "근거"}], "grade": "A", "status": "L2 최종"},
                                            {"row_id": "K-NEW-01", "conclusion_id": "RX-K-NEW-01", "kind": "R", "location": "(원 연구에 없음)", "old": "(원 연구에 없음)",
                                             "new": "신규 시사점", "blind_new": "Q1", "verdict": "신규결론", "reason_locus": ["P"], "reason": "새 사건",
                                             "evidence": [{"url": "https://example.org/e", "grade": "A", "note": "정책"}], "grade": "A", "status": "L2 최종", "upstream": ["E-1"]}],
                                        "body_rows": [{"row_id": "S-1", "location": "p.1", "old": "구", "new": "신", "change_type": "서술수정", "reason": "사유",
                                                       "evidence": [], "grade": "B", "status": "L0 잠정", "linked_conclusions": ["RX-K-F-01"]}],
                                        "l2_compare": {"rules": "규칙", "inputs": ["a.json"], "blind_mapping": {"Q1": ["RX-K-F-01"]}}})


def test_minimal_set_renders_all_sections(tmp_path):
    base = tmp_path / "reports" / "RX"
    _minimal_set(base)
    assert rr.main("RX", root=tmp_path) == 0
    md = (base / "07_report" / "report.md").read_text(encoding="utf-8")
    html_out = (base / "07_report" / "report.html").read_text(encoding="utf-8")
    for title in rr.SECTION_TITLES:
        assert f"## {title}" in md, title
        assert title in html_out, title
    assert "(아직 생성되지 않음" not in md
    # 핵심 내용이 JSON에서 그대로 옮겨졌는지
    assert "원 결론" in md and "새 결론" in md and "블라인드 결론" in md
    assert "격리 확인 · files_opened 2개" in md and "격리 유지" in md
    assert "신규 시사점" in md  # 7절 신규결론
    assert "L0 확인 실패 — **항목**: 못 찾음" in md  # 8.3 environment_delta.md 확인 실패
    assert '<meta charset="utf-8">' in html_out and 'class="pill p-good"' in html_out


def test_missing_inputs_are_marked(tmp_path):
    base = tmp_path / "reports" / "RY"
    _w(base / "01_meta.json", {"report_id": "RY", "title": "메타만 있는 보고서", "published": "2024-01"})
    assert rr.main("RY", root=tmp_path) == 0
    md = (base / "07_report" / "report.md").read_text(encoding="utf-8")
    assert "(아직 생성되지 않음" in md
    for title in rr.SECTION_TITLES:  # 파일이 없어도 8개 절 제목은 모두 있어야 한다
        assert f"## {title}" in md, title
    assert "비교(compare) 실행 필요" in md and "L1 근거 재검증(verify) 실행 필요" in md
    assert "| 접수(intake) | 01_meta.json | 있음 |" in md and "| 비교(compare) | comparison_table.json | 없음 |" in md
    assert (base / "07_report" / "report.html").exists()
