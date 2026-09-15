"""engine.tools / engine.search 테스트 — 경로 탈출 차단, 블라인드 도구 세트, 공급자 폴백 순서, 결과 잘라내기."""
from __future__ import annotations
import json

import pytest

import config
from engine import search as search_mod
from engine import tools as tools_mod
from engine.stages import STAGES, get_stage
from engine.tools import ToolRegistry, cap_json


@pytest.fixture
def report(make_report):
    return make_report("R91", source_text="<!-- page 1 -->\n원문 SRC_MARKER_91\n" * 50,
                       files={"L0/events.json": [], "L2/blind_input/brief.md": "# 브리프\n질문만"})


def test_read_report_file_blocks_escape(report, settings):
    reg = ToolRegistry(env={}, llm=None, settings=settings)
    defs, run = reg.for_stage("chains", "R91")
    assert [d["function"]["name"] for d in defs] == ["read_report_file"]
    ok = json.loads(run("read_report_file", {"relpath": "01_meta.json"}))
    assert ok["content"] and '"report_id": "R91"' in ok["content"]
    for bad in ("../R01/01_meta.json", "../../registry.csv", "..\\..\\app\\.env", "/etc/passwd", "L0/../../R01/01_meta.json"):
        out = json.loads(run("read_report_file", {"relpath": bad}))
        assert "error" in out, bad
        assert "R01" not in out.get("content", "")
    missing = json.loads(run("read_report_file", {"relpath": "없는파일.json"}))
    assert "error" in missing
    # 이 단계에서 허용되지 않은 도구
    assert "error" in json.loads(run("web_search", {"query": "x"}))


def test_read_core_file_restricted(settings):
    reg = ToolRegistry(env={}, llm=None, settings=settings)
    _, run = reg.for_stage("delta", "R91")
    out = json.loads(run("read_core_file", {"relpath": "templates/verdict_rules.yaml"}))
    assert "verdicts" in out["content"]
    for bad in ("prompts/00_intake.md", "registry.csv", "../app/.env", "kb/../reports/R01/01_meta.json", "scripts/validate.py"):
        assert "error" in json.loads(run("read_core_file", {"relpath": bad})), bad


def test_blind_stage_has_no_read_tools(report, settings):
    blind = get_stage("blind")
    assert blind.isolated
    assert not (set(blind.tools) & tools_mod.READ_TOOLS)
    reg = ToolRegistry(env={}, llm=None, settings=settings)
    defs, run = reg.for_stage(blind, "R91")
    names = {d["function"]["name"] for d in defs}
    assert names == {"web_search", "fetch_page", "evidence_search"}
    assert not (names & tools_mod.READ_TOOLS)
    # 실행기도 거부한다
    assert "error" in json.loads(run("read_report_file", {"relpath": "00_source/R91.md"}))
    assert "SRC_MARKER_91" not in run("read_report_file", {"relpath": "00_source/R91.md"})
    # 격리 단계에 read 계열이 섞여 들어와도 걸러진다
    from dataclasses import replace
    tampered = replace(blind, tools=list(blind.tools) + ["read_report_file", "read_core_file"])
    defs2, _ = reg.for_stage(tampered, "R91")
    assert not ({d["function"]["name"] for d in defs2} & tools_mod.READ_TOOLS)


def test_all_stage_tools_are_known():
    for s in STAGES:
        for t in s.tools:
            assert t in tools_mod.TOOL_DEFS, (s.name, t)


# ---------------------------------------------------------------- 검색 공급자 폴백
def _stub_providers(monkeypatch, record: list):
    def mk(name):
        def fn(query, since, max_results, lang, env, llm=None):
            record.append(name)
            return [{"title": f"{name} 결과", "url": f"https://{name}.example/{query}", "snippet": "s", "date": "2026-01-01", "source": name}]
        return fn
    new = {n: (has, mk(n)) for n, (has, _) in search_mod.PROVIDERS.items()}
    monkeypatch.setattr(search_mod, "PROVIDERS", new)


