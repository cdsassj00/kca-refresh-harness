"""근거 레코드, HTTP 캐시 클라이언트, 소스 기반 클래스."""
from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional
import requests

GRADES = ("A", "B", "C")

# 재시도 정책: 429·5xx 를 지수 백오프로 최대 3번 더 시도한다(1초 → 2초 → 4초).
RETRY_MAX = 3
RETRY_BASE_SECONDS = 1.0

@dataclass
class EvidenceRecord:
    source: str
    id: str
    url: str
    title: str
    date: Optional[str]
    snippet: str
    grade: str
    retrieved_at: str
    query: str
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.grade not in GRADES:
            raise ValueError(f"증거 등급은 A/B/C 중 하나여야 합니다: {self.grade}")

    def to_json(self) -> dict:
        return asdict(self)

@dataclass
class SourceStatus:
    name: str
    tier: str
    kind: str
    env_vars: list
    configured: bool
    implemented: bool
    ok: Optional[bool]
    detail: str

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

class HttpClient:
    """GET 전용, JSON 파일 캐시. 키 값은 캐시 키에 넣지 않는다(헤더는 캐시 키 제외)."""
    def __init__(self, cache_dir: Path, ttl_days: int = 7, no_cache: bool = False,
                 user_agent: str = "kca-refresh/0.1"):
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_days * 86400; self.no_cache = no_cache; self.user_agent = user_agent

    def _key(self, url: str, params: Optional[dict]) -> Path:
        raw = json.dumps([url, sorted((params or {}).items())], ensure_ascii=False)
        return self.cache_dir / (hashlib.sha1(raw.encode("utf-8")).hexdigest() + ".json")

    def _fetch(self, url, params, headers, timeout) -> tuple[int, str]:
        h = {"User-Agent": self.user_agent}; h.update(headers or {})
        resp = requests.get(url, params=params, headers=h, timeout=timeout)
        return resp.status_code, resp.text

    def get_text(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
                 timeout: int = 20, cache_url: Optional[str] = None) -> str:
        """cache_url: 캐시 키·캐시 기록에 남길 주소.

        ECOS처럼 **인증키가 주소 경로에 들어가는** API는 키를 가린 주소를 넘긴다.
        그러면 캐시 파일에 키가 글자 그대로 남지 않는다(질의 문자열에 든 키는
        원래도 해시로만 쓰이고 기록되지 않는다). 안 넘기면 예전과 똑같이 동작한다.
        """
        ck = cache_url or url
        p = self._key(ck, params)
        if not self.no_cache and p.exists():
            c = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - c["fetched_at"] < self.ttl and c["status"] == 200:
                return c["body"]
        status, body = self._fetch(url, params, headers, timeout)
        # 한도 초과(429)·일시 장애(5xx)는 지수 백오프로 다시 시도한다.
        # 상대 서버에 부담을 주지 않겠다는 약속(각 API 이용 조건)을 코드로 지킨다.
        for attempt in range(RETRY_MAX):
            if status != 429 and not (500 <= status < 600):
                break
            time.sleep(RETRY_BASE_SECONDS * (2 ** attempt))  # 1초 → 2초 → 4초
            status, body = self._fetch(url, params, headers, timeout)
        if status != 200:
            raise requests.HTTPError(f"HTTP {status} for {url}")
        if not self.no_cache:
            p.write_text(json.dumps({"fetched_at": time.time(), "status": status, "url": ck,
                                     "body": body}, ensure_ascii=False), encoding="utf-8")
        return body

    def get_json(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
                 timeout: int = 20, cache_url: Optional[str] = None) -> dict:
        return json.loads(self.get_text(url, params, headers, timeout, cache_url))

class BaseSource:
    name: str = ""; tier: str = ""; kind: str = ""; env_vars: list = []; default_grade: str = "B"

    def __init__(self, env: Mapping[str, str], http: Optional[HttpClient]):
        self.env = env; self.http = http

    def is_configured(self) -> bool:
        return all(self.env.get(k) for k in self.env_vars)

    def search(self, query: str, since: Optional[str] = None, until: Optional[str] = None,
               limit: int = 20) -> list[EvidenceRecord]:
        raise NotImplementedError

    def ping(self) -> tuple[bool, str]:
        raise NotImplementedError

    def record(self, **kw) -> EvidenceRecord:
        kw.setdefault("source", self.name); kw.setdefault("grade", self.default_grade)
        kw.setdefault("retrieved_at", now_iso()); kw.setdefault("extra", {})
        return EvidenceRecord(**kw)
