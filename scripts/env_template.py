"""`.env` 관련 파일의 **배치 원본**. 세 파일이 서로 다른 모양이 되지 않게 한 곳에 적는다.

왜 필요한가
  키 파일은 세 개다(루트 견본 · app 견본 · app 실제 키). 셋의 줄 순서와 구역 주석이 제각각이면
  "지금 보고 있는 게 어느 파일인지" 알 수 없고, 실제로 견본에 키를 넣거나 편집기 내용이
  디스크와 어긋나는 사고가 났다. 그래서 **차례와 구역 주석을 여기 한 곳에서 정하고**,
  `tests/test_env_layout.py` 가 세 파일이 이 차례를 지키는지 검사한다.

무엇을 통일하고 무엇을 통일하지 않는가
  통일한다   : 구역 이름과 차례, 변수 이름과 차례, 변수마다 붙는 한 줄 설명
  통일하지 않는다: 첫머리 안내문(파일마다 쓰임이 다르다)과 값(견본은 비우고 실제 파일만 채운다)
"""
from __future__ import annotations

# 구역: (구역 제목, [(변수 이름, 한 줄 설명), ...])
# 차례를 바꾸려면 여기만 고치고 `python scripts/env_template.py --write` 를 돌린다.
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("독립 프로그램(app/) 전용 — 하네스는 쓰지 않는다", [
        ("OPENROUTER_API_KEY", "[app 필수] OpenRouter 키 (sk-or-… ). openrouter.ai/keys"),
        ("LLM_BASE_URL", "OpenAI 호환 주소. 비우면 OpenRouter 기본값"),
        ("LLM_MODEL", "기본 모델 ID (예: anthropic/claude-sonnet-5)"),
        ("LLM_MODEL_CHEAP", "추출·분류처럼 가벼운 단계에 쓸 저가 모델. 비우면 기본 모델"),
        ("SEARCH_PROVIDER", "auto | tavily | exa | naver | openrouter_online"),
    ]),
    ("권장 최소 세트 — 이것만 있어도 국내 근거 수집이 돈다", [
        ("DATA_GO_KR_API_KEY", "공공데이터포털. 마이페이지의 '일반 인증키(Decoding)'. 계정당 하나"),
        ("KOSIS_API_KEY", "국가통계포털. 유효기간 2년, 만료되면 마이페이지에서 연장"),
        ("LAW_GO_KR_OC", "법제처. 긴 키가 아니라 짧은 기관 아이디(OC). 이메일 앞부분이 아니다"),
        ("NAVER_CLIENT_ID", "NAVER 검색. API HUB 의 X-NCP-APIGW-API-KEY-ID"),
        ("NAVER_CLIENT_SECRET", "NAVER 검색. API HUB 의 X-NCP-APIGW-API-KEY"),
        ("NAVER_API_STYLE", "비우면 API HUB. 예전 개발자센터를 쓰려면 legacy"),
    ]),
    ("국내 추가", [
        ("ASSEMBLY_API_KEY", "열린국회정보. open.assembly.go.kr/portal/openapi/main.do"),
        ("ECOS_API_KEY", "한국은행 경제통계. 통계표 코드를 알아야 값을 꺼낸다"),
        ("KCI_API_KEY", "한국학술지인용색인. open.kci.go.kr. 국내 논문 제목·기간 검색"),
        ("NANET_API_KEY", "국회도서관. 학술논문·정책자료"),
        ("SCIENCEON_API_KEY", "KISTI ScienceON. 논문·특허·국가R&D 과제"),
    ]),
    ("해외 — 위 둘은 키가 아니라 이메일 주소다(신청 없음)", [
        ("OPENALEX_MAILTO", "OpenAlex 우대 대기열용 이메일. 신청 절차 없음"),
        ("CROSSREF_MAILTO", "Crossref 우대 대기열용 이메일. 신청 절차 없음"),
        ("S2_API_KEY", "Semantic Scholar. 없어도 되지만 있으면 한도가 올라간다"),
        ("IEEE_API_KEY", "IEEE Xplore. 통신·전파 공학"),
        ("CORE_API_KEY", "CORE. 오픈액세스 원문"),
        ("SPRINGER_API_KEY", "Springer Nature"),
        ("LENS_API_TOKEN", "Lens.org. 논문 + 특허. 비상업 무료"),
    ]),
    ("웹 검색", [
        ("TAVILY_API_KEY", "Tavily (tvly-… ). app.tavily.com"),
        ("EXA_API_KEY", "Exa. dashboard.exa.ai"),
        ("PERPLEXITY_API_KEY", "Perplexity"),
        ("SERPAPI_API_KEY", "SerpAPI (Google Scholar 경유)"),
    ]),
    ("유료·기관 구독 — 필요할 때만", [
        ("ELSEVIER_API_KEY", "Scopus/ScienceDirect"),
        ("ELSEVIER_INSTTOKEN", "Elsevier 기관 토큰(기관 네트워크 밖에서 쓸 때)"),
        ("WOS_API_KEY", "Web of Science"),
        ("DIMENSIONS_API_KEY", "Dimensions"),
        ("DBPIA_API_KEY", "DBpia"),
        ("BIGKINDS_API_KEY", "빅카인즈(뉴스)"),
    ]),
]