def test_search_provider_fallback_order(monkeypatch):
    rec: list = []
    _stub_providers(monkeypatch, rec)
    all_keys = {"TAVILY_API_KEY": "t", "EXA_API_KEY": "e", "NAVER_CLIENT_ID": "n", "NAVER_CLIENT_SECRET": "s",
                "OPENROUTER_API_KEY": "o"}
    assert search_mod.available_providers(all_keys, llm=object()) == ["tavily", "exa", "naver", "openrouter_online"]
    search_mod.search("q", provider="auto", env=all_keys, llm=object())
    assert rec[-1] == "tavily"
    search_mod.search("q", provider="auto", env={k: v for k, v in all_keys.items() if k != "TAVILY_API_KEY"}, llm=object())
    assert rec[-1] == "exa"
    search_mod.search("q", provider="auto", env={"NAVER_CLIENT_ID": "n", "NAVER_CLIENT_SECRET": "s"})
    assert rec[-1] == "naver"
    search_mod.search("q", provider="auto", env={"OPENROUTER_API_KEY": "o"}, llm=object())
    assert rec[-1] == "openrouter_online"
    # naver 는 ID+SECRET 둘 다 있어야 한다 → openrouter 로 넘어감
    search_mod.search("q", provider="auto", env={"NAVER_CLIENT_ID": "n", "OPENROUTER_API_KEY": "o"}, llm=object())
    assert rec[-1] == "openrouter_online"
    # 명시 지정
    out = search_mod.search("q", provider="exa", env=all_keys)
    assert rec[-1] == "exa" and out[0]["source"] == "exa"
    with pytest.raises(search_mod.SearchError):
        search_mod.search("q", provider="auto", env={}, llm=None)
    with pytest.raises(search_mod.SearchError):
        search_mod.search("q", provider="tavily", env={})


def test_openrouter_online_parses_json_array_or_empty():
    class L:
        def __init__(self, content):
            self.content = content

        def chat(self, messages, tools=None, json_mode=False, model=None, extra=None):
            assert extra == {"plugins": [{"id": "web"}]}
            assert "JSON 배열" in messages[0]["content"]
            from engine.llm import LLMResult
            return LLMResult(content=self.content)

    good = '```json\n[{"title":"t","url":"https://a.b/c","snippet":"s","date":"2026-02-03"}]\n```'
    out = search_mod._search_openrouter_online("q", None, 5, "ko", {}, L(good))
    assert out == [{"title": "t", "url": "https://a.b/c", "snippet": "s", "date": "2026-02-03", "source": "openrouter_online"}]
    assert search_mod._search_openrouter_online("q", None, 5, "ko", {}, L("검색 결과가 없습니다.")) == []
    assert search_mod._search_openrouter_online("q", None, 5, "ko", {}, L('{"a": 1}')) == []


def test_web_search_tool_uses_registry_env(monkeypatch, settings):
    rec: list = []
    _stub_providers(monkeypatch, rec)
    reg = ToolRegistry(env={"EXA_API_KEY": "e"}, llm=None, settings=settings)
    _, run = reg.for_stage("delta", "R91")
    out = json.loads(run("web_search", {"query": "이음5G", "since": "2024-01-01"}))
    assert rec == ["exa"] and out[0]["url"].endswith("이음5G")
    reg2 = ToolRegistry(env={}, llm=None, settings=settings)
    _, run2 = reg2.for_stage("delta", "R91")
    assert "error" in json.loads(run2("web_search", {"query": "x"}))


# ---------------------------------------------------------------- 결과 잘라내기·fetch_page
def test_cap_json_truncates_but_stays_json():
    big = {"url": "u", "text": "가" * 20000}
    s = cap_json(big, 12000)
    d = json.loads(s)
    assert len(s) <= 12000 and d["truncated"] is True and d["text"].endswith("…")
    arr = [{"title": "t" * 500, "url": "u"} for _ in range(100)]
    d2 = json.loads(cap_json(arr, 12000))
    assert d2["truncated"] is True and d2["dropped"] > 0 and len(d2["results"]) < 100
    assert json.loads(cap_json({"a": 1}, 100)) == {"a": 1}


