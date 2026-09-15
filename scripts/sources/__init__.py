"""소스 로더."""
from __future__ import annotations
import importlib
from typing import Mapping, Optional
from .base import BaseSource, HttpClient, SourceStatus
from .catalog import CATALOG

def _cls(impl: str):
    mod, cls = impl.split(":")
    return getattr(importlib.import_module(mod), cls)

def load_sources(env: Mapping[str, str], http: Optional[HttpClient], kind: Optional[str] = None,
                 only: Optional[list] = None) -> list[BaseSource]:
    out = []
    for c in CATALOG:
        if c["impl"] is None: continue
        if kind and c["kind"] != kind: continue
        if only and c["name"] not in only: continue
        src = _cls(c["impl"])(env, http)
        if src.is_configured(): out.append(src)
    return out

def get_source(name: str, env, http) -> Optional[BaseSource]:
    for c in CATALOG:
        if c["name"] == name and c["impl"]:
            return _cls(c["impl"])(env, http)
    return None

def source_statuses(env: Mapping[str, str], http: Optional[HttpClient], do_ping: bool = False) -> list[SourceStatus]:
    out = []
    for c in CATALOG:
        configured = all(env.get(k) for k in c["env_vars"])
        implemented = c["impl"] is not None
        ok, detail = None, ""
        if not configured:
            detail = "키 없음: " + ", ".join(c["env_vars"])
        elif not implemented:
            detail = "키 있음, 커넥터는 P4에서 구현"
        elif do_ping:
            try:
                ok, detail = _cls(c["impl"])(env, http).ping()
            except Exception as e:  # 네트워크 오류도 상태로 보고
                msg = str(e)
                if "429" in msg:
                    ok, detail = False, "한도 초과(429): 잠시 후 재시도하거나 키를 등록하면 완화됨"
                elif "Timeout" in type(e).__name__ or "timed out" in msg:
                    ok, detail = False, "응답 지연(타임아웃): 네트워크 또는 서버 상태 확인"
                else:
                    ok, detail = False, f"오류: {type(e).__name__}: {msg[:60]}"
        else:
            detail = "설정됨"
        out.append(SourceStatus(c["name"], c["tier"], c["kind"], c["env_vars"], configured, implemented, ok, detail))
    return out
