"""현행화 보고서 렌더: reports/<id>/ 산출물 JSON -> 07_report/report.md + report.html
사용: python scripts/render_report.py R01

입력(모두 선택, 없으면 해당 절에 "(아직 생성되지 않음: 단계 X 실행 필요)" 표시):
  01_meta.json, 02_classification.json, 03_argument_chains.json,
  L0/events.json, L0/environment_delta.md, L0/provisional_verdicts.json,
  L1/verdicts.json, L2/traced/traced_conclusions.json, L2/blind_output/blind_conclusions.json,
  comparison_table.json
원칙: 모든 수치·문장은 JSON에서만 가져온다. 새 수치를 만들지 않는다. 원 결론(old)은 그대로 옮긴다.
"""
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

SECTION_TITLES = [
    "1. 결론 재도출 요약",
    "2. 원 연구 개요와 논증 사슬",
    "3. 환경변화 브리프",
    "4. 결론 대조표",
    "5. 근거 재검증 매트릭스",
    "6. 재수행 시뮬레이션 상세",
    "7. 새로운 정책 시사점",
    "8. 부록",
]

# 입력 파일 → (상대경로, 생성 단계 이름)
INPUTS = {
    "meta": ("01_meta.json", "접수(intake)"),
    "classification": ("02_classification.json", "분류(classify)"),
    "chains": ("03_argument_chains.json", "논증 사슬(chains)"),
    "events": ("L0/events.json", "L0 환경변화(delta)"),
    "delta_md": ("L0/environment_delta.md", "L0 환경변화(delta)"),
    "provisional": ("L0/provisional_verdicts.json", "L0 영향 전파(impact)"),
    "verdicts": ("L1/verdicts.json", "L1 근거 재검증(verify)"),
    "traced": ("L2/traced/traced_conclusions.json", "L2 추적 재도출(rederive)"),
    "blind": ("L2/blind_output/blind_conclusions.json", "L2 블라인드 재수행(blind)"),
    "comparison": ("comparison_table.json", "비교(compare)"),
}

# 핵심 3건 선정 우선순위(낮을수록 먼저). 뒤집힘·신규·판정불가 우선.
VERDICT_PRIORITY = {"뒤집힘": 0, "신규결론": 1, "판정불가": 2, "약화": 3, "부분수정": 4, "강화": 5, "동일": 6, "": 7}
VERDICT_ORDER = ["동일", "강화", "부분수정", "약화", "뒤집힘", "신규결론", "판정불가", "잠정"]
VERDICT_CLASS = {"동일": "good", "강화": "good", "부분수정": "warn", "약화": "warn", "뒤집힘": "bad",
                 "신규결론": "new", "판정불가": "na", "잠정": "na", "": "na",
                 "적중": "good", "유효": "good", "수정필요": "warn", "검증불가": "na"}

# 팔레트: scripts/render_table.py 와 동일하게 유지한다.
CSS = """
:root{--bg:#F4F6F9;--surface:#fff;--ink:#1A2330;--muted:#5E6B7A;--line:#D5DCE5;--accent:#0B6E8F;--accent-soft:#DCEEF4;
--good:#2E7D4F;--good-soft:#DFF2E6;--warn:#A8690E;--warn-soft:#FBEFD6;--bad:#B93A2B;--bad-soft:#FBE3DF;--na:#6F7C8A;--na-soft:#E8ECF0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0E141B;--surface:#151D26;--ink:#E7EDF3;--muted:#9AA7B5;--line:#2A3542;
--accent:#4FB3D4;--accent-soft:#123A48;--good:#5FCB8A;--good-soft:#163425;--warn:#E2B14A;--warn-soft:#3A2E12;--bad:#F07A6A;--bad-soft:#3F1F1B;--na:#8E9BA8;--na-soft:#232C36}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans KR","Noto Sans KR","Malgun Gothic",sans-serif;font-size:14.5px;line-height:1.6}
.wrap{max-width:1180px;margin:0 auto;padding:36px 20px 80px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:20px;margin:44px 0 12px;padding-top:12px;border-top:2px solid var(--accent)}
h3{font-size:16px;margin:26px 0 8px}h4{font-size:14.5px;margin:18px 0 6px;color:var(--muted)}
.sub{color:var(--muted);margin:0 0 18px}
nav.toc{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin:16px 0 8px}
nav.toc a{color:var(--accent);text-decoration:none;margin-right:14px;font-size:13.5px;white-space:nowrap}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12.5px;font-weight:700;white-space:nowrap}
.p-good{background:var(--good-soft);color:var(--good)}.p-warn{background:var(--warn-soft);color:var(--warn)}.p-bad{background:var(--bad-soft);color:var(--bad)}
.p-na{background:var(--na-soft);color:var(--na)}.p-new{background:var(--accent-soft);color:var(--accent)}
.tw{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:8px 0 14px}
table{width:100%;border-collapse:collapse;min-width:720px}th,td{border-top:1px solid var(--line);padding:9px 8px;vertical-align:top;text-align:left}
th{font-size:12px;letter-spacing:.06em;color:var(--muted);font-weight:500;border-top:0;white-space:nowrap}
td.old{background:var(--na-soft)}a{color:var(--accent)}
.missing{background:var(--warn-soft);color:var(--warn);border-radius:8px;padding:10px 14px;font-weight:700}
.note{color:var(--muted);font-size:13px}ul{margin:6px 0 12px;padding-left:22px}li{margin:3px 0}
"""