# 파일마다 다른 것은 첫머리 안내문뿐이다.
HEADERS = {
    ".env.example": [
        "하네스(Claude Code 쪽) 설정 **견본**. 이 파일을 `.env` 로 복사해 값을 채운다.",
        "이 파일은 git 에 올라간다. **여기에는 절대 실제 키를 적지 않는다.**",
        "발급처·절차: docs/api_keys_guide.md",
    ],
    "app/.env.example": [
        "독립 프로그램(app/) 설정 **견본**. run_app.bat 이 없으면 이 파일을 .env 로 복사한다.",
        "이 파일은 git 에 올라간다. **여기에는 절대 실제 키를 적지 않는다.**",
        "값은 브라우저 [설정] 화면에서 넣어도 된다. 발급처: ../docs/api_keys_guide.md",
    ],
    "app/.env": [
        "독립 프로그램(app/) **실제 키**. 이 파일은 git 에 올라가지 않는다(.gitignore).",
        "하네스(scripts/evidence.py)도 루트 .env 가 없으면 이 파일을 읽는다.",
        "배치는 scripts/env_template.py 가 정한다. 줄 차례를 바꾸지 말 것.",
    ],
    ".env": [
        "하네스 **실제 키**. 이 파일은 git 에 올라가지 않는다(.gitignore).",
        "배치는 scripts/env_template.py 가 정한다. 줄 차례를 바꾸지 말 것.",
    ],
}

VAR_ORDER: list[str] = [name for _, items in SECTIONS for name, _ in items]


def render(rel_path: str, values: dict | None = None) -> str:
    """한 파일의 전체 내용을 만든다. values 를 주면 그 값만 채운다(없는 변수는 빈칸)."""
    values = values or {}
    out = ["# " + line for line in HEADERS[rel_path]]
    for title, items in SECTIONS:
        out.append("")
        out.append(f"# ── {title} ──")
        for name, note in items:
            out.append(f"# {note}")
            out.append(f"{name}={values.get(name, '')}")
    return "\n".join(out) + "\n"


def layout_of(text: str) -> list[str]:
    """파일에서 변수 이름을 나온 차례대로 뽑는다(주석 줄은 뺀다)."""
    names = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        names.append(s.partition("=")[0].strip())
    return names


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    from dotenv import dotenv_values

    ROOT = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="`.env` 파일들의 배치를 원본에 맞춘다")
    ap.add_argument("--write", action="store_true", help="실제로 파일을 고친다(기본은 확인만)")
    ap.add_argument("--files", nargs="*", default=[".env.example", "app/.env.example"],
                    help="대상 파일. 실제 키 파일(.env)은 값을 보존한 채 다시 쓴다")
    args = ap.parse_args()

    for rel in args.files:
        p = ROOT / rel
        if not p.exists():
            print(f"{rel:20} 없음 — 건너뜀")
            continue
        before = dict(dotenv_values(p))
        keep = {k: v for k, v in before.items() if v} if not rel.endswith(".example") else {}
        new_text = render(rel, keep)
        if p.read_text(encoding="utf-8") == new_text:
            print(f"{rel:20} 이미 원본과 같음")
            continue
        if not args.write:
            print(f"{rel:20} 배치가 다름 (--write 로 고칠 수 있음)")
            continue
        had = {k for k, v in before.items() if v}
        if rel.endswith(".example") and had:
            # 견본에 실제 키가 들어 있었다는 뜻이다. 비우는 것이 맞지만, 무엇을 비웠는지는
            # 반드시 알려 준다(다른 데에도 적혀 있는지 확인해야 하므로). 값은 찍지 않는다.
            print(f"  ! {rel} 에 값이 들어 있어 비웠습니다: {', '.join(sorted(had))}")
            print(f"  ! 이 키들이 실제 파일(.env)에도 있는지 확인하세요. 견본은 git 에 올라갑니다.")
        p.write_text(new_text, encoding="utf-8")
        after = {k: v for k, v in dotenv_values(p).items() if v}
        if not rel.endswith(".example"):
            lost = {k for k, v in before.items() if v and after.get(k) != v}
            assert not lost, f"{rel}: 값이 바뀐 변수가 있습니다 {sorted(lost)}"
        print(f"{rel:20} 배치 통일 완료 (값 {len(after)}개)")
