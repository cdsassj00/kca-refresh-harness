"""독립 프로그램 실행 엔진.

- llm.py      OpenAI 호환 LLM 클라이언트(LLMClient)
- search.py   웹 검색 공급자 통합(tavily → exa → naver → openrouter_online)
- tools.py    단계별 도구 레지스트리(ToolRegistry)
- stages.py   단계 정의(STAGES, stages_for)
- runner.py   단계 실행기(run_stage, run_pipeline)
- brief.py    블라인드 브리프 보조(질문 대응표 저장·수치 유출 검사)
- jobs.py     백그라운드 작업 저장소(JobStore)
- parsing.py  문서 파싱(다른 작업자가 작성)

하위 모듈은 필요할 때 개별로 import 한다(`from engine.runner import run_pipeline`).
패키지 import 시점에 무거운 의존성을 끌어오지 않도록 여기서는 아무것도 import 하지 않는다.
"""
__version__ = "0.1"
