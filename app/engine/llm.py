"""OpenAI 호환 채팅 API 클라이언트. DESIGN.md 2절.

- POST {base_url}/chat/completions 에 usage:{"include":true}를 붙여 토큰·비용을 받는다.
- 429/5xx 는 지수 백오프로 최대 3회 재시도, 네트워크 오류는 LLMError.
- API 키 값은 어떤 예외 메시지·로그에도 넣지 않는다(_scrub 으로 한 번 더 지운다).
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3


class LLMError(Exception):
    """LLM 호출 실패(네트워크·인증·형식). 메시지에 키 값은 들어가지 않는다."""


@dataclass
class LLMResult:
    content: str
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    cost_usd: Optional[float] = None
    raw: dict = field(default_factory=dict)

    @property
    def tokens_in(self) -> int:
        return int(self.usage.get("prompt_tokens") or 0)

    @property
    def tokens_out(self) -> int:
        return int(self.usage.get("completion_tokens") or 0)


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.2, timeout: int = 180,
                 referer: str = "http://localhost:8765", title: str = "KCA Refresh"):
        self.base_url = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self._api_key = api_key or ""
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.referer = referer
        self.title = title
        self.backoff_base = 1.0  # 초. 테스트에서 0으로 둔다.

    # ---------- 내부 ----------
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json",
                "HTTP-Referer": self.referer, "X-Title": self.title}

    def _scrub(self, text: str) -> str:
        """오류 메시지에 키 값이 섞여 들어오는 경우를 대비해 지운다."""
        if not text:
            return ""
        if self._api_key and self._api_key in text:
            text = text.replace(self._api_key, "***")
        return text

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        last_note = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = requests.post(url, headers=self._headers(), json=body, timeout=self.timeout)
            except requests.RequestException as e:  # 연결·타임아웃
                raise LLMError(f"LLM 네트워크 오류: {type(e).__name__}: {self._scrub(str(e))[:200]}") from None
            status = getattr(resp, "status_code", 0)
            if status in RETRY_STATUSES and attempt < MAX_RETRIES:
                last_note = f"HTTP {status}"
                time.sleep(self.backoff_base * (2 ** attempt))
                continue
            if status != 200:
                snippet = self._scrub(getattr(resp, "text", "") or "")[:300]
                raise LLMError(f"LLM 응답 오류 HTTP {status}: {snippet}")
            try:
                return resp.json()
            except ValueError:
                raise LLMError("LLM 응답이 JSON이 아닙니다") from None
        raise LLMError(f"LLM 재시도 {MAX_RETRIES}회 실패 ({last_note})")

    # ---------- 공개 ----------
    def chat(self, messages: list, tools: Optional[list] = None, json_mode: bool = False,
             model: Optional[str] = None, extra: Optional[dict] = None) -> LLMResult:
        body: dict = {"model": model or self.model, "messages": messages, "temperature": self.temperature,
                      "usage": {"include": True}}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if extra:
            body.update(extra)
        data = self._post("/chat/completions", body)
        if "error" in data and not data.get("choices"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise LLMError(f"LLM 오류: {self._scrub(str(msg))[:300]}")
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("LLM 응답에 choices가 없습니다")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):  # 일부 공급자는 content를 파트 배열로 준다
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        tool_calls = message.get("tool_calls") or []
        usage = data.get("usage") or {}
        cost = usage.get("cost")
        try:
            cost_usd = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_usd = None
        return LLMResult(content=content, tool_calls=tool_calls, usage=usage, cost_usd=cost_usd, raw=data)

    def list_models(self) -> list:
        """GET {base_url}/models → [{id, name, context_length, pricing}]"""
        try:
            resp = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=30)
        except requests.RequestException as e:
            raise LLMError(f"모델 목록 조회 실패: {type(e).__name__}") from None
        if resp.status_code != 200:
            raise LLMError(f"모델 목록 조회 실패: HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError:
            raise LLMError("모델 목록 응답이 JSON이 아닙니다") from None
        items = data.get("data") if isinstance(data, dict) else data
        out = []
        for m in items or []:
            if not isinstance(m, dict):
                continue
            out.append({"id": m.get("id", ""), "name": m.get("name") or m.get("id", ""),
                        "context_length": m.get("context_length"), "pricing": m.get("pricing") or {}})
        return out

    def ping(self) -> tuple:
        """1토큰짜리 호출로 키·모델을 확인한다."""
        if not self._api_key:
            return False, "API 키가 비어 있습니다"
        try:
            r = self.chat([{"role": "user", "content": "ping"}], extra={"max_tokens": 1})
        except LLMError as e:
            return False, str(e)
        used = r.raw.get("model") or self.model
        return True, f"연결 확인: 모델 {used}, 입력 {r.tokens_in}토큰"
