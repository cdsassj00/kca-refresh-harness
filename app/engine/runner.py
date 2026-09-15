"""단계 실행기. DESIGN.md 5절.

run_stage: 한 단계를 실행한다(재개 규칙 → 파이썬 단계 또는 LLM 도구 루프 → 최종 JSON 파싱·검증 → 파일 쓰기).
run_pipeline: run_config 로 단계 목록을 정해 순서대로 run_stage 를 부른다(취소·진행 이벤트·로그).

- 재개: outputs 가 모두 있으면 건너뜀. force_from 단계부터는 강제 재실행(기존 파일은 .bak.<시각> 으로 보관).
- 루프: system + user(프롬프트 전문 + 인라인 입력 + 출력 지시) → chat(tools) → tool_calls 실행 → 반복(max_steps)
  → tool_calls 없으면 content 를 JSON 으로 파싱.
- 검증: 파싱 실패·키 누락·스키마 오류면 오류 목록을 담아 "고쳐서 다시 JSON만" 재요청, 최대 2회. 실패 시 파일을 쓰지 않는다.
- 블라인드(isolated): 대화에 브리프 파일 외 어떤 보고서 파일도 넣지 않고, files_opened 원소를 강제로 붙인다.
"""
from __future__ import annotations
import contextlib
import io
import json
import re
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import config
from engine import brief as brief_mod
from engine.llm import LLMClient, LLMError
from engine.stages import STAGE_ORDER, StageSpec, get_stage, stages_for
from engine.tools import ToolRegistry

SYSTEM_PROMPT_PATH = Path(__file__).with_name("system_prompt.md")
MAX_REPAIRS = 2
CORE_PREFIXES = ("kb/", "templates/")
VERDICT_KEYS = ["동일", "강화", "부분수정", "약화", "뒤집힘", "신규결론", "판정불가", "잠정"]


class StageError(Exception):
    """단계 실패(입력 없음·형식 오류·검증 실패)."""


class CancelledError(Exception):
    """사용자 취소."""


@dataclass
class StageResult:
    stage: str
    status: str = "done"          # done | skipped | failed | cancelled
    outputs: list = field(default_factory=list)
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    error: str = ""
    started_at: str = ""
    ended_at: str = ""
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- 시각·로그 ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_str() -> str:
    return date.today().isoformat()