def test_fetch_page_html_and_pdf(monkeypatch):
    class R:
        def __init__(self, content, ctype, url="https://x.test/p"):
            self.content = content
            self.text = content.decode("utf-8", "ignore")
            self.headers = {"Content-Type": ctype}
            self.status_code = 200
            self.url = url

    html = b"<html><head><title>Test Page</title></head><body><nav>menu</nav><article><h1>Heading</h1><p>" + \
           "본문 문단입니다. ".encode("utf-8") * 30 + b"</p></article></body></html>"
    monkeypatch.setattr(tools_mod, "host_blocked", lambda u: None)  # DNS 없이 공개 호스트로 간주
    monkeypatch.setattr(tools_mod.requests, "get", lambda *a, **k: R(html, "text/html; charset=utf-8"))
    out = tools_mod.fetch_page("https://x.test/p")
    assert out["status"] == 200 and out["title"] == "Test Page" and "본문 문단" in out["text"]
    assert out["fetched_at"]

    import io
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(25):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    monkeypatch.setattr(tools_mod.requests, "get", lambda *a, **k: R(buf.getvalue(), "application/pdf", "https://x.test/f.pdf"))
    out = tools_mod.fetch_page("https://x.test/f.pdf")
    assert out["text"].count("<!-- page") == 20  # 앞 20쪽만
    assert tools_mod.fetch_page("ftp://nope")["status"] == 0


def test_fetch_page_blocks_internal_hosts(monkeypatch):
    """SSRF 방지: 사설·루프백·링크로컬 주소와 사용자 정보 URL 은 요청 자체를 보내지 않는다. 리다이렉트도 매 홉 검사."""
    import socket
    calls = []
    monkeypatch.setattr(tools_mod.requests, "get", lambda *a, **k: calls.append(a[0]) or (_ for _ in ()).throw(AssertionError("차단돼야 함")))
    fake_dns = {"evil.test": "10.0.0.5", "meta.test": "169.254.169.254", "loop.test": "127.0.0.1"}
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: [(None, None, None, None, (fake_dns.get(host, host), port))])
    for url in ("http://evil.test/x", "http://meta.test/latest", "http://loop.test/", "http://localhost:8765/api",
                "http://169.254.169.254/latest/meta-data", "http://user:pw@example.org/"):
        out = tools_mod.fetch_page(url)
        assert out["status"] == 0 and out["error"].startswith("차단"), url
    assert calls == []

    # 공개 호스트 → 내부 주소로 리다이렉트하면 두 번째 홉에서 차단
    class Redir:
        status_code = 302
        headers = {"Location": "http://loop.test/secret"}
        content = b""; text = ""; url = "http://ok.test/"
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kw: [(None, None, None, None, ({"ok.test": "93.184.216.34"}.get(host, fake_dns.get(host, host)), port))])
    monkeypatch.setattr(tools_mod.requests, "get", lambda *a, **k: Redir())
    out = tools_mod.fetch_page("http://ok.test/")
    assert out["status"] == 0 and "차단" in out["error"] and out["url"] == "http://loop.test/secret"


def test_evidence_search_saves_jsonl(monkeypatch, core_dir):
    from scripts.sources.base import BaseSource

    class FakeSrc(BaseSource):
        name = "fake"; kind = "papers"; env_vars = []

        def search(self, query, since=None, until=None, limit=20):
            return [self.record(id="1", url="https://doi.org/1", title="논문", date="2024-01-01", snippet="요약", grade="A", query=query)]

    monkeypatch.setattr("scripts.sources.load_sources", lambda env, http, kind=None, only=None: [FakeSrc(env, http)])
    out = tools_mod.evidence_search("이음5G", since="2023-05-01", limit=5, env={})
    assert out[0]["title"] == "논문" and out[0]["grade"] == "A"
    files = list((config.KB_DIR / "evidence").glob("*_papers_*.jsonl"))
    assert files and "논문" in files[-1].read_text(encoding="utf-8")