MISSING_FMT = "(아직 생성되지 않음: 단계 {} 실행 필요)"


# ---------- 공통 도우미 ----------
def missing(key: str) -> str:
    return MISSING_FMT.format(INPUTS[key][1])


def load_json(path: Path):
    """없거나 깨진 JSON이면 None. 예외로 죽지 않는다."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def as_list(d, *keys):
    """리스트면 그대로, dict면 후보 키 중 첫 리스트를 꺼낸다. 그 외 빈 리스트."""
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in keys:
            v = d.get(k)
            if isinstance(v, list):
                return v
    return []


def s(v, default="") -> str:
    """값을 표시용 문자열로. None/빈값은 default."""
    if v is None or v == "" or v == []:
        return default
    if isinstance(v, (list, tuple)):
        return ", ".join(s(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k} {s(x)}" for k, x in v.items())
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def clip(text, n=160) -> str:
    t = s(text)
    return t if len(t) <= n else t[: n - 1] + "…"


def link(title, url) -> str:
    """마크다운 링크 문자열. HTML 렌더러가 다시 <a>로 바꾼다."""
    t = s(title) or s(url)
    return f"[{t}]({url})" if s(url).startswith("http") else t


def value_with_unit(d) -> str:
    """{value, unit, asof, years...} 형태를 한 줄로."""
    if not isinstance(d, dict):
        return s(d, "—")
    parts = []
    if d.get("value") not in (None, ""):
        parts.append(s(d["value"]) + (s(d.get("unit")) if d.get("unit") else ""))
    for k in ("year", "years", "asof"):
        if d.get(k) not in (None, ""):
            parts.append(f"({s(d[k])})")
            break
    if d.get("scenarios"):
        parts.append("시나리오 " + s(d["scenarios"]))
    return " ".join(parts) if parts else s(d.get("note"), "—")


def best_grade(evs) -> str:
    grades = [s(e.get("grade")) for e in (evs or []) if isinstance(e, dict) and e.get("grade")]
    return min(grades) if grades else ""


def next_action(row: dict) -> str:
    for k in ("next_action", "action", "next_step"):
        if row.get(k):
            return s(row[k])
    return "—"


# ---------- 블록 모델 ----------
# ("h", level, text) / ("p", text) / ("ul", [items]) / ("table", headers, rows, pill_cols) / ("missing", text)
def H(level, text):
    return ("h", level, text)


def P(text):
    return ("p", text)


def UL(items):
    return ("ul", [s(i) for i in items])


def T(headers, rows, pill_cols=()):
    return ("table", list(headers), [[s(c, "—") for c in r] for r in rows], set(pill_cols))


def MISSING(key):
    return ("missing", missing(key))


# ---------- 절 조립 ----------
def sec_summary(cmp, prov):
    out = [H(2, SECTION_TITLES[0])]
    if not isinstance(cmp, dict):
        out.append(MISSING("comparison"))
        if prov:
            cnt = Counter(s((p.get("provisional") or {}).get("expected_direction"), "미기재") for p in as_list(prov, "verdicts", "items"))
            out.append(P(f"참고: L0 잠정 판정 {sum(cnt.values())}건이 있다(예상 방향 기준)."))
            out.append(T(["예상 방향", "건수"], [[k, v] for k, v in cnt.items()]))
        return out
    rows = as_list(cmp.get("conclusion_rows"))
    summary = cmp.get("summary") if isinstance(cmp.get("summary"), dict) else {}
    if not summary:
        summary = Counter((r.get("verdict") or "잠정") for r in rows)
    total = len(rows)
    out.append(P(f"결론 {total}건(원 연구 결론 + 신규결론)에 대한 판정 분포. 성숙도 {s(cmp.get('maturity'), '미기재')} · 비교 생성일 {s(cmp.get('generated_at'), '미기재')}."))
    ordered = [(k, summary.get(k, 0)) for k in VERDICT_ORDER] + [(k, v) for k, v in summary.items() if k not in VERDICT_ORDER]
    out.append(T(["판정", "건수"], [[k, v] for k, v in ordered], pill_cols={0}))
    picks = sorted(rows, key=lambda r: VERDICT_PRIORITY.get(r.get("verdict") or "", 9))[:3]
    if picks:
        out.append(H(3, "핵심 3건 (뒤집힘 → 신규결론 → 판정불가 순)"))
        out.append(T(["결론", "판정", "현행화(안) 요지", "왜 달라졌나", "등급", "상태", "다음 조치"],
                     [[f"{r.get('row_id', '')} ({r.get('kind', '')})", r.get("verdict") or "잠정", clip(r.get("new"), 260),
                       f"{'/'.join(r.get('reason_locus') or [])} · {clip(r.get('reason'), 220)}", r.get("grade"), r.get("status"), next_action(r)]
                      for r in picks], pill_cols={1}))
    return out


def sec_overview(meta, cls, chains):
    out = [H(2, SECTION_TITLES[1])]
    if not isinstance(cls, dict) and not isinstance(meta, dict):
        out.append(MISSING("classification"))
    else:
        meta = meta if isinstance(meta, dict) else {}
        cls = cls if isinstance(cls, dict) else {}
        rd = cls.get("research_design") if isinstance(cls.get("research_design"), dict) else {}
        kv = [["제목", cls.get("title") or meta.get("title")], ["발행", cls.get("published") or meta.get("published")],
              ["발행·수행기관", cls.get("publisher")], ["원문", f"{s(meta.get('source_pdf'))} ({s(meta.get('pages'))}쪽)" if meta else ""],
              ["도메인", cls.get("domains")], ["유형 혼합", cls.get("type_mix")]]
        out.append(T(["항목", "내용"], [r for r in kv if s(r[1])]))
        if rd:
            out.append(H(3, "연구질문(RQ)"))
            out.append(P(s(rd.get("rq"), "(미기재)")))
            for key, title in (("methods", "방법"), ("data", "데이터"), ("limits", "원 연구가 밝힌 한계")):
                if rd.get(key):
                    out.append(H(3, title))
                    out.append(UL(as_list(rd.get(key))))
            if rd.get("sample"):
                out.append(P("표본·범위: " + s(rd["sample"])))
        elif not isinstance(cls, dict) or not cls:
            out.append(P(missing("classification")))
    out.append(H(3, "논증 사슬(결론 → 방법 → 전제·근거)"))
    if not isinstance(chains, dict):
        out.append(MISSING("chains"))
        return out
    concl = as_list(chains.get("conclusions"))
    out.append(P(f"결론 {len(concl)}개 · 전제 {len(as_list(chains.get('premises')))}개 · 주장(근거 항목) {len(as_list(chains.get('claims')))}개 · 연결 {len(as_list(chains.get('edges')))}개."))
    out.append(T(["결론 ID", "종류", "쪽(인쇄)", "결론 문장(원문 요지)", "방법", "전제 수", "근거 수", "재수행"],
                 [[c.get("conclusion_id"), c.get("kind"), f"{s(c.get('page'))}({s(c.get('printed_page'))})", clip(c.get("statement"), 220),
                   clip(c.get("method"), 120), len(as_list(c.get("premises"))), len(as_list(c.get("evidence_refs"))), c.get("rerun_grade")]
                  for c in concl]))
    return out


def sec_environment(events, delta_md):
    out = [H(2, SECTION_TITLES[2])]
    ev = as_list(events, "events", "items")
    if events is None:
        out.append(MISSING("events"))
        return out
    dom = Counter(s(e.get("domain"), "미기재") for e in ev)
    gr = Counter(s(e.get("grade"), "미표기") for e in ev)
    out.append(P(f"발간 이후 사건 {len(ev)}건. 도메인: " + ", ".join(f"{k} {v}" for k, v in dom.items()) + " · 등급: " + ", ".join(f"{k} {v}" for k, v in sorted(gr.items())) + "."))
    rows = []
    for e in sorted(ev, key=lambda x: s(x.get("date"))):
        srcs = [x for x in as_list(e.get("sources")) if isinstance(x, dict)]
        src_txt = " · ".join(link(clip(x.get("title") or x.get("url"), 50), x.get("url")) for x in srcs[:2])
        if len(srcs) > 2:
            src_txt += f" 외 {len(srcs) - 2}건"
        rows.append([e.get("date"), clip(e.get("title"), 200), e.get("affected_indicators"), e.get("grade"), src_txt or e.get("source")])
    out.append(T(["날짜", "사건", "영향 지표", "등급", "출처"], rows))
    if delta_md:
        out.append(P("서술형 타임라인·제외 항목·확인 실패 목록은 `L0/environment_delta.md` 참조(확인 실패 항목은 8절 부록에 옮겨 실었다)."))
    return out


def sec_comparison(cmp):
    out = [H(2, SECTION_TITLES[3])]
    if not isinstance(cmp, dict):
        out.append(MISSING("comparison"))
        return out
    rows = as_list(cmp.get("conclusion_rows"))
    out.append(P("판정 어휘: 동일·강화·부분수정·약화·뒤집힘·신규결론·판정불가. 왜 = 달라진 이유의 위치(P 전제 / E 근거 / M 방법). "
                 "\"현행(원 보고서)\" 열은 원문 요지이며 바꾸지 않았다. 등급 A 1차·공식 / B 2차 / C 추정·시뮬레이션·블라인드 결론."))
    out.append(T(["결론 · 위치", "현행 (원 보고서)", "현행화(안) · 추적 재도출", "블라인드 재수행", "판정", "왜", "등급", "상태", "다음 조치"],
                 [[f"{s(r.get('row_id'))} ({s(r.get('kind'))}) · {s(r.get('location'))}", r.get("old"), r.get("new"), r.get("blind_new") or "—",
                   r.get("verdict") or "잠정", f"{'/'.join(r.get('reason_locus') or [])} · {s(r.get('reason'))}", r.get("grade"), r.get("status"), next_action(r)]
                  for r in rows], pill_cols={4}))
    return out


def sec_verify(verdicts):
    out = [H(2, SECTION_TITLES[4])]
    if verdicts is None:
        out.append(MISSING("verdicts"))
        return out
    vs = as_list(verdicts, "verdicts", "items")
    cnt = Counter(s(v.get("verdict"), "미기재") for v in vs)
    lv = Counter(s(v.get("level"), "미기재") for v in vs)
    out.append(P(f"검증 항목 {len(vs)}건(" + ", ".join(f"{k} {v}" for k, v in lv.items()) + "). 판정: " + ", ".join(f"{k} {v}" for k, v in cnt.items()) + ". 오차(%) = (현재 − 원) / 원, 예측형 주장에만 기재."))
    rows = []
    for v in vs:
        ov = v.get("original_value") if isinstance(v.get("original_value"), dict) else {}
        cv = v.get("current_value") if isinstance(v.get("current_value"), dict) else {}
        evs = as_list(v.get("evidence"))
        rows.append([v.get("claim_id"), v.get("conclusion_id"), v.get("level"), ov.get("metric") or clip(v.get("statement"), 60) or "—",
                     value_with_unit(ov), value_with_unit(cv), s(v.get("error_pct"), "—"), v.get("verdict"), clip(v.get("reason"), 200),
                     f"{len(evs)}건 {best_grade(evs)}".strip()])
    out.append(T(["주장 ID", "결론 ID", "수준", "지표", "원 값", "현재 값(기준시점)", "오차 %", "판정", "사유", "근거 수·최고등급"], rows, pill_cols={7}))
    return out


def series_table(series):
    """{계열: {연도: 값}} → 연도 열 표."""
    if not isinstance(series, dict) or not series:
        return None
    years = sorted({y for v in series.values() if isinstance(v, dict) for y in v})
    return T(["계열"] + [s(y) for y in years], [[k] + [(v.get(y) if isinstance(v, dict) else None) for y in years] for k, v in series.items()])


def sec_rerun(traced, blind, cmp):
    out = [H(2, SECTION_TITLES[5])]
    out.append(H(3, "트랙 A · 추적 재도출 (원 방법 + 오늘 값)"))
    if traced is None:
        out.append(MISSING("traced"))
    else:
        tr = as_list(traced, "traced", "conclusions", "items")
        out.append(P(f"재도출 {len(tr)}건. 등급은 모두 시뮬레이션(C)이며 입력값의 등급은 표에 따로 적었다."))
        for t in tr:
            out.append(H(4, f"{s(t.get('conclusion_id'))} · 등급 {s(t.get('grade'), '미표기')} · 달라진 위치 {'/'.join(as_list(t.get('changed_locus'))) or '—'}"))
            out.append(P("적용 방법: " + s(t.get("method_applied"), "(미기재)")))
            inp = [i for i in as_list(t.get("inputs_now")) if isinstance(i, dict)]
            if inp:
                out.append(T(["입력", "값", "단위", "기준시점", "등급", "출처"],
                             [[i.get("name"), i.get("value"), i.get("unit"), i.get("asof"), i.get("grade"), link(clip(i.get("source_url"), 60), i.get("source_url") if s(i.get("source_url")).startswith("http") else "")] for i in inp]))
            out.append(P("재도출 결과: " + s(t.get("rederived"), "(미기재)")))
            out.append(P("원 결론 대비: " + s(t.get("delta_vs_original"), "(미기재)")))
            st = series_table(t.get("series"))
            if st:
                out.append(st)
            if t.get("calc_note"):
                out.append(P("계산 메모: " + s(t["calc_note"])))
    out.append(H(3, "트랙 B · 블라인드 재수행 (원 결론·원문 없이)"))
    if blind is None:
        out.append(MISSING("blind"))
    else:
        bl = as_list(blind, "blind", "items", "conclusions")
        items = [b for b in bl if isinstance(b, dict) and b.get("item_id")]
        iso = [b for b in bl if isinstance(b, dict) and "files_opened" in b]
        if iso:
            files = as_list(iso[0].get("files_opened"))
            leak = [f for f in files if any(x in s(f) for x in ("00_source", "03_argument_chains", "comparison_table", "L2/traced", "L1/", "L0/"))]
            out.append(P(f"격리 확인 · files_opened {len(files)}개: " + ", ".join(f"`{s(f)}`" for f in files) +
                         (" → 원문·비교·재도출 산출물 접근 없음(격리 유지)." if not leak else f" → 경고: 원문/산출물 접근 흔적 {', '.join(map(str, leak))}.")))
            if iso[0].get("note"):
                out.append(P("에이전트 기록: " + s(iso[0]["note"])))
        else:
            out.append(P("격리 확인 · files_opened 항목이 산출물에 없음 → 격리 여부 미확인(블라인드 실행 로그 점검 필요)."))
        mapping = ((cmp or {}).get("l2_compare") or {}).get("blind_mapping") if isinstance(cmp, dict) else None
        out.append(T(["항목", "질문", "블라인드 결론", "확신", "등급", "입력 수", "대응 결론(비교기 매핑)"],
                     [[b.get("item_id"), clip(b.get("question"), 120), clip(b.get("conclusion"), 320), b.get("confidence"), b.get("grade"), len(as_list(b.get("inputs"))),
                       s((mapping or {}).get(s(b.get("item_id"))), "—")] for b in items]))
        cav = [(b.get("item_id"), c) for b in items for c in as_list(b.get("caveats"))]
        if cav:
            out.append(H(4, "블라인드 에이전트가 밝힌 유의점"))
            out.append(UL([f"{i}: {c}" for i, c in cav]))
    if isinstance(cmp, dict) and isinstance(cmp.get("l2_compare"), dict):
        lc = cmp["l2_compare"]
        out.append(H(3, "비교기 규칙·입력"))
        out.append(P("규칙: " + s(lc.get("rules"), "(미기재)")))
        if lc.get("inputs"):
            out.append(UL(as_list(lc.get("inputs"))))
        if lc.get("notes"):
            out.append(P("판정 노트: " + s(lc["notes"])))
    return out


def sec_implications(cmp):
    out = [H(2, SECTION_TITLES[6])]
    if not isinstance(cmp, dict):
        out.append(MISSING("comparison"))
        return out
    rows = [r for r in as_list(cmp.get("conclusion_rows")) if (r.get("verdict") or "") in ("신규결론", "뒤집힘")]
    if not rows:
        out.append(P("해당 없음 — 신규결론·뒤집힘 판정이 없다."))
        return out
    out.append(P(f"신규결론·뒤집힘 {len(rows)}건에서 도출. 문장은 비교기(comparison_table.json)의 현행화(안)·판정 사유를 그대로 옮겼고, 근거 ID·등급을 함께 적었다."))
    for r in rows:
        out.append(H(3, f"{s(r.get('row_id'))} · {s(r.get('verdict'))} · {s(r.get('kind'))} · 등급 {s(r.get('grade'), '미표기')}"))
        out.append(P("시사점: " + s(r.get("new"), "(미기재)")))
        out.append(P("근거·판정 사유: " + s(r.get("reason"), "(미기재)")))
        evs = [e for e in as_list(r.get("evidence")) if isinstance(e, dict)]
        if evs:
            out.append(UL([f"[{s(e.get('grade'), '-')}] {link(clip(e.get('note') or e.get('title') or e.get('url'), 110), e.get('url') if s(e.get('url')).startswith('http') else '')}" for e in evs]))
        if r.get("upstream"):
            out.append(P("연결 전제·사건: " + s(r["upstream"])))
    return out


def collect_evidence(cmp, events, verdicts, traced, blind):
    """모든 산출물의 근거 항목을 (url, grade) 목록으로 모은다."""
    evs = []
    if isinstance(cmp, dict):
        for r in as_list(cmp.get("conclusion_rows")) + as_list(cmp.get("body_rows")):
            evs += [(e.get("url"), e.get("grade")) for e in as_list(r.get("evidence")) if isinstance(e, dict)]
    for e in as_list(events, "events", "items"):
        evs += [(x.get("url"), e.get("grade")) for x in as_list(e.get("sources")) if isinstance(x, dict)]
    for v in as_list(verdicts, "verdicts", "items"):
        evs += [(e.get("url"), e.get("grade")) for e in as_list(v.get("evidence")) if isinstance(e, dict)]
    for t in as_list(traced, "traced", "conclusions", "items"):
        evs += [(i.get("source_url"), i.get("grade")) for i in as_list(t.get("inputs_now")) if isinstance(i, dict)]
    for b in as_list(blind, "blind", "items", "conclusions"):
        evs += [(i.get("source_url"), i.get("grade")) for i in as_list(b.get("inputs")) if isinstance(i, dict)]
    return evs


def unverified_from_delta(delta_md):
    """environment_delta.md 의 '확인 실패' 절에서 항목 줄만 뽑는다."""
    if not delta_md:
        return []
    items, on = [], False
    for line in delta_md.splitlines():
        if line.startswith("## "):
            on = "확인 실패" in line
            continue
        if on and re.match(r"^\s*(\d+\.|-)\s+", line):
            items.append(re.sub(r"^\s*(\d+\.|-)\s+", "", line).strip())
    return items


def sec_appendix(cmp, events, verdicts, traced, blind, delta_md, present):
    out = [H(2, SECTION_TITLES[7])]
    out.append(H(3, "8.1 본문 대조표 (환경분석·현황 절)"))
    if not isinstance(cmp, dict):
        out.append(MISSING("comparison"))
    else:
        brows = as_list(cmp.get("body_rows"))
        if not brows:
            out.append(P("본문 대조표 행이 없다."))
        else:
            out.append(T(["위치", "현행", "현행화(안)", "변경유형", "사유", "등급", "상태", "연결 결론"],
                         [[f"{s(r.get('row_id'))} · {s(r.get('location'))}", r.get("old"), r.get("new"), r.get("change_type"), r.get("reason"),
                           r.get("grade"), r.get("status"), r.get("linked_conclusions")] for r in brows]))
    out.append(H(3, "8.2 사용한 소스·등급 통계"))
    evs = collect_evidence(cmp, events, verdicts, traced, blind)
    if not evs:
        out.append(P("집계할 근거 항목이 없다."))
    else:
        gr = Counter(s(g, "미표기") for _, g in evs)
        urls = [s(u) for u, _ in evs if s(u)]
        hosts = Counter(urlparse(u).netloc if u.startswith("http") else "(내부 산출물)" for u in urls)
        out.append(P(f"근거 항목 {len(evs)}건, 고유 URL·경로 {len(set(urls))}개. 등급: " + ", ".join(f"{k} {v}" for k, v in sorted(gr.items())) + "."))
        out.append(T(["출처(호스트)", "인용 횟수"], hosts.most_common(20)))
    out.append(H(3, "8.3 미확인 항목"))
    items = []
    if isinstance(cmp, dict):
        items += [f"{s(r.get('row_id'))} · {s(r.get('verdict')) or '잠정'} · {s(r.get('status'))} — {clip(r.get('reason'), 180)}"
                  for r in as_list(cmp.get("conclusion_rows")) if (r.get("verdict") or "") in ("판정불가", "")]
    items += [f"{s(v.get('claim_id'))} · 검증불가 — {clip((v.get('original_value') or {}).get('metric') if isinstance(v.get('original_value'), dict) else '', 60)} {clip(v.get('reason'), 150)}"
              for v in as_list(verdicts, "verdicts", "items") if s(v.get("verdict")) == "검증불가"]
    items += [f"블라인드 {s(b.get('item_id'))} · 확신 낮음 — {clip(b.get('conclusion'), 150)}"
              for b in as_list(blind, "blind", "items", "conclusions") if isinstance(b, dict) and s(b.get("confidence")) == "낮음"]
    items += [f"L0 확인 실패 — {clip(x, 220)}" for x in unverified_from_delta(delta_md)]
    out.append(UL(items) if items else P("해당 없음."))
    out.append(H(3, "8.4 입력 산출물 존재 여부"))
    out.append(T(["입력", "경로", "상태"], [[INPUTS[k][1], INPUTS[k][0], "있음" if present.get(k) else "없음"] for k in INPUTS]))
    return out


# ---------- 렌더러 ----------
def md_cell(text: str) -> str:
    return s(text, "—").replace("|", "｜").replace("\r", " ").replace("\n", " ").strip() or "—"


def to_markdown(title_line: str, sub: str, blocks) -> str:
    lines = [f"# {title_line}", "", sub, ""]
    lines += ["목차: " + " · ".join(SECTION_TITLES), ""]
    for b in blocks:
        kind = b[0]
        if kind == "h":
            lines += ["#" * b[1] + " " + b[2], ""]
        elif kind == "p":
            lines += [b[1], ""]
        elif kind == "missing":
            lines += [f"**{b[1]}**", ""]
        elif kind == "ul":
            lines += [f"- {md_cell(i)}" for i in b[1]] + [""]
        elif kind == "table":
            _, headers, rows, _ = b
            lines.append("| " + " | ".join(md_cell(h) for h in headers) + " |")
            lines.append("|" + "---|" * len(headers))
            lines += ["| " + " | ".join(md_cell(c) for c in r) + " |" for r in rows]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")


def inline_html(text: str) -> str:
    t = html.escape(s(text, "—"))
    t = _LINK.sub(lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>', t)
    t = _BOLD.sub(r"<b>\1</b>", t)
    t = _CODE.sub(r"<code>\1</code>", t)
    return t.replace("\n", "<br>")


def pill(v: str) -> str:
    return f'<span class="pill p-{VERDICT_CLASS.get(v, "na")}">{html.escape(v or "잠정")}</span>'


def to_html(title_line: str, sub: str, blocks) -> str:
    body, sec_no = [], 0
    for b in blocks:
        kind = b[0]
        if kind == "h":
            attr = ""
            if b[1] == 2:
                sec_no += 1
                attr = f' id="sec{sec_no}"'
            body.append(f"<h{b[1]}{attr}>{inline_html(b[2])}</h{b[1]}>")
        elif kind == "p":
            body.append(f"<p>{inline_html(b[1])}</p>")
        elif kind == "missing":
            body.append(f'<p class="missing">{html.escape(b[1])}</p>')
        elif kind == "ul":
            body.append("<ul>" + "".join(f"<li>{inline_html(i)}</li>" for i in b[1]) + "</ul>")
        elif kind == "table":
            _, headers, rows, pill_cols = b
            old_col = next((i for i, h in enumerate(headers) if h.startswith("현행 ") or h == "현행"), None)
            trs = []
            for r in rows:
                tds = []
                for i, c in enumerate(r):
                    if i in pill_cols:
                        tds.append(f"<td>{pill(c if c != '—' else '')}</td>")
                    else:
                        cls = ' class="old"' if i == old_col else ""
                        tds.append(f"<td{cls}>{inline_html(c)}</td>")
                trs.append("<tr>" + "".join(tds) + "</tr>")
            body.append('<div class="tw"><table><thead><tr>' + "".join(f"<th>{html.escape(h)}</th>" for h in headers) +
                        "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div>")
    toc = "".join(f'<a href="#sec{i + 1}">{html.escape(t)}</a>' for i, t in enumerate(SECTION_TITLES))
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>현행화 보고서 · {html.escape(title_line)}</title><style>{CSS}</style></head><body><div class=\"wrap\">"
            f"<h1>현행화 보고서 · {inline_html(title_line)}</h1><p class=\"sub\">{inline_html(sub)}</p><nav class=\"toc\">{toc}</nav>"
            + "".join(body) +
            '<p class="note" style="margin-top:28px">등급 A 1차·공식(정부·법령·표준·학술지) / B 2차(언론·업계) / C 추정·시뮬레이션·블라인드 결론. '
            '모든 수치는 단계별 JSON 산출물에서 그대로 옮겼으며 이 문서에서 새로 만든 수치는 없다.</p></div></body></html>')


# ---------- 진입점 ----------
def build(rid: str, root: Path):
    base = root / "reports" / rid
    data, present = {}, {}
    for key, (rel, _) in INPUTS.items():
        p = base / rel
        data[key] = load_text(p) if key == "delta_md" else load_json(p)
        present[key] = data[key] is not None
    meta = data["meta"] if isinstance(data["meta"], dict) else {}
    cmp = data["comparison"] if isinstance(data["comparison"], dict) else {}
    cls = data["classification"] if isinstance(data["classification"], dict) else {}
    title = s(meta.get("title") or cmp.get("title") or cls.get("title"), rid)
    published = s(meta.get("published") or cmp.get("published") or cls.get("published"), "미기재")
    sub = (f"보고서 {rid} · 발간 {published} · 비교 생성 {s(cmp.get('generated_at'), '—')} · 성숙도 {s(cmp.get('maturity'), '—')} · "
           f"렌더 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 입력 {sum(present.values())}/{len(INPUTS)}개 확인")
    blocks = []
    blocks += sec_summary(data["comparison"], data["provisional"])
    blocks += sec_overview(data["meta"], data["classification"], data["chains"])
    blocks += sec_environment(data["events"], data["delta_md"])
    blocks += sec_comparison(data["comparison"])
    blocks += sec_verify(data["verdicts"])
    blocks += sec_rerun(data["traced"], data["blind"], data["comparison"])
    blocks += sec_implications(data["comparison"])
    blocks += sec_appendix(data["comparison"], data["events"], data["verdicts"], data["traced"], data["blind"], data["delta_md"], present)
    return title, sub, blocks


def main(rid: str, root: Path = None) -> int:
    root = Path(root) if root else ROOT
    title, sub, blocks = build(rid, root)
    out_dir = root / "reports" / rid / "07_report"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path, html_path = out_dir / "report.md", out_dir / "report.html"
    md_path.write_text(to_markdown(title, sub, blocks), encoding="utf-8")
    html_path.write_text(to_html(title, sub, blocks), encoding="utf-8")
    print(md_path)
    print(html_path)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python scripts/render_report.py <report_id>", file=sys.stderr)
        sys.exit(2)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1]))
