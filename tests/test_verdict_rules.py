"""판정 임계값의 유형별 분화(templates/verdict_rules.yaml 의 by_type) 검사.

지적 A: 시장전망·경제성·정책평가에 같은 ±10/30% 를 쓰면 안 된다.
- 유형 코드는 taxonomy.yaml 과 같아야 한다(F/M/S/P/T/B/G).
- 상태로 재는 유형(P·S·T)은 mode 를 가진다.
- 수치로 재는 유형(F·M)은 same_within_pct·partial_within_pct 를 가진다.
- 모든 항목에 rationale 이 있어야 한다(근거를 못 찾았으면 "잠정값 — 근거 미확보").
- 기존 numeric_rules 는 유형 미지정 시 기본값으로 남아 있어야 한다.
"""
import yaml

CODES = ["F", "M", "S", "P", "T", "B", "G"]
NUMERIC_CODES = ["F", "M"]
STATE_CODES = ["P", "S", "T"]
MODES = {"numeric_error", "numeric_with_sensitivity", "state", "substitute_or_redesign",
         "standard_tracking", "case_validity_ratio", "kpi_attainment"}
VERDICTS = {"동일", "강화", "부분수정", "약화", "뒤집힘", "신규결론", "판정불가"}


def _rules(ROOT):
    return yaml.safe_load((ROOT / "templates" / "verdict_rules.yaml").read_text(encoding="utf-8"))


def test_by_type_has_all_seven_types(ROOT):
    by_type = _rules(ROOT)["by_type"]
    assert sorted(by_type) == sorted(CODES)
    taxonomy = yaml.safe_load((ROOT / "templates" / "taxonomy.yaml").read_text(encoding="utf-8"))
    assert sorted(by_type) == sorted(x["code"] for x in taxonomy["types"])


def test_every_type_has_mode_and_rationale(ROOT):
    for code, t in _rules(ROOT)["by_type"].items():
        assert t.get("mode") in MODES, code
        assert isinstance(t.get("rationale"), str) and t["rationale"].strip(), code
        assert t.get("name"), code


def test_state_modes_are_not_percent_based(ROOT):
    """P·S·T 는 퍼센트가 아니라 상태·대체 가능성·표준 변경으로 잰다."""
    by_type = _rules(ROOT)["by_type"]
    for code in STATE_CODES:
        t = by_type[code]
        assert "mode" in t, code
        assert "same_within_pct" not in t, f"{code}: 상태 유형에 퍼센트 임계값이 들어 있다"
    assert by_type["P"]["mode"] == "state"
    assert by_type["S"]["mode"] == "substitute_or_redesign"
    assert by_type["T"]["mode"] == "standard_tracking"


def test_numeric_types_have_thresholds_and_sources(ROOT):
    for code in NUMERIC_CODES:
        t = _rules(ROOT)["by_type"][code]
        assert isinstance(t["same_within_pct"], (int, float)), code
        assert isinstance(t["partial_within_pct"], (int, float)), code
        assert t["same_within_pct"] < t["partial_within_pct"], code
        # 수치 임계값은 인용 가능한 출처를 달아야 한다
        assert str(t.get("source_url", "")).startswith("http"), code


def test_F_horizons_long_is_looser_than_short(ROOT):
    f = _rules(ROOT)["by_type"]["F"]
    assert f["horizon_years"] == 5  # 중장기(5년 초과)를 가르는 기준
    hz = {h["id"]: h for h in f["horizons"]}
    assert set(hz) == {"short", "long"}
    for h in hz.values():
        assert h["rationale"].strip() and str(h.get("source_url", "")).startswith("http")
        assert h["same_within_pct"] < h["partial_within_pct"]
    assert hz["long"]["same_within_pct"] > hz["short"]["same_within_pct"]
    assert hz["long"]["partial_within_pct"] > hz["short"]["partial_within_pct"]
    # Lewis(1982) MAPE 해석: <10 매우 정확, 10~20 좋음
    assert hz["short"]["same_within_pct"] == 10 and hz["short"]["partial_within_pct"] == 20


def test_M_has_sign_stability(ROOT):
    ss = _rules(ROOT)["by_type"]["M"]["sign_stability"]
    assert isinstance(ss["shock_pct"], (int, float)) and ss["shock_pct"] > 0
    assert ss["pass_verdict"] == "동일" and ss["sign_flip_verdict"] == "뒤집힘"
    assert ss["fail_verdict"] in VERDICTS and ss["unavailable_verdict"] == "판정불가"
    assert ss["rationale"].strip() and str(ss.get("source_url", "")).startswith("http")


def test_P_state_table_covers_verdicts(ROOT):
    states = _rules(ROOT)["by_type"]["P"]["states"]
    verdicts = [x["verdict"] for x in states]
    assert {"동일", "부분수정", "약화", "뒤집힘", "판정불가"} <= set(verdicts)
    for x in states:
        assert x["state"] and x["verdict"] in VERDICTS and x["test"]


def test_T_state_table_tracks_standards(ROOT):
    states = _rules(ROOT)["by_type"]["T"]["states"]
    assert {"동일", "부분수정", "판정불가"} <= {x["verdict"] for x in states}
    for x in states:
        assert x["state"] and x["verdict"] in VERDICTS


def test_S_substitute_or_redesign(ROOT):
    s = _rules(ROOT)["by_type"]["S"]
    assert s["substitute_available"]["apply_type"] == "F"       # 동등 조사가 있으면 F 기준 준용
    assert s["substitute_unavailable"]["verdict"] == "판정불가"  # 없으면 설계서
    assert s["substitute_unavailable"]["next_action"] == "추가 조사(설계서)"
    assert len(s["equivalence_checks"]) >= 4


def test_B_and_G_use_ratio_metrics(ROOT):
    by_type = _rules(ROOT)["by_type"]
    b, g = by_type["B"], by_type["G"]
    assert 0 < b["valid_ratio_partial"] < b["valid_ratio_same"] <= 1
    assert 0 < g["attainment_partial"] < g["attainment_same"] <= 1
    # 근거를 못 찾은 값은 정직하게 표시한다
    for t in (b, g):
        assert "잠정값" in t["rationale"] and "근거 미확보" in t["rationale"]


def test_numeric_rules_remain_as_default(ROOT):
    """유형 미지정 시 기본값은 그대로 남아 있어야 한다(기존 산출물 호환)."""
    n = _rules(ROOT)["numeric_rules"]
    assert n == {"same_within_pct": 10, "partial_within_pct": 30, "strengthen_pct": 20}


def test_multi_type_rule_orders_state_before_numeric(ROOT):
    m = _rules(ROOT)["multi_type_rule"]
    order = m["order"]
    assert sorted(order) == sorted(CODES)
    assert order.index("P") < order.index("F")  # 상태 기준이 수치 기준보다 먼저
    assert m["rationale"].strip()
