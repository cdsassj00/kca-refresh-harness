"""신구 대조표 렌더: reports/<id>/comparison_table.json -> 07_report/comparison_table.html
사용: python scripts/render_table.py R01
"""
import html, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERDICT_CLASS = {"동일": "good", "강화": "good", "부분수정": "warn", "약화": "warn", "뒤집힘": "bad",
                 "신규결론": "new", "판정불가": "na", "": "na"}
# 사람의 승인 게이트(선택 필드). 없는 데이터에서도 그대로 렌더된다.
COMPARABILITY_CLASS = {"직접비교 가능": "good", "대체지표 비교": "warn", "비교 불가": "bad"}
APPROVAL_CLASS = {"승인": "good", "보류": "warn", "반려": "bad"}
NOT_APPROVED = "미승인"

CSS = """
:root{--bg:#F4F6F9;--surface:#fff;--ink:#1A2330;--muted:#5E6B7A;--line:#D5DCE5;--accent:#0B6E8F;--accent-soft:#DCEEF4;
--good:#2E7D4F;--good-soft:#DFF2E6;--warn:#A8690E;--warn-soft:#FBEFD6;--bad:#B93A2B;--bad-soft:#FBE3DF;--na:#6F7C8A;--na-soft:#E8ECF0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0E141B;--surface:#151D26;--ink:#E7EDF3;--muted:#9AA7B5;--line:#2A3542;
--accent:#4FB3D4;--accent-soft:#123A48;--good:#5FCB8A;--good-soft:#163425;--warn:#E2B14A;--warn-soft:#3A2E12;--bad:#F07A6A;--bad-soft:#3F1F1B;--na:#8E9BA8;--na-soft:#232C36}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans KR","Noto Sans KR","Malgun Gothic",sans-serif;font-size:14.5px;line-height:1.55}
.wrap{max-width:1180px;margin:0 auto;padding:36px 20px 80px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 12px}.sub{color:var(--muted);margin:0 0 18px}
.sum{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 6px}.sum span{padding:6px 12px;border-radius:999px;font-weight:700;font-size:13px}
.p-good{background:var(--good-soft);color:var(--good)}.p-warn{background:var(--warn-soft);color:var(--warn)}.p-bad{background:var(--bad-soft);color:var(--bad)}
.p-na{background:var(--na-soft);color:var(--na)}.p-new{background:var(--accent-soft);color:var(--accent)}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12.5px;font-weight:700;white-space:nowrap}
.filters{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 10px;font-size:13px}.filters select{font:inherit;padding:4px 8px}
.tw{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px 12px}
table{width:100%;border-collapse:collapse;min-width:1000px}#ctab{min-width:1420px}th,td{border-top:1px solid var(--line);padding:10px 8px;vertical-align:top;text-align:left}
th{font-size:12px;letter-spacing:.06em;color:var(--muted);font-weight:500;border-top:0}td.k{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--muted);white-space:nowrap}
td.old{background:var(--na-soft)}td.g{font-family:"IBM Plex Mono",monospace;text-align:center}.ev a{color:var(--accent);font-size:12.5px;display:block}
.why{color:var(--muted);font-size:13px}.loc{font-size:12px;color:var(--muted)}
"""

JS = """
document.querySelectorAll('select[data-col]').forEach(s=>s.addEventListener('change',()=>{
  const f=[...document.querySelectorAll('select[data-col]')].map(x=>[x.dataset.col,x.value]);
  document.querySelectorAll('#ctab tbody tr').forEach(tr=>{tr.hidden=!f.every(([c,v])=>!v||tr.dataset[c]===v);});
}));
"""

def pill(v):
    return f'<span class="pill p-{VERDICT_CLASS.get(v, "na")}">{html.escape(v or "잠정")}</span>'

def ev_links(evs):
    out = []
    for e in evs or []:
        u = e.get("url", ""); g = e.get("grade", ""); n = e.get("note") or e.get("title") or ""
        label = html.escape((n or u)[:60]) + (f" [{g}]" if g else "")
        out.append(f'<a href="{html.escape(u)}" target="_blank" rel="noopener">{label}</a>' if u else html.escape(label))
    return "".join(out)

def badge(text, cls="na"):
    return f'<span class="pill p-{cls}">{html.escape(text)}</span>'

def why(text):
    return f'<div class="why">{html.escape(text)}</div>' if text else ""

def comparability_cell(r):
    """비교가능성. 필드가 없으면 '미기재'."""
    v = r.get("comparability") or ""
    return badge(v or "미기재", COMPARABILITY_CLASS.get(v, "na")) + why(r.get("comparability_note") or "")

def method_cell(r):
    """방법변경. boolean이 없으면 '미기재'."""
    mc = r.get("method_changed")
    label, cls = ("미기재", "na") if mc is None else (("변경", "warn") if mc else ("원 방법 유지", "good"))
    return badge(label, cls) + why(r.get("method_change_note") or "")

def floor_text(r):
    ok = r.get("evidence_floor_ok")
    return "근거하한 미기재" if ok is None else ("근거하한 확인(A/B 있음)" if ok else "근거하한 미충족(C등급만)")

def approval_decision(r):
    """승인 결정 문자열. 비어 있으면 '미승인'."""
    a = r.get("approval")
    if not isinstance(a, dict):
        return NOT_APPROVED
    return a.get("decision") or (NOT_APPROVED if not a.get("approver") else "기록")