class JsonlLogger:
    """reports/<id>/logs/app_run.jsonl 한 줄 = {ts, stage, model, step, event, name?, tokens_in, tokens_out, cost_usd, note}"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def __call__(self, event: dict) -> None:
        row = {"ts": now_iso(), "stage": "", "model": "", "step": 0, "event": "", "tokens_in": 0,
               "tokens_out": 0, "cost_usd": 0.0, "note": ""}
        row.update(event or {})
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def make_logger(report_id: str) -> JsonlLogger:
    return JsonlLogger(config.report_dir(report_id) / "logs" / "app_run.jsonl")


def _noop_log(event: dict) -> None:
    return None


# ---------- 시스템 프롬프트·입력 인라인 ----------
def load_system_prompt(today: Optional[str] = None) -> str:
    text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return text.replace("{today}", today or today_str())


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_if(path: Path):
    try:
        return _read_json(path) if path.exists() else None
    except json.JSONDecodeError:
        return None


def head_with_toc(text: str, max_chars: int) -> str:
    """앞 max_chars 자 + 목차 페이지 탐지(상한 밖에 있으면 덧붙인다)."""
    head = text[:max_chars]
    m = re.search(r"(<!-- page (\d+) -->)[^<]{0,400}?(목\s*차|CONTENTS|Contents)", text)
    if m and m.start() >= max_chars:
        seg_start = m.start(1)
        nxt = text.find("<!-- page", seg_start + 10)
        seg = text[seg_start: nxt if nxt > 0 else seg_start + 6000][:6000]
        head += f"\n\n### 목차 탐지(page {m.group(2)})\n{seg}"
    if len(text) > max_chars:
        head += f"\n\n[... 원문 {len(text):,}자 중 앞 {max_chars:,}자만 인라인 ...]"
    return head


def premises_only(chains) -> dict:
    return {"report_id": chains.get("report_id", ""), "premises": chains.get("premises") or [],
            "conclusion_index": [{"conclusion_id": c.get("conclusion_id"), "kind": c.get("kind")}
                                 for c in chains.get("conclusions") or []]}


def _apply_transform(name: str, text: str, path: Path) -> str:
    if name == "premises_only" or name == "conclusions_only":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        fn = premises_only if name == "premises_only" else brief_mod.conclusions_only
        return json.dumps(fn(data), ensure_ascii=False, indent=1)
    return text


def _substitute(path: str, report_id: str, domains: list) -> list:
    """자리표시자 치환. <domain> 이 있으면 도메인마다 하나씩 돌려준다."""
    p = path.replace("<id>", report_id)
    if "<domain>" in p:
        return [p.replace("<domain>", d) for d in domains] if domains else []
    return [p]


def _resolve_path(rel: str, report_id: str) -> Path:
    if rel.startswith(CORE_PREFIXES):
        return config.CORE_DIR / rel
    return config.report_dir(report_id) / rel


def _expand(rel: str, report_id: str) -> list:
    """glob(*) 이 있으면 파일 목록을, 아니면 그 경로 하나를 돌려준다. (표시용 상대경로, 실제 경로) 쌍."""
    base = config.CORE_DIR if rel.startswith(CORE_PREFIXES) else config.report_dir(report_id)
    if "*" in rel:
        parent = (base / rel).parent
        pattern = Path(rel).name
        if not parent.exists():
            return []
        found = sorted(parent.glob(pattern))
        return [(f"{rel.rsplit('/', 1)[0]}/{f.name}" if "/" in rel else f.name, f) for f in found if f.is_file()]
    return [(rel, base / rel)]


def _stage_context(report_id: str, spec: StageSpec, run_config: dict) -> dict:
    """메타·분류에서 도메인·발간·조사 기간을 뽑는다. 격리 단계에는 ID·오늘만 준다."""
    ctx = {"report_id": report_id, "today": today_str(), "domains": [], "published": "", "since": "", "until": ""}
    if spec.isolated:
        return ctx
    rd = config.report_dir(report_id)
    meta = _load_json_if(rd / "01_meta.json") or {}
    cls = _load_json_if(rd / "02_classification.json") or {}
    ctx["published"] = meta.get("published") or cls.get("published") or ""
    ctx["domains"] = [d for d in (cls.get("domains") or []) if isinstance(d, str)]
    ctx["title"] = meta.get("title") or cls.get("title") or ""
    period = (run_config or {}).get("period") or {}
    since = period.get("since") or ""
    if not since and ctx["published"] and re.match(r"^\d{4}-\d{2}", ctx["published"]):
        y, m = int(ctx["published"][:4]), int(ctx["published"][5:7])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        since = f"{y:04d}-{m:02d}"
    until = period.get("until") or "today"
    ctx["since"], ctx["until"] = since, (ctx["today"] if until == "today" else until)
    return ctx


def resolve_inputs(spec: StageSpec, report_id: str, settings: dict, ctx: dict) -> list:
    """[(표시 경로, 내용)] 을 돌려준다. 필수 입력이 없으면 StageError."""
    blocks = []
    max_source = int(settings.get("max_source_chars") or 120000)
    for raw in spec.inputs:
        rule = spec.input_rules.get(raw, {})
        for rel in _substitute(raw, report_id, ctx.get("domains") or []):
            if spec.isolated and not rel.startswith("L2/blind_input/"):
                raise StageError(f"격리 단계에 허용되지 않은 입력: {rel}")
            for label, path in _expand(rel, report_id):
                if not path.exists():
                    if raw in spec.required_inputs and "*" not in raw:
                        raise StageError(f"필수 입력 파일이 없습니다: {label}")
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                transform = rule.get("transform")
                limit = rule.get("max_chars")
                if limit == "max_source_chars":
                    limit = max_source
                if transform == "head_with_toc":
                    text = head_with_toc(text, int(limit or 30000))
                elif transform:
                    text = _apply_transform(transform, text, path)
                    label = f"{label} ({'premises 만' if transform == 'premises_only' else '결론 목록만'})"
                elif limit and len(text) > int(limit):
                    text = text[: int(limit)] + f"\n\n[... {len(text):,}자 중 앞 {int(limit):,}자만 인라인. 나머지는 read_report_file 로 읽을 것 ...]"
                blocks.append((label, text))
        if raw in spec.required_inputs and "*" in raw and not any(b[0].startswith(raw.split("*")[0]) for b in blocks):
            raise StageError(f"필수 입력 파일이 없습니다: {raw}")
    return blocks


def _output_kind(path: str) -> str:
    return "json" if path.endswith(".json") else "md"


def output_instructions(spec: StageSpec, tool_names: list) -> str:
    lines = ["## 출력 지시",
             "최종 응답은 아래 키를 **모두** 가진 JSON 객체 하나로만 답한다. 설명 문장·코드펜스를 붙이지 않는다. "
             "파일을 직접 쓰지 말고 값으로 돌려준다. 값이 JSON 파일이면 객체·배열(문자열로 감싸지 말 것), 마크다운이면 문자열."]
    vmap = {o: (s, sel) for o, s, sel in spec.validations}
    for o in spec.outputs:
        kind = "마크다운 문자열" if _output_kind(o) == "md" else "JSON 객체 또는 배열"
        note = ""
        if o in vmap:
            s, sel = vmap[o]
            note = f" (스키마 {s}" + (", 배열 원소마다" if sel == "[]" else (f", {sel} 의 원소마다" if sel else "")) + ")"
        lines.append(f'- "{o}": {kind}{note}')
    for o in spec.optional_outputs:
        lines.append(f'- "{o}": 선택. 있으면 함께 돌려준다({"JSON 객체" if _output_kind(o) == "json" else "문자열"}).')
    if tool_names:
        lines.append(f"사용 가능한 도구: {', '.join(tool_names)}. 근거는 도구 결과에서만 가져온다.")
    else:
        lines.append("이 단계에는 도구가 없다. 주어진 입력만으로 답한다.")
    return "\n".join(lines)


def build_user_message(report_id: str, spec: StageSpec, settings: dict, run_config: dict, tool_names: list) -> str:
    ctx = _stage_context(report_id, spec, run_config)
    head = [f"보고서 ID: {report_id} · 오늘: {ctx['today']} · 단계: {spec.name}"]
    if not spec.isolated:
        bits = []
        if ctx.get("title"):
            bits.append(f"제목: {ctx['title']}")
        if ctx.get("published"):
            bits.append(f"발간: {ctx['published']}")
        if ctx.get("domains"):
            bits.append(f"도메인: {', '.join(ctx['domains'])}")
        if ctx.get("since"):
            bits.append(f"조사 기간: {ctx['since']} ~ {ctx['until']}")
        if bits:
            head.append(" · ".join(bits))
    parts = ["\n".join(head)]
    if spec.prompt_file:
        prompt_text = (config.PROMPTS_DIR / spec.prompt_file).read_text(encoding="utf-8")
        parts.append(f"## 역할 지시서 (prompts/{spec.prompt_file})\n{prompt_text}")
    blocks = resolve_inputs(spec, report_id, settings, ctx)
    if blocks:
        parts.append("## 입력\n" + "\n\n".join(f"### 파일: {label}\n{text}" for label, text in blocks))
    else:
        parts.append("## 입력\n(인라인 입력 없음)")
    parts.append(output_instructions(spec, tool_names))
    return "\n\n".join(parts)


# ---------- 최종 JSON 파싱·검증 ----------
def parse_final_json(text: str):
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except ValueError:
            pass
    raise ValueError("응답에서 JSON 객체를 찾지 못했습니다")


def _match_key(obj: dict, path: str, report_id: str):
    """모델이 키를 'reports/R01/…' 처럼 돌려줘도 찾는다. 없으면 None."""
    if path in obj:
        return path
    cands = {path, f"reports/{report_id}/{path}", f"./{path}", path.replace("<id>", report_id)}
    for k in obj:
        kk = str(k).replace("\\", "/")
        norm = re.sub(rf"^(\./)?(reports/{report_id}/)?", "", kk)
        if kk in cands or norm == path:
            return k
    base = path.rsplit("/", 1)[-1]
    hits = [k for k in obj if str(k).replace("\\", "/").rsplit("/", 1)[-1] == base]
    return hits[0] if len(hits) == 1 else None


def normalize_outputs(spec: StageSpec, obj, report_id: str) -> tuple:
    """(outputs dict, errors list). JSON 출력이 문자열로 왔으면 풀고, 형식이 틀리면 오류로 적는다."""
    errors, outputs = [], {}
    if not isinstance(obj, dict):
        return {}, ["최종 응답이 JSON 객체가 아닙니다(키: 출력 파일 경로)"]
    for o in list(spec.outputs) + list(spec.optional_outputs):
        key = _match_key(obj, o, report_id)
        if key is None and o == "L2/compare/question_map.json" and "question_map" in obj:
            key = "question_map"
        if key is None:
            if o in spec.outputs:
                errors.append(f"출력 키 누락: {o}")
            continue
        val = obj[key]
        if _output_kind(o) == "json":
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except ValueError:
                    errors.append(f"{o}: JSON 객체·배열이어야 하는데 문자열입니다")
                    continue
            if not isinstance(val, (dict, list)):
                errors.append(f"{o}: JSON 객체·배열이어야 합니다")
                continue
        else:
            if isinstance(val, (dict, list)):
                errors.append(f"{o}: 마크다운 문자열이어야 합니다")
                continue
            val = str(val)
            if not val.strip():
                errors.append(f"{o}: 내용이 비어 있습니다")
                continue
        outputs[o] = val
    return outputs, errors


def validate_outputs(spec: StageSpec, outputs: dict) -> list:
    from scripts.validate import validate_obj
    errors = []
    for o, schema, selector in spec.validations:
        if o not in outputs:
            continue
        val = outputs[o]
        if selector == "":
            errors += [f"{o}: {m}" for m in validate_obj(val, schema)]
        elif selector == "[]":
            if not isinstance(val, list):
                errors.append(f"{o}: 배열이어야 합니다")
                continue
            for i, item in enumerate(val):
                errors += [f"{o}[{i}]: {m}" for m in validate_obj(item, schema)]
        else:
            if not isinstance(val, dict):
                errors.append(f"{o}: 객체여야 합니다")
                continue
            for part in selector.split(","):
                k = part.strip().rstrip("[]")
                arr = val.get(k)
                if arr is None:
                    errors.append(f"{o}: '{k}' 배열이 없습니다")
                    continue
                if not isinstance(arr, list):
                    errors.append(f"{o}.{k}: 배열이어야 합니다")
                    continue
                for i, item in enumerate(arr):
                    errors += [f"{o}.{k}[{i}]: {m}" for m in validate_obj(item, schema)]
    return errors[:40]


def write_outputs(report_id: str, outputs: dict) -> list:
    """문자열은 그대로, 객체·배열은 ensure_ascii=False indent=1 로 쓴다."""
    written = []
    rd = config.report_dir(report_id)
    for rel, val in outputs.items():
        p = config.safe_join(rd, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(val, str):
            p.write_text(val if val.endswith("\n") else val + "\n", encoding="utf-8")
        else:
            p.write_text(json.dumps(val, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(rel)
    return written


def outputs_exist(report_id: str, spec: StageSpec) -> bool:
    rd = config.report_dir(report_id)
    return bool(spec.outputs) and all((rd / o.replace("<id>", report_id)).exists() for o in spec.outputs)


def backup_outputs(report_id: str, spec: StageSpec) -> list:
    rd = config.report_dir(report_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = []
    for o in spec.outputs:
        p = rd / o.replace("<id>", report_id)
        if p.exists():
            bak = p.with_name(f"{p.name}.bak.{ts}")
            shutil.copy2(p, bak)
            moved.append(str(bak.relative_to(rd)))
    return moved


# ---------- 단계별 후처리 ----------
def _slug(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "_", s or "").strip("_")
    return s[:60] or "event"


def event_to_markdown(ev: dict, report_id: str) -> str:
    """사건 JSON → 프론트매터 + 요약 마크다운(kb/events 형식)."""
    import yaml
    fm = {k: ev.get(k) for k in ("event_id", "domain", "date", "title", "grade", "affected_indicators", "sources") if k in ev}
    fm["report_id"] = report_id
    fm["recorded_at"] = today_str()
    front = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()
    body = [f"# {ev.get('title', '')}", "", ev.get("summary", "") or "", ""]
    if ev.get("affected_indicators"):
        body.append("영향 지표: " + ", ".join(str(x) for x in ev["affected_indicators"]))
    if ev.get("sources"):
        body.append("")
        body.append("출처:")
        for s in ev["sources"]:
            body.append(f"- [{s.get('title') or s.get('url')}]({s.get('url')}) (조회 {s.get('retrieved_at', '')})")
    return front and f"---\n{front}\n---\n" + "\n".join(body) + "\n"


def copy_events_to_kb(report_id: str, events: list) -> list:
    """새 사건을 kb/events/<domain>/<date>_<slug>.md 로 복사(이미 있으면 건너뜀)."""
    created = []
    for ev in events or []:
        if not isinstance(ev, dict) or not ev.get("event_id") or not ev.get("domain"):
            continue
        d = config.KB_DIR / "events" / str(ev["domain"])
        d.mkdir(parents=True, exist_ok=True)
        eid = str(ev["event_id"])
        slug_src = eid.split("-", 4)[-1] if eid.count("-") >= 4 else ev.get("title", "")
        fname = f"{ev.get('date', '')}_{_slug(slug_src)}.md"
        p = d / fname
        if p.exists() or any(f.read_text(encoding="utf-8", errors="ignore").find(f"event_id: {eid}") >= 0
                             for f in d.glob("*.md")):
            continue
        p.write_text(event_to_markdown(ev, report_id), encoding="utf-8")
        created.append(str(p.relative_to(config.CORE_DIR)).replace("\\", "/"))
    return created


def recount_summary(cmp: dict) -> dict:
    counts = {k: 0 for k in VERDICT_KEYS}
    for r in cmp.get("conclusion_rows") or []:
        v = (r.get("verdict") or "").strip()
        counts[v if v in counts and v != "잠정" else "잠정"] += 1
    cmp["summary"] = counts
    return counts


def restore_old_from_v0(report_id: str, cmp: dict) -> list:
    """comparison_table 의 old 를 v0 와 대조해 달라졌으면 v0 값으로 되돌린다(원 결론 문장 불변)."""
    v0 = _load_json_if(config.report_dir(report_id) / "L0" / "comparison_table_v0.json")
    if not v0:
        return []
    restored = []
    for key in ("conclusion_rows", "body_rows"):
        old_map = {r.get("row_id"): r.get("old") for r in v0.get(key) or [] if isinstance(r, dict)}
        for r in cmp.get(key) or []:
            if not isinstance(r, dict):
                continue
            rid = r.get("row_id")
            if rid in old_map and old_map[rid] is not None and r.get("old") != old_map[rid]:
                r["old"] = old_map[rid]
                restored.append(f"{key}:{rid}")
    return restored


def _render_table_quiet(report_id: str) -> None:
    import scripts.render_table as rt
    with contextlib.redirect_stdout(io.StringIO()):
        rt.main(report_id)


def _post_stage(report_id: str, spec: StageSpec, outputs: dict, log: Callable) -> None:
    """파일 쓰기 전 후처리(내용 보정)와 쓰기 후 부수 작업."""
    base = spec.name.split("_")[0]
    rd = config.report_dir(report_id)
    if base == "classify":
        cls = outputs.get("02_classification.json") or {}
        try:
            from scripts.registry import upsert
            row = {"id": report_id}
            if cls.get("domains"):
                row["domain"] = str(cls["domains"][0])
            if isinstance(cls.get("type_mix"), dict):
                row["types"] = ",".join(sorted(cls["type_mix"].keys()))
            upsert(config.REGISTRY_CSV, row)
        except Exception as e:  # 레지스트리 갱신 실패는 단계 실패가 아니다
            log({"stage": spec.name, "event": "error", "note": f"레지스트리 갱신 실패: {type(e).__name__}"})
    elif base == "delta":
        created = copy_events_to_kb(report_id, outputs.get("L0/events.json") or [])
        if created:
            log({"stage": spec.name, "event": "write", "name": "kb/events", "note": f"kb 사건 {len(created)}건 기록: " + ", ".join(created[:5])})
    elif base == "impact":
        v0 = rd / "L0" / "comparison_table_v0.json"
        if not v0.exists():
            v0.parent.mkdir(parents=True, exist_ok=True)
            v0.write_text(json.dumps(outputs.get("comparison_table.json"), ensure_ascii=False, indent=1), encoding="utf-8")
            log({"stage": spec.name, "event": "write", "name": "L0/comparison_table_v0.json", "note": "v0 사본 저장(old 불변 기준)"})
        try:
            _render_table_quiet(report_id)
            src = rd / "07_report" / "comparison_table.html"
            dst = rd / "07_report" / "comparison_table_v0_L0.html"
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
        except Exception as e:
            log({"stage": spec.name, "event": "error", "note": f"v0 대조표 렌더 실패: {type(e).__name__}"})
    elif base == "brief":
        qm = outputs.get("L2/compare/question_map.json")
        if isinstance(qm, dict):
            log({"stage": spec.name, "event": "write", "name": "L2/compare/question_map.json", "note": f"질문 대응표 {len(qm)}건(블라인드에 주지 않음)"})
        chains = _load_json_if(rd / "03_argument_chains.json")
        chk = brief_mod.check_brief(outputs.get("L2/blind_input/brief.md", ""), chains)
        if chk["original_values"] or chk["verdict_words"] or chk["leaks"]:
            log({"stage": spec.name, "event": "error", "note": "브리프 자가 검사 경고: "
                 + json.dumps({k: v[:10] for k, v in chk.items()}, ensure_ascii=False)})
    elif base == "compare":
        cmp = outputs.get("comparison_table.json")
        if isinstance(cmp, dict):
            restored = restore_old_from_v0(report_id, cmp)
            if restored:
                log({"stage": spec.name, "event": "error", "note": f"old 문장이 바뀌어 v0 값으로 복원: {', '.join(restored[:10])}"})
            recount_summary(cmp)
            cmp.setdefault("report_id", report_id)
            cmp["generated_at"] = today_str()


def _pre_write(report_id: str, spec: StageSpec, outputs: dict) -> None:
    """쓰기 직전 보정: 블라인드 files_opened 강제, 비교표 old 복원·summary 재집계 등."""
    if spec.isolated:
        for o in spec.outputs:
            val = outputs.get(o)
            if isinstance(val, list):
                val = [x for x in val if not (isinstance(x, dict) and "files_opened" in x)]
                val.append({"files_opened": ["L2/blind_input/brief.md"]})
                outputs[o] = val
    base = spec.name.split("_")[0]
    if base == "compare":
        cmp = outputs.get("comparison_table.json")
        if isinstance(cmp, dict):
            restore_old_from_v0(report_id, cmp)
            recount_summary(cmp)
            cmp.setdefault("report_id", report_id)
            cmp["generated_at"] = today_str()


# ---------- 파이썬 단계 ----------
def _run_intake(report_id: str, run_config: dict, log: Callable) -> list:
    from engine.parsing import intake  # 다른 작업자가 만든 파서
    src = (run_config or {}).get("source_file") or (run_config or {}).get("source_path")
    if not src:
        d = config.report_dir(report_id) / "00_source"
        cands = [p for p in d.glob("*") if p.is_file() and p.suffix.lower() != ".md"] if d.exists() else []
        src = str(cands[0]) if cands else None
    if not src or not Path(src).exists():
        raise StageError("접수할 원본 파일이 없습니다. 접수 화면에서 파일을 올리거나 run_config.source_file 을 지정하세요")
    meta = intake(report_id, Path(src), title=(run_config or {}).get("title"), published=(run_config or {}).get("published"))
    log({"stage": "intake", "event": "write", "name": "01_meta.json", "note": json.dumps(meta, ensure_ascii=False)[:300]})
    return [f"00_source/{report_id}.md", "01_meta.json"]


def _run_report(report_id: str, log: Callable) -> list:
    import scripts.render_report as rr
    import scripts.render_table as rt
    from scripts.registry import set_maturity
    rd = config.report_dir(report_id)
    if not (rd / "comparison_table.json").exists():
        raise StageError("comparison_table.json 이 없어 보고서를 조립할 수 없습니다(L0 impact 단계 먼저)")
    with contextlib.redirect_stdout(io.StringIO()):
        rt.main(report_id)
        rr.main(report_id, config.CORE_DIR)
    cmp = _load_json_if(rd / "comparison_table.json") or {}
    maturity = str(cmp.get("maturity") or "L0")
    try:
        set_maturity(config.REGISTRY_CSV, report_id, maturity)
    except Exception as e:
        log({"stage": "report", "event": "error", "note": f"레지스트리 성숙도 갱신 실패: {type(e).__name__}"})
    log({"stage": "report", "event": "write", "name": "07_report", "note": f"성숙도 {maturity}"})
    return ["07_report/comparison_table.html", "07_report/report.md", "07_report/report.html"]


# ---------- 단계 실행 ----------
def _tool_note(name: str, args: dict) -> str:
    a = json.dumps(args, ensure_ascii=False)
    return f"{name}({a[:120]}{'…' if len(a) > 120 else ''})"


def run_stage(report_id: str, stage, settings: dict, llm: Optional[LLMClient], tools: Optional[ToolRegistry],
              log: Optional[Callable] = None, *, progress: Optional[Callable] = None,
              cancel: Optional[threading.Event] = None, job_id: str = "", run_config: Optional[dict] = None,
              force: bool = False) -> StageResult:
    """한 단계 실행. stage 는 StageSpec 또는 이름."""
    spec: StageSpec = stage if isinstance(stage, StageSpec) else get_stage(stage)
    log = log or _noop_log
    run_config = run_config or {}
    settings = settings or config.load_settings()
    res = StageResult(stage=spec.name, started_at=now_iso())
    model = settings.get("model") or (llm.model if llm else "")
    if spec.model_role == "cheap" and settings.get("model_cheap"):
        model = settings["model_cheap"]
    res.model = "" if spec.is_python else model
    totals = {"in": 0, "out": 0, "cost": 0.0}

    def emit(status: str, message: str, step: int = 0):
        if progress:
            progress({"job_id": job_id, "report_id": report_id, "stage": spec.name, "status": status, "step": step,
                      "message": message, "tokens": {"in": res.tokens_in, "out": res.tokens_out},
                      "cost_usd": round(res.cost_usd, 6), "ts": now_iso()})

    def finish(status: str, error: str = "") -> StageResult:
        res.status, res.error, res.ended_at = status, error, now_iso()
        if status == "failed":
            log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "error", "note": error})
        emit(status, error or {"done": "완료", "skipped": "건너뜀(산출물 있음)", "cancelled": "취소됨"}.get(status, status), res.steps)
        return res

    # 재개 규칙
    if not force and outputs_exist(report_id, spec):
        res.outputs = list(spec.outputs)
        log({"stage": spec.name, "event": "skip", "note": "산출물이 모두 있어 건너뜀"})
        return finish("skipped")
    if force and outputs_exist(report_id, spec) and not spec.is_python:
        moved = backup_outputs(report_id, spec)
        if moved:
            log({"stage": spec.name, "event": "write", "name": "backup", "note": "강제 재실행 전 보관: " + ", ".join(moved)})
    if cancel is not None and cancel.is_set():
        return finish("cancelled", "사용자 취소")
    emit("running", f"{spec.name} 시작", 0)
    log({"stage": spec.name, "model": res.model, "event": "start", "note": spec.note})

    # 파이썬 단계
    if spec.is_python:
        try:
            if spec.name == "intake":
                res.outputs = _run_intake(report_id, run_config, log)
            elif spec.name == "report":
                res.outputs = _run_report(report_id, log)
            else:
                raise StageError(f"알 수 없는 파이썬 단계: {spec.python}")
        except StageError as e:
            return finish("failed", str(e))
        except Exception as e:
            return finish("failed", f"{type(e).__name__}: {str(e)[:300]}")
        log({"stage": spec.name, "event": "done", "note": ", ".join(res.outputs)})
        return finish("done")

    # LLM 단계
    if llm is None:
        return finish("failed", "LLM 클라이언트가 없습니다(API 키 설정 필요)")
    tools = tools or ToolRegistry(llm=llm, settings=settings)
    tool_defs, executor = tools.for_stage(spec, report_id)
    tool_names = [d["function"]["name"] for d in tool_defs]
    try:
        user_msg = build_user_message(report_id, spec, settings, run_config, tool_names)
    except StageError as e:
        return finish("failed", str(e))
    except OSError as e:
        return finish("failed", f"입력 읽기 실패: {e}")
    messages = [{"role": "system", "content": load_system_prompt()}, {"role": "user", "content": user_msg}]
    max_steps = int(settings.get("max_steps") or 25)
    json_mode = not tool_defs
    repairs = 0
    last_content = ""
    while True:
        if cancel is not None and cancel.is_set():
            return finish("cancelled", "사용자 취소")
        if res.steps >= max_steps:
            log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "error", "note": "최대 단계 초과", "raw": last_content[:4000]})
            return finish("failed", f"최대 단계({max_steps}) 초과")
        try:
            r = llm.chat(messages, tools=tool_defs or None, json_mode=json_mode, model=model)
        except LLMError as e:
            return finish("failed", f"LLM 호출 실패: {e}")
        res.steps += 1
        res.tokens_in += r.tokens_in
        res.tokens_out += r.tokens_out
        res.cost_usd += float(r.cost_usd or 0.0)
        log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "llm", "tokens_in": r.tokens_in,
             "tokens_out": r.tokens_out, "cost_usd": r.cost_usd or 0.0,
             "note": f"tool_calls {len(r.tool_calls)}" if r.tool_calls else f"content {len(r.content)}자"})
        if r.tool_calls:
            messages.append({"role": "assistant", "content": r.content or None, "tool_calls": r.tool_calls})
            for tc in r.tool_calls:
                fn = (tc.get("function") or {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except ValueError:
                    args = None
                if args is None:
                    result = json.dumps({"error": "arguments 가 JSON 이 아닙니다"}, ensure_ascii=False)
                else:
                    result = executor(name, args)
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "name": name, "content": result})
                log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "tool", "name": name,
                     "note": _tool_note(name, args or {}) + f" → {len(result)}자"})
                emit("running", f"도구 {_tool_note(name, args or {})}", res.steps)
            continue
        # 최종 응답
        last_content = r.content or ""
        errors = []
        try:
            obj = parse_final_json(last_content)
        except ValueError as e:
            obj, errors = None, [str(e)]
        outputs = {}
        if not errors:
            outputs, errors = normalize_outputs(spec, obj, report_id)
        if not errors:
            errors = validate_outputs(spec, outputs)
        if errors:
            if repairs < MAX_REPAIRS:
                repairs += 1
                messages.append({"role": "assistant", "content": last_content})
                messages.append({"role": "user", "content": "이전 응답에 아래 문제가 있다. 지적된 부분을 고쳐 **같은 JSON 객체 전체**를 다시, JSON만 답하라.\n- "
                                 + "\n- ".join(errors)})
                log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "error",
                     "note": f"검증 실패 → 재요청 {repairs}/{MAX_REPAIRS}: " + " | ".join(errors[:5])})
                emit("running", f"검증 실패 재요청 {repairs}/{MAX_REPAIRS}", res.steps)
                continue
            log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "error",
                 "note": "검증 실패(재요청 소진): " + " | ".join(errors[:8]), "raw": last_content[:20000]})
            return finish("failed", "검증 실패: " + " | ".join(errors[:5]))
        # 쓰기
        _pre_write(report_id, spec, outputs)
        try:
            written = write_outputs(report_id, outputs)
        except OSError as e:
            return finish("failed", f"파일 쓰기 실패: {e}")
        for w in written:
            log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "write", "name": w})
        res.outputs = written
        try:
            _post_stage(report_id, spec, outputs, log)
        except Exception as e:  # 후처리 실패는 기록만
            log({"stage": spec.name, "event": "error", "note": f"후처리 오류: {type(e).__name__}: {str(e)[:200]}"})
        log({"stage": spec.name, "model": res.model, "step": res.steps, "event": "done", "tokens_in": res.tokens_in,
             "tokens_out": res.tokens_out, "cost_usd": res.cost_usd, "note": ", ".join(written)})
        return finish("done")


# ---------- 파이프라인 ----------
def make_llm(settings: Optional[dict] = None, env: Optional[dict] = None) -> Optional[LLMClient]:
    env = env if env is not None else config.load_env()
    settings = settings or config.load_settings()
    if not env.get("OPENROUTER_API_KEY"):
        return None
    return LLMClient(base_url=env.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"), api_key=env["OPENROUTER_API_KEY"],
                     model=settings.get("model") or "openrouter/auto", temperature=float(settings.get("temperature", 0.2)))


def run_pipeline(report_id: str, run_config: dict, progress: Optional[Callable] = None,
                 cancel: Optional[threading.Event] = None, *, force_from: Optional[str] = None,
                 settings: Optional[dict] = None, llm: Optional[LLMClient] = None,
                 tools: Optional[ToolRegistry] = None, job_id: str = "", log: Optional[Callable] = None) -> dict:
    """run_config 로 단계를 정해 순서대로 실행한다. 반환: 실행 요약 dict."""
    run_config = dict(run_config or {})
    run_config.setdefault("report_id", report_id)
    config.report_dir(report_id)  # ID 형식 검사
    settings = dict(settings or config.load_settings())
    # 실행 화면에서 고른 모델·검색 공급자(run_config.model / search_provider)가 있으면 settings 보다 우선한다
    for key in ("model", "search_provider"):
        val = run_config.get(key)
        if isinstance(val, str) and val.strip():
            settings[key] = val.strip()
    env = config.load_env()
    llm = llm if llm is not None else make_llm(settings, env)
    tools = tools or ToolRegistry(env=env, llm=llm, settings=settings)
    log = log or make_logger(report_id)
    cancel = cancel or threading.Event()
    specs = stages_for(run_config)
    force_idx = None
    if force_from:
        names = [s.name for s in specs]
        base_names = [n.split("_")[0] for n in names]
        if force_from in names:
            force_idx = names.index(force_from)
        elif force_from in base_names:
            force_idx = base_names.index(force_from)
        elif force_from in STAGE_ORDER:
            # 실행 목록에 없는 단계면 그 다음 순서의 단계부터 강제
            later = [i for i, n in enumerate(base_names) if STAGE_ORDER.index(n) >= STAGE_ORDER.index(force_from)]
            force_idx = later[0] if later else None
        else:
            raise ValueError(f"알 수 없는 force_from 단계: {force_from}")
    summary = {"job_id": job_id, "report_id": report_id, "status": "running", "started_at": now_iso(), "ended_at": "",
               "stages": [], "tokens": {"in": 0, "out": 0}, "cost_usd": 0.0, "error": "", "run_config": run_config,
               "force_from": force_from}
    log({"stage": "pipeline", "event": "start", "note": f"단계 {[s.name for s in specs]}, force_from={force_from}"})
    dirty = False
    status = "done"

    def wrapped_progress(ev: dict):
        ev["tokens"] = {"in": summary["tokens"]["in"] + ev.get("tokens", {}).get("in", 0),
                        "out": summary["tokens"]["out"] + ev.get("tokens", {}).get("out", 0)}
        ev["cost_usd"] = round(summary["cost_usd"] + float(ev.get("cost_usd") or 0), 6)
        if progress:
            progress(ev)

    for i, spec in enumerate(specs):
        if cancel.is_set():
            status = "cancelled"
            summary["error"] = "사용자 취소"
            break
        force = force_idx is not None and i >= force_idx
        if spec.name in ("report", "critic") and dirty:
            force = True
        res = run_stage(report_id, spec, settings, llm, tools, log, progress=wrapped_progress, cancel=cancel,
                        job_id=job_id, run_config=run_config, force=force)
        summary["stages"].append(res.to_dict())
        summary["tokens"]["in"] += res.tokens_in
        summary["tokens"]["out"] += res.tokens_out
        summary["cost_usd"] = round(summary["cost_usd"] + res.cost_usd, 6)
        if res.status == "done":
            dirty = True
        elif res.status == "failed":
            status = "failed"
            summary["error"] = f"{spec.name}: {res.error}"
            break
        elif res.status == "cancelled":
            status = "cancelled"
            summary["error"] = "사용자 취소"
            break
    summary["status"] = status
    summary["ended_at"] = now_iso()
    try:
        from scripts.registry import upsert
        upsert(config.REGISTRY_CSV, {"id": report_id})  # updated_at 만 갱신
    except Exception as e:
        log({"stage": "pipeline", "event": "error", "note": f"레지스트리 갱신 실패: {type(e).__name__}"})
    log({"stage": "pipeline", "event": "done" if status == "done" else "error", "tokens_in": summary["tokens"]["in"],
         "tokens_out": summary["tokens"]["out"], "cost_usd": summary["cost_usd"], "note": f"{status} {summary['error']}".strip()})
    if progress:
        progress({"job_id": job_id, "report_id": report_id, "stage": "pipeline", "status": status, "step": len(summary["stages"]),
                  "message": summary["error"] or "파이프라인 완료", "tokens": dict(summary["tokens"]),
                  "cost_usd": summary["cost_usd"], "ts": now_iso()})
    return summary


def default_run_config(report_id: str) -> dict:
    """UI 없이 돌릴 때의 기본 run_config(설계서 7.3)."""
    return {"report_id": report_id, "layers": ["L0", "L1", "L2"],
            "options": {"blind_rerun": {"enabled": True, "repeats": 1}, "survey_redesign": True, "experiment_plan": True,
                        "synthetic_sim": {"enabled": False, "panel_size": 200}, "l0_rewrite_scope": "env_and_desk_updatable"},
            "sources": ["openalex", "web"], "output": ["html"], "period": {"since": "", "until": "today"}}


if __name__ == "__main__":  # python -m engine.runner R01 [force_from]
    import sys
    rid = sys.argv[1] if len(sys.argv) > 1 else "R01"
    ff = sys.argv[2] if len(sys.argv) > 2 else None
    rc_path = config.report_dir(rid) / "run_config.json"
    rc = _load_json_if(rc_path) or default_run_config(rid)
    jid = f"{datetime.now():%Y%m%d_%H%M%S}_{rid}"
    out = run_pipeline(rid, rc, progress=lambda e: print(f"[{e['stage']}] {e['status']} {e['message']}"), force_from=ff, job_id=jid)
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (config.RUNS_DIR / f"{jid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("status", "tokens", "cost_usd", "error")}, ensure_ascii=False))
