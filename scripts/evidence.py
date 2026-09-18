"""근거 수집 CLI. papers / stats / law / bills / doctor (news는 다음 단계)."""
from __future__ import annotations
import argparse, json, os, re, sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `python scripts/evidence.py ...`로 직접 실행하면 sys.path[0]이 scripts/ 이므로 프로젝트 루트를 넣어 준다.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
from scripts.sources import load_sources, source_statuses
from scripts.sources.base import HttpClient

def load_env(root: Path = ROOT) -> dict:
    """키를 모은다. 루트 `.env` 를 먼저 보고, 없는 값은 `app/.env` 에서 채운다.

    키를 한 군데만 적어도 두 실행 방식(하네스·독립 프로그램)이 모두 쓰도록 하기 위함이다.
    같은 이름이 양쪽에 있으면 루트 `.env` 가 이긴다.
    """
    env = dict(dotenv_values(root / ".env")) if (root / ".env").exists() else {}
    app_env_path = root / "app" / ".env"
    if app_env_path.exists():
        for k, v in dotenv_values(app_env_path).items():
            if v and not env.get(k):
                env[k] = v
    for k, v in os.environ.items():
        if k in env or k.endswith(("_API_KEY", "_MAILTO", "_OC", "_CLIENT_ID", "_CLIENT_SECRET", "_TOKEN", "_INSTTOKEN")):
            env.setdefault(k, v)
    return {k: v for k, v in env.items() if v}

def _slug(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", s).strip("_")[:40] or "q"

# 하위 명령 → 카탈로그의 종류(kind). 같은 방식으로 돌고 저장 파일 이름만 달라진다.
KIND_BY_CMD = {"papers": "papers", "stats": "stats", "law": "law", "bills": "bills"}

def run_search(args, env, http, kind: str) -> list[dict]:
    """종류가 같은 소스를 모두 불러 결과를 JSONL 한 파일로 모은다."""
    only = args.sources.split(",") if args.sources else None
    rows, counts = [], {}
    for src in load_sources(env, http, kind=kind, only=only):
        try:
            recs = src.search(args.q, since=args.since, until=args.until, limit=args.limit)
        except Exception as e:
            print(f"[{src.name}] 오류: {type(e).__name__}: {e}", file=sys.stderr); recs = []
        counts[src.name] = len(recs); rows += [r.to_json() for r in recs]
    out = Path(args.out) if args.out else ROOT / "kb" / "evidence" / f"{datetime.now():%Y%m%d_%H%M%S}_{kind}_{_slug(args.q)}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"질의: {args.q}  기간: {args.since or '-'}~{args.until or '-'}")
    if not counts: print("  (이 종류에 쓸 수 있는 소스가 없습니다. 키를 넣었는지 doctor 로 확인하세요)")
    for k, v in counts.items(): print(f"  {k:<18} {v:>4}건")
    print(f"저장: {out}  (총 {len(rows)}건)")
    return rows

def run_papers(args, env, http) -> list[dict]:
    return run_search(args, env, http, "papers")

def run_doctor(env, http, do_ping: bool):
    return source_statuses(env, http, do_ping=do_ping)

def _print_doctor(statuses):
    print(f"{'소스':<18}{'등급':<5}{'종류':<8}{'키':<6}{'구현':<6}{'연결':<6}비고")
    for s in statuses:
        key = "있음" if s.configured and s.env_vars else ("불필요" if s.configured else "없음")
        impl = "예" if s.implemented else "대기"
        ok = "-" if s.ok is None else ("OK" if s.ok else "실패")
        print(f"{s.name:<18}{s.tier:<5}{s.kind:<8}{key:<6}{impl:<6}{ok:<6}{s.detail}")

def _add_common(parser, defaults: bool):
    """캐시 옵션. 최상위 파서에는 기본값을, 하위 명령 파서에는 SUPPRESS를 줘서
    `evidence.py --no-cache papers ...`와 `evidence.py papers ... --no-cache` 둘 다 허용하고
    하위 명령의 기본값이 최상위 값을 덮어쓰지 않게 한다."""
    parser.add_argument("--cache-dir", default=str(ROOT / "kb" / "cache") if defaults else argparse.SUPPRESS,
                        help="HTTP 캐시 디렉터리 (기본 kb/cache)")
    parser.add_argument("--no-cache", action="store_true", default=False if defaults else argparse.SUPPRESS,
                        help="캐시를 읽지도 쓰지도 않음")

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evidence", description="근거 소스 수집·상태 점검")
    _add_common(ap, defaults=True)
    common = argparse.ArgumentParser(add_help=False); _add_common(common, defaults=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd, helptext in (("papers", "논문·보고서 검색"),
                          ("stats", "통계표·시계열 검색 (KOSIS·ECOS·공공데이터포털)"),
                          ("law", "법령 검색 (법제처 국가법령정보)"),
                          ("bills", "의안 검색 (열린국회정보)")):
        p = sub.add_parser(cmd, help=helptext, parents=[common])
        p.add_argument("--q", required=True); p.add_argument("--since"); p.add_argument("--until")
        p.add_argument("--limit", type=int, default=20); p.add_argument("--sources"); p.add_argument("--out")
    d = sub.add_parser("doctor", help="소스 키·연결 상태", parents=[common])
    d.add_argument("--json", action="store_true"); d.add_argument("--no-ping", action="store_true")
    args = ap.parse_args(argv)
    env = load_env(); http = HttpClient(Path(args.cache_dir), no_cache=args.no_cache)
    if args.cmd in KIND_BY_CMD:
        run_search(args, env, http, KIND_BY_CMD[args.cmd]); return 0
    statuses = run_doctor(env, http, do_ping=not args.no_ping)
    if args.json: print(json.dumps([asdict(s) for s in statuses], ensure_ascii=False, indent=1))
    else: _print_doctor(statuses)
    return 0

if __name__ == "__main__":
    sys.exit(main())