def approval_cell(r):
    """승인 칸: 비어 있으면 회색 '미승인' 배지, 있으면 승인자·시각·결정."""
    a = r.get("approval") if isinstance(r.get("approval"), dict) else {}
    dec = approval_decision(r)
    if dec == NOT_APPROVED:
        return badge(NOT_APPROVED, "na") + why(floor_text(r))
    meta = " · ".join(x for x in (a.get("approver") or "", a.get("approved_at") or "") if x)
    return (badge(dec, APPROVAL_CLASS.get(dec, "na")) + why(meta) +
            why(a.get("comment") or "") + why(floor_text(r)))

def main(rid: str) -> int:
    p = ROOT / "reports" / rid / "comparison_table.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    s = d.get("summary", {})
    sum_html = "".join(f'<span class="p-{VERDICT_CLASS.get(k, "na")}">{html.escape(k)} {v}</span>' for k, v in s.items() if v)
    verdicts = sorted({r.get("verdict") or "" for r in d["conclusion_rows"]})
    kinds = sorted({r.get("kind", "") for r in d["conclusion_rows"]})
    approvals = sorted({approval_decision(r) for r in d["conclusion_rows"]})
    opt = lambda vals: "".join(f'<option value="{html.escape(v)}">{html.escape(v or "(잠정)")}</option>' for v in vals)
    rows = []
    for r in d["conclusion_rows"]:
        rows.append(f"""<tr data-verdict="{html.escape(r.get('verdict') or '')}" data-kind="{html.escape(r.get('kind',''))}" data-approval="{html.escape(approval_decision(r))}">
<td class="k">{html.escape(r['row_id'])}<div class="loc">{html.escape(r.get('location',''))}</div></td>
<td class="old">{html.escape(r.get('old',''))}</td>
<td>{html.escape(r.get('new',''))}</td>
<td>{html.escape(r.get('blind_new','') or '—')}</td>
<td>{pill(r.get('verdict',''))}<div class="why">{html.escape('/'.join(r.get('reason_locus',[])))} · {html.escape(r.get('reason',''))}</div></td>
<td>{comparability_cell(r)}</td>
<td>{method_cell(r)}</td>
<td class="ev">{ev_links(r.get('evidence'))}</td>
<td class="g">{html.escape(r.get('grade',''))}</td><td>{html.escape(r.get('status',''))}</td>
<td>{approval_cell(r)}</td></tr>""")
    brows = []
    for r in d.get("body_rows", []):
        brows.append(f"""<tr><td class="k">{html.escape(r['row_id'])}<div class="loc">{html.escape(r.get('location',''))}</div></td>
<td class="old">{html.escape(r.get('old',''))}</td><td>{html.escape(r.get('new',''))}</td>
<td>{html.escape(r.get('change_type',''))}<div class="why">{html.escape(r.get('reason',''))}</div></td>
<td class="ev">{ev_links(r.get('evidence'))}</td><td class="g">{html.escape(r.get('grade',''))}</td>
<td>{html.escape(r.get('status',''))}<div class="loc">{html.escape(', '.join(r.get('linked_conclusions',[])))}</div></td></tr>""")
    page = f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>신구 대조표 · {html.escape(rid)}</title><style>{CSS}</style><div class="wrap">
<h1>신구 대조표 · {html.escape(d.get('title',''))}</h1>
<p class="sub">{html.escape(rid)} · 발간 {html.escape(d.get('published',''))} · 생성 {html.escape(d.get('generated_at',''))} · 성숙도 {html.escape(d.get('maturity',''))}</p>
<div class="sum">{sum_html}</div>
<h2>결론 대조표</h2>
<div class="filters">판정 <select data-col="verdict"><option value="">전체</option>{opt(verdicts)}</select>
종류 <select data-col="kind"><option value="">전체</option>{opt(kinds)}</select>
승인 <select data-col="approval"><option value="">전체</option>{opt(approvals)}</select></div>
<div class="tw"><table id="ctab"><thead><tr><th>결론</th><th>현행 (원 보고서)</th><th>현행화(안) · 추적 재도출</th><th>블라인드 재수행</th><th>판정 · 왜</th><th>비교가능성</th><th>방법변경</th><th>근거</th><th>등급</th><th>상태</th><th>승인</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>본문 대조표 (환경분석·현황 절)</h2>
<div class="tw"><table><thead><tr><th>위치</th><th>현행</th><th>현행화(안)</th><th>변경</th><th>근거</th><th>등급</th><th>상태 · 연결 결론</th></tr></thead>
<tbody>{''.join(brows)}</tbody></table></div>
<p class="sub" style="margin-top:20px">등급 A 공식 통계·법령·학술지 / B 언론·업계 / C 추정·시뮬레이션·블라인드 결론. "현행" 열은 원문 요지이며 바꾸지 않았다.<br>
비교가능성·방법변경은 비교기가 채우고, 승인은 사람이 채운다. 회색 "미승인"은 아직 사람이 확인하지 않았다는 뜻이다(판정이 틀렸다는 뜻이 아니다).</p>
</div><script>{JS}</script></html>"""
    out = ROOT / "reports" / rid / "07_report" / "comparison_table.html"
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(page, encoding="utf-8")
    print(out); return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
