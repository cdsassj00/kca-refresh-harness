import yaml

def test_taxonomy_has_7_types(ROOT):
    t = yaml.safe_load((ROOT / "templates" / "taxonomy.yaml").read_text(encoding="utf-8"))
    assert [x["code"] for x in t["types"]] == ["F","M","S","P","T","B","G"]
    for x in t["types"]:
        assert x["verify_method"] in ("backtest","model_rerun","survey_map","policy_track","standard_track","case_refresh","kpi_track")
        assert x["rerun_grade"] in ("R1","R1~R2","R2~R3")

def test_verdict_rules(ROOT):
    v = yaml.safe_load((ROOT / "templates" / "verdict_rules.yaml").read_text(encoding="utf-8"))
    assert [x["name"] for x in v["verdicts"]] == ["동일","강화","부분수정","약화","뒤집힘","신규결론","판정불가"]
    assert v["numeric_rules"]["same_within_pct"] == 10

def test_domains(ROOT):
    ids = {"spectrum","emf_inspection","broadcast_media","network_5g6g","ict_qualification","kca_management"}
    files = {p.stem for p in (ROOT / "kb" / "domains").glob("*.yaml")}
    assert files == ids
    for p in (ROOT / "kb" / "domains").glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert d["id"] == p.stem
        for key in ("name","indicators","laws","agencies","standards","journals","news_keywords"):
            assert key in d
        for ind in d["indicators"]:
            assert {"name","source","locator"} <= set(ind)
