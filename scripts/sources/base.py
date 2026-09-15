"""근거 레코드, HTTP 캐시 클라이언트, 소스 기반 클래스."""
from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional
import requests

GRADES = ("A", "B", "C")

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
                 timeout: int = 20) -> str:
        p = self._key(url, params)
        if not self.no_cache and p.exists():
            c = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - c["fetched_at"] < self.ttl and c["status"] == 200:
                return c["body"]
        status, body = self._fetch(url, params, headers, timeout)
        if status in (429, 503):  # 한도 초과·일시 장애: 3초 뒤 한 번만 재시도
            time.sleep(3)
            status, body = self._fetch(url, params, headers, timeout)
        if status != 200:
            raise requests.HTTPError(f"HTTP {status} for {url}")
        if not self.no_cache:
            p.write_text(json.dumps({"fetched_at": time.time(), "status": status, "url": url,
                                     "body": body}, ensure_ascii=False), encoding="utf-8")
        return body

    def get_json(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
                 timeout: int = 20) -> dict:
        return json.loads(self.get_text(url, params, headers, timeout))

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
