"""블라인드 브리프 보조. 브리프 자체는 stages 의 `brief` 단계(LLM)가 만들고, 여기는

- 질문 대응표(question_map) 저장·읽기 (블라인드 에이전트에게 주지 않는 파일)
- 브리프에 원 결론의 수치가 새지 않았는지 검사 (prompts/05a_brief.md 의 자가 검사, critic C5)
- 브리프 단계 입력용으로 사슬을 결론 목록만 남기게 추리기
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Optional

import config

BRIEF_PATH = "L2/blind_input/brief.md"
QUESTION_MAP_PATH = "L2/compare/question_map.json"   # prompts/08_critic.md 가 읽는 경로
VERDICT_WORDS = ("동일", "강화", "부분수정", "약화", "뒤집힘", "신규결론", "판정불가")


def save_question_map(report_id: str, mapping: dict) -> Path:
    """{"Q1": "R01-K-Fc-06", ...} 를 L2/compare/question_map.json 에 저장한다."""
    if not isinstance(mapping, dict):
        raise ValueError("question_map 은 {\"Q1\": \"결론ID\"} 모양의 객체여야 합니다")
    p = config.report_dir(report_id) / QUESTION_MAP_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    clean = {str(k): str(v) for k, v in mapping.items()}
    p.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_question_map(report_id: str) -> dict:
    p = config.report_dir(report_id) / QUESTION_MAP_PATH
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}


def conclusions_only(chains: dict) -> dict:
    """브리프 단계 입력: 결론의 종류·방법·유형만 남긴다(전제·근거·간선은 뺀다)."""
    out = {"report_id": chains.get("report_id", ""), "conclusions": []}
    for c in chains.get("conclusions") or []:
        out["conclusions"].append({k: c.get(k) for k in ("conclusion_id", "kind", "statement", "method", "types", "rerun_grade")
                                   if k in c})
    return out


_YEAR = re.compile(r"^(19|20)\d{2}$")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def find_leaked_numbers(brief_text: str) -> list:
    """브리프에 남은 숫자 중 연도·날짜·기간·질문 번호·목록 번호가 아닌 것을 돌려준다(의심 목록)."""
    text = brief_text or ""
    # 날짜·연도 범위·질문 ID·목록 번호·방법 참조를 먼저 지운다
    text = re.sub(r"\d{4}-\d{2}(-\d{2})?", " ", text)
    text = re.sub(r"(19|20)\d{2}\s*[~∼–-]\s*(19|20)?\d{2,4}\s*년?", " ", text)
    text = re.sub(r"(19|20)\d{2}\s*년?", " ", text)
    text = re.sub(r"\bQ\d+\b", " ", text)
    text = re.sub(r"(?m)^\s*\d+\.\s", " ", text)
    text = re.sub(r"방법\s*\d+(\s*[~∼–-]\s*\d+)?", " ", text)
    text = re.sub(r"\d+\s*개\s*시나리오", " ", text)
    text = re.sub(r"\d+\s*가지", " ", text)
    text = re.sub(r"\d+\s*(개월|분기|년간|주|일)\b", " ", text)
    # 기술 명칭·대역·장 번호·보고서 ID 는 수치 유출이 아니다: 5G/6G, 24~28GHz, 4.7㎓, 레벨-5, 제3장, R01, Wi-Fi 6, O-RAN
    text = re.sub(r"\d+(?:\.\d+)?\s*(?:[~∼–-]\s*\d+(?:\.\d+)?)?\s*(?:GHz|㎓|MHz|㎒|Hz|G\b|TB|GB|Mbps|Gbps)", " ", text)
    text = re.sub(r"레벨\s*-?\s*\d+|Level\s*-?\s*\d+|제\s*\d+\s*장|\bR\d{2}\b|Wi-?Fi\s*\d|3GPP|Rel(?:ease)?[- ]?\d+", " ", text)
    leaks = []
    for m in _NUM.finditer(text):
        tok = m.group(0)
        if _YEAR.match(tok):
            continue
        leaks.append(tok)
    return leaks


def find_original_values(brief_text: str, chains: Optional[dict]) -> list:
    """claims[].original_value.value 가 브리프에 그대로 들어 있는지 검사한다(critic C5)."""
    if not chains:
        return []
    hits = []
    text = brief_text or ""
    for claim in chains.get("claims") or []:
        ov = (claim.get("original_value") or {}).get("value")
        if ov is None or isinstance(ov, bool):
            continue
        s = str(ov)
        if len(s) < 2:
            continue
        if re.search(rf"(?<![\d.]){re.escape(s)}(?![\d.])", text):
            hits.append(f"{claim.get('claim_id', '?')}: {s}")
    return hits


def find_verdict_words(brief_text: str) -> list:
    return [w for w in VERDICT_WORDS if w in (brief_text or "")]


def check_brief(brief_text: str, chains: Optional[dict] = None) -> dict:
    """자가 검사 결과. leaks(의심 숫자), original_values(원 결론 수치 일치), verdict_words(판정 어휘)."""
    return {"leaks": find_leaked_numbers(brief_text), "original_values": find_original_values(brief_text, chains),
            "verdict_words": find_verdict_words(brief_text)}
