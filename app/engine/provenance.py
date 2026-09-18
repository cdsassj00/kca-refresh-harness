"""실행 묶음(provenance bundle) 보존·검증. **독립 실행 모듈**이며 러너와 연결되어 있지 않다.

계산 결과만 남기면 "그 숫자가 어떻게 나왔는지"를 나중에 확인할 수 없다. 이 모듈은 한 번의 계산을
**입력 데이터(해시) · 계산 코드 · 패키지 환경 · 중간값 · 최종값** 한 묶음으로 폴더에 보존하고,
나중에 그 폴더가 손대지지 않았는지 대조한다.

## 재현은 두 종류다 — 섞지 말 것

1. **계산 재현(deterministic)** — 백테스트·모형 재계산처럼 숫자가 나오는 부분.
   같은 입력이면 항상 같은 결과가 나와야 한다. **이 모듈이 보장 대상으로 삼는 것은 여기다.**
   입력 해시·코드·패키지 버전·중간값을 남겨 두므로, 같은 코드에 같은 입력을 넣어
   같은 값이 나오는지 대조할 수 있다. manifest 의 `reproducibility` 가 `"deterministic"`.

2. **판정 재추적(traceable)** — AI(LLM) 판정.
   온도 0과 seed 고정으로도 완전 재현이 되지 않는다. 그래서 목표는 "재현"이 아니라
   **같은 입력·근거를 보존해 사람이 다시 따라갈 수 있게 하는 것**이다.
   모델·온도·seed·프롬프트 해시는 기록하되, 그 기록은 같은 답을 약속하지 않는다.
   `set_llm_context()` 를 부른 묶음은 `reproducibility` 가 `"traceable"` 로 바뀐다.

## 쓰는 법

    from engine.provenance import open_bundle, verify_bundle

    b = open_bundle("R01", "verify_forecast")          # reports/R01/runs/verify_forecast_<시각>/
    b.add_input("femis.csv", csv_path, source_url="https://www.data.go.kr/...", grade="A", asof="2025-10")
    b.add_code(__file__)
    b.add_intermediate("step1_ratio", {"r_2025": 0.0221})
    b.add_output("backtest", {"error_pct": 34.62})
    summary = b.close()                                 # manifest.json 을 쓰고 요약을 돌려준다

    ok, problems = verify_bundle(summary_dir)           # 해시 대조
    # 명령줄:  python -m engine.provenance verify reports/R01/runs/verify_forecast_20260918_153000

## manifest.json 의 확인 범위

- `inputs` · `code` · `outputs` — 파일마다 SHA-256 을 남기므로 **변조·누락을 모두** 잡는다.
- `intermediate` — 이름 목록만 남긴다(설계 계약). 검증은 파일이 있는지까지만 본다.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import platform
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Optional

import config

# ---------------------------------------------------------------- 상수
REPRO_DETERMINISTIC = "deterministic"   # 계산 재현: 같은 입력이면 같은 결과를 보장 대상으로 삼는다
REPRO_TRACEABLE = "traceable"           # 판정 재추적: 재현이 아니라 "사람이 다시 따라갈 수 있음"이 목표

LLM_NOTE = "LLM 판정은 완전 재현되지 않는다. 이 기록은 재추적용이다."
GRADES = ("A", "B", "C")                # A 1차·공식 / B 2차 / C 추정·시뮬레이션·블라인드 결론
MANIFEST_NAME = "manifest.json"
SUBDIRS = ("inputs", "code", "intermediate", "outputs")


class BundleError(Exception):
    """실행 묶음 생성·검증 중의 오류."""


# ---------------------------------------------------------------- 작은 도우미
def _now() -> datetime:
    return datetime.now()


def _now_iso() -> str:
    return _now().astimezone().isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def _safe_rel(name: str) -> str:
    """묶음 폴더 밖으로 나가는 이름을 막는다. 하위 폴더(`a/b.json`)는 허용."""
    n = str(name or "").strip().replace("\\", "/")
    if not n:
        raise ValueError("이름이 비어 있습니다")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        raise ValueError(f"절대 경로는 이름으로 쓸 수 없습니다: {name}")
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"상위 폴더로 나가는 이름은 쓸 수 없습니다: {name}")
    if not parts:
        raise ValueError(f"이름이 비어 있습니다: {name}")
    return "/".join(parts)


def _json_name(name: str) -> str:
    rel = _safe_rel(name)
    return rel if rel.lower().endswith(".json") else rel + ".json"


def _slug_stage(stage: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", str(stage or "")).strip("_")
    if not s:
        raise ValueError("단계 이름(stage)이 비어 있습니다")
    return s[:60]


def _looks_like_path(value: Any) -> bool:
    """Path 이거나, 실제로 존재하는 파일을 가리키는 문자열이면 참."""
    if isinstance(value, Path):
        return True
    if not isinstance(value, str) or not value or "\n" in value or len(value) > 4096:
        return False
    try:
        return Path(value).is_file()
    except OSError:
        return False


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")))


# ---------------------------------------------------------------- 실행 환경
def _requirements_files() -> list:
    """이 프로젝트의 requirements 파일들(실제 경로 기준). 없는 것은 건너뛴다."""
    cands = [config.APP_DIR / "requirements.txt",          # app/ 독립 프로그램
             config.APP_DIR.parent / "requirements.txt",   # 저장소 루트 하네스
             config.CORE_DIR / "requirements.txt"]         # KCA_CORE_DIR 를 바꿔 쓰는 경우
    out, seen = [], set()
    for p in cands:
        rp = Path(p).resolve()
        if rp in seen:
            continue
        seen.add(rp)
        if rp.is_file():
            out.append(rp)
    return out


_REQ_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?")


def _requirement_names() -> list:
    """requirements 파일에서 패키지 이름만 뽑는다(버전 지정·extras·주석 제거)."""
    names, seen = [], set()
    for path in _requirements_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            m = _REQ_LINE.match(line)
            if not m:
                continue
            name = m.group(1)
            key = name.lower().replace("_", "-")
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
    return names


def collect_packages() -> dict:
    """**이 프로젝트가 실제로 쓰는 패키지만** 이름→설치 버전으로 모은다(전체 freeze 아님).

    requirements 목록이 기준이고, 설치되어 있지 않은 것은 빼고 기록한다."""
    out = {}
    for name in _requirement_names():
        try:
            out[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            continue
        except Exception:  # 메타데이터가 깨진 배포판
            continue
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def collect_environment() -> dict:
    """파이썬 버전·운영체제·프로젝트 패키지 버전."""
    return {"python": platform.python_version(),
            "platform": platform.platform(),
            "packages": collect_packages()}


# ---------------------------------------------------------------- 묶음 폴더
def _report_dir(report_id: str, root: Optional[Any] = None) -> Path:
    if root is None:
        return config.report_dir(report_id)
    if not re.fullmatch(r"R\d{2,3}", report_id or ""):
        raise ValueError(f"보고서 ID 형식 오류: {report_id}")
    return Path(root) / report_id


def open_bundle(report_id: str, stage: str, root: Optional[Any] = None) -> "Bundle":
    """`reports/<id>/runs/<stage>_<YYYYMMDD_HHMMSS>/` 폴더를 만들고 `Bundle` 을 돌려준다.

    report_id: `R01` 형식. stage: 단계 이름(예: `verify_forecast`, `backtest`).
    root: reports 폴더 경로. 기본은 `config.REPORTS_DIR` 이며, 테스트나 다른 저장소를 쓸 때만 지정한다.
    """
    st = _slug_stage(stage)
    started = _now()
    runs = _report_dir(report_id, root) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    bundle_dir = runs / f"{st}_{stamp}"
    n = 2
    while bundle_dir.exists():  # 같은 초에 두 번 열리면 뒤에 번호를 붙인다
        bundle_dir = runs / f"{st}_{stamp}_{n}"
        n += 1
    bundle_dir.mkdir(parents=True)
    return Bundle(report_id=report_id, stage=st, bundle_dir=bundle_dir, created_at=started)


class Bundle:
    """한 번의 계산·판정을 통째로 담는 폴더 한 개. `open_bundle()` 로 만든다."""

    def __init__(self, report_id: str, stage: str, bundle_dir: Path, created_at: datetime):
        self.report_id = report_id
        self.stage = stage
        self.dir = Path(bundle_dir)
        self.created_at = created_at
        self.bundle_id = f"{report_id}_{stage}_{created_at.strftime('%Y%m%d_%H%M%S')}"
        self._inputs: list = []
        self._code: list = []
        self._intermediate: list = []
        self._outputs: list = []
        self._llm: Optional[dict] = None
        self._closed = False
        self.manifest: Optional[dict] = None

    # ---------------------------------------------------------- 내부
    @property
    def manifest_path(self) -> Path:
        return self.dir / MANIFEST_NAME

    def _write(self, rel: str, data: bytes) -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def _copy(self, rel: str, src: Path) -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, p)
        return p

    def _check_open(self) -> None:
        if self._closed:
            raise BundleError("이미 닫힌 실행 묶음에는 더 담을 수 없습니다")

    # ---------------------------------------------------------- 담기
    def add_input(self, name: str, data_or_path: Any, source_url: Optional[str] = None,
                  grade: Optional[str] = None, asof: Optional[str] = None) -> dict:
        """입력을 `inputs/<name>` 으로 복사·저장하고 SHA-256 을 기록한다.

        data_or_path: 파일 경로(Path 또는 존재하는 경로 문자열) · bytes · 문자열 · dict/list.
        dict/list 는 JSON 으로 저장하며 이름에 확장자가 없으면 `.json` 을 붙인다.
        grade: 증거 등급 A(1차·공식)·B(2차)·C(추정·시뮬레이션). asof: 값의 기준 시점(예: `2025-12`).
        """
        self._check_open()
        if grade is not None and str(grade).upper() not in GRADES:
            raise ValueError(f"증거 등급은 A·B·C 중 하나여야 합니다: {grade}")
        if isinstance(data_or_path, (dict, list)):
            rel = f"inputs/{_json_name(name)}"
            path = self._write(rel, _json_bytes(data_or_path))
        elif isinstance(data_or_path, (bytes, bytearray)):
            rel = f"inputs/{_safe_rel(name)}"
            path = self._write(rel, bytes(data_or_path))
        elif _looks_like_path(data_or_path):
            src = Path(data_or_path)
            if not src.is_file():
                raise FileNotFoundError(f"입력 파일이 없습니다: {src}")
            rel = f"inputs/{_safe_rel(name)}"
            path = self._copy(rel, src)
        elif isinstance(data_or_path, Path):
            raise FileNotFoundError(f"입력 파일이 없습니다: {data_or_path}")
        elif isinstance(data_or_path, str):
            rel = f"inputs/{_safe_rel(name)}"
            path = self._write(rel, data_or_path.encode("utf-8"))
        else:
            rel = f"inputs/{_json_name(name)}"
            path = self._write(rel, _json_bytes(data_or_path))
        entry = {"name": _safe_rel(name), "path": rel, "sha256": _sha256_file(path),
                 "bytes": path.stat().st_size, "source_url": source_url or "",
                 "grade": (str(grade).upper() if grade else ""), "asof": asof or ""}
        self._inputs.append(entry)
        return entry

    def add_code(self, path_or_source: Any, name: Optional[str] = None) -> dict:
        """계산에 쓴 코드를 `code/` 에 보존하고 해시를 기록한다.

        path_or_source: 파일 경로이면 그 파일을 복사하고, 아니면 소스 문자열로 보고 그대로 저장한다.
        name: 저장할 이름. 생략하면 파일 이름 또는 `code_<번호>.py`.
        """
        self._check_open()
        if _looks_like_path(path_or_source):
            src = Path(path_or_source)
            rel = f"code/{_safe_rel(name or src.name)}"
            path = self._copy(rel, src)
            origin = str(src)
        else:
            if isinstance(path_or_source, Path):
                raise FileNotFoundError(f"코드 파일이 없습니다: {path_or_source}")
            text = path_or_source if isinstance(path_or_source, str) else str(path_or_source)
            rel = f"code/{_safe_rel(name or f'code_{len(self._code) + 1}.py')}"
            path = self._write(rel, text.encode("utf-8"))
            origin = "(문자열로 전달된 소스)"
        entry = {"name": rel.split("/", 1)[1], "path": rel, "sha256": _sha256_file(path),
                 "bytes": path.stat().st_size, "origin": origin}
        self._code.append(entry)
        return entry

    def add_intermediate(self, name: str, obj: Any) -> dict:
        """중간값을 `intermediate/<name>.json` 으로 저장하고 해시를 기록한다.

        입력·코드·산출물과 같은 수준으로 변조를 탐지하기 위해 이름만이 아니라
        {name, path, sha256, bytes} 를 남긴다. 같은 이름을 다시 넣으면 덮어쓰고 기록도 갱신한다.
        """
        self._check_open()
        rel = f"intermediate/{_json_name(name)}"
        path = self._write(rel, _json_bytes(obj))
        entry = {"name": rel.split("/", 1)[1], "path": rel, "sha256": _sha256_file(path),
                 "bytes": path.stat().st_size}
        self._intermediate = [e for e in self._intermediate
                              if not (isinstance(e, dict) and e.get("path") == rel)]
        self._intermediate.append(entry)
        return entry

    def add_output(self, name: str, obj: Any) -> dict:
        """최종값을 `outputs/<name>.json` 으로 저장하고 해시를 기록한다."""
        self._check_open()
        rel = f"outputs/{_json_name(name)}"
        path = self._write(rel, _json_bytes(obj))
        entry = {"name": rel.split("/", 1)[1], "path": rel, "sha256": _sha256_file(path),
                 "bytes": path.stat().st_size}
        self._outputs.append(entry)
        return entry

    def set_llm_context(self, model: str, temperature: float, seed: Optional[int] = None,
                        prompt_sha: Optional[str] = None) -> dict:
        """**판정 재추적용** 기록. 이 값을 남겨도 같은 답이 다시 나온다는 뜻은 아니다.

        prompt_sha: 프롬프트의 SHA-256. 64자리 16진수가 아니면 그 문자열을 프롬프트 전문으로 보고 해시한다.
        이 메서드를 부른 묶음은 `reproducibility` 가 `traceable` 이 된다.
        """
        self._check_open()
        sha = ""
        if prompt_sha:
            sha = str(prompt_sha).lower() if _is_sha256(prompt_sha) else _sha256_bytes(str(prompt_sha).encode("utf-8"))
        self._llm = {"model": str(model or ""), "temperature": (None if temperature is None else float(temperature)),
                     "seed": seed, "prompt_sha256": sha, "note": LLM_NOTE}
        return dict(self._llm)

    # ---------------------------------------------------------- 닫기
    @property
    def reproducibility(self) -> str:
        """LLM 판정이 섞인 묶음은 `traceable`, 계산만 있으면 `deterministic`."""
        return REPRO_TRACEABLE if self._llm else REPRO_DETERMINISTIC

    def _verify_cmd(self) -> str:
        d = self.dir.resolve()
        for base in (config.CORE_DIR, config.APP_DIR.parent):
            try:
                return f"python -m engine.provenance verify {d.relative_to(Path(base).resolve()).as_posix()}"
            except ValueError:
                continue
        return f"python -m engine.provenance verify {d.as_posix()}"

    def close(self, status: str = "ok", note: str = "") -> dict:
        """`manifest.json` 을 쓰고 요약(= manifest 내용)을 돌려준다. status 는 보통 `ok`·`failed`."""
        manifest = {
            "bundle_id": self.bundle_id,
            "report_id": self.report_id,
            "stage": self.stage,
            "created_at": self.created_at.astimezone().isoformat(timespec="seconds"),
            "closed_at": _now_iso(),
            "status": str(status or "ok"),
            "reproducibility": self.reproducibility,
            "reproducibility_note": (
                "계산 재현(deterministic): 같은 입력이면 같은 결과가 나와야 한다."
                if self.reproducibility == REPRO_DETERMINISTIC else
                "판정 재추적(traceable): 완전 재현이 아니라 같은 입력·근거로 사람이 다시 따라갈 수 있게 한 기록이다."),
            "environment": collect_environment(),
            "inputs": list(self._inputs),
            "code": list(self._code),
            "intermediate": list(self._intermediate),
            "outputs": list(self._outputs),
            "llm": (dict(self._llm) if self._llm else None),
            "note": str(note or ""),
            "verify_cmd": self._verify_cmd(),
        }
        self.manifest_path.write_bytes(_json_bytes(manifest))
        self._closed = True
        self.manifest = manifest
        return manifest


# ---------------------------------------------------------------- 검증
def _entry_path(entry: dict, default_dir: str) -> str:
    rel = str(entry.get("path") or "").strip()
    if rel:
        return rel.replace("\\", "/")
    return f"{default_dir}/{str(entry.get('name') or '').replace(chr(92), '/')}"


def _verify_details(bundle_dir: Any) -> tuple:
    """(행 목록, 문제 목록, manifest). 행: {kind, name, status, detail}."""
    d = Path(bundle_dir)
    rows: list = []
    problems: list = []
    if not d.is_dir():
        return rows, [f"묶음 폴더가 없습니다: {d}"], None
    mpath = d / MANIFEST_NAME
    if not mpath.is_file():
        return rows, [f"{MANIFEST_NAME} 이 없습니다: {d}"], None
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return rows, [f"{MANIFEST_NAME} 을 읽을 수 없습니다: {e}"], None
    if not isinstance(manifest, dict):
        return rows, [f"{MANIFEST_NAME} 형식 오류: 객체가 아닙니다"], None

    recorded: set = {MANIFEST_NAME}

    def check_hashed(kind: str, entries, default_dir: str) -> None:
        for entry in entries or []:
            if not isinstance(entry, dict):
                problems.append(f"{kind}: manifest 항목 형식 오류({entry!r})")
                continue
            rel = _entry_path(entry, default_dir)
            recorded.add(rel)
            name = str(entry.get("name") or rel)
            p = d / rel
            if not p.is_file():
                rows.append({"kind": kind, "name": name, "status": "파일 없음", "detail": rel})
                problems.append(f"{kind} 파일이 없습니다: {rel}")
                continue
            actual = _sha256_file(p)
            expected = str(entry.get("sha256") or "")
            size = p.stat().st_size
            if not expected:
                rows.append({"kind": kind, "name": name, "status": "해시 미기록", "detail": rel})
                problems.append(f"{kind} 해시가 manifest 에 없습니다: {rel}")
            elif actual != expected:
                rows.append({"kind": kind, "name": name, "status": "해시 불일치",
                             "detail": f"기록 {expected[:12]}… ≠ 실제 {actual[:12]}…"})
                problems.append(f"{kind} 파일이 변조되었습니다(해시 불일치): {rel}")
            elif entry.get("bytes") is not None and int(entry["bytes"]) != size:
                rows.append({"kind": kind, "name": name, "status": "크기 불일치",
                             "detail": f"기록 {entry['bytes']}바이트 ≠ 실제 {size}바이트"})
                problems.append(f"{kind} 파일 크기가 다릅니다: {rel}")
            else:
                rows.append({"kind": kind, "name": name, "status": "일치", "detail": f"{size:,}바이트"})

    check_hashed("입력", manifest.get("inputs"), "inputs")
    check_hashed("코드", manifest.get("code"), "code")
    check_hashed("산출물", manifest.get("outputs"), "outputs")

    # 중간값도 해시로 검증한다. 옛 묶음(이름 문자열 목록)은 존재 여부까지만 본다.
    legacy_mid = [x for x in (manifest.get("intermediate") or []) if not isinstance(x, dict)]
    hashed_mid = [x for x in (manifest.get("intermediate") or []) if isinstance(x, dict)]
    check_hashed("중간값", hashed_mid, "intermediate")
    for raw in legacy_mid:
        name = str(raw).replace("\\", "/")
        rel = f"intermediate/{name if name.lower().endswith('.json') else name + '.json'}"
        recorded.add(rel)
        if (d / rel).is_file():
            rows.append({"kind": "중간값", "name": name, "status": "있음(해시 없음)", "detail": f"{rel} — 옛 형식 묶음"})
        else:
            rows.append({"kind": "중간값", "name": name, "status": "파일 없음", "detail": rel})
            problems.append(f"중간값 파일이 없습니다: {rel}")

    # 기록에 없는 파일(나중에 몰래 끼워 넣은 것)
    for sub in SUBDIRS:
        base = d / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(d).as_posix()
            if rel in recorded:
                continue
            rows.append({"kind": "기타", "name": rel, "status": "기록에 없음", "detail": "manifest 에 없는 파일"})
            problems.append(f"manifest 에 기록되지 않은 파일이 있습니다: {rel}")

    return rows, problems, manifest


def verify_bundle(bundle_dir: Any) -> tuple:
    """저장된 해시와 실제 파일을 다시 대조한다. 돌려주는 값: `(문제 없음 여부, 한국어 문제 목록)`."""
    _rows, problems, _manifest = _verify_details(bundle_dir)
    return (not problems), problems


# ---------------------------------------------------------------- 얇은 헬퍼
def _error_pct(forecast: float, actual: float):
    """오차율(%) = (전망 - 실적) / 실적 × 100. 부호를 유지한다(양수=과대 전망, 음수=과소 전망)."""
    if actual == 0:
        return None
    return (forecast - actual) / actual * 100.0


def bundled_backtest(report_id: str, claim_id: str, forecast: float, actual: float, unit: str,
                     sources, code_note: str = "") -> dict:
    """전망 대비 실적 오차를 계산하면서 그 과정을 자동으로 실행 묶음에 담는 **예시 함수**.

    오차율 = (전망 - 실적) / 실적 × 100 (부호 유지). 실적이 0이면 오차율은 `None`.
    sources: 실적치의 근거 목록 `[{"url":…, "grade":"A", "asof":"2025-12", "note":…}, …]`.
    돌려주는 값에는 계산 결과와 묶음 위치(`bundle_dir`)가 함께 들어간다.
    이 계산은 **계산 재현(deterministic)** 이다 — LLM 이 끼어들지 않는다.
    """
    if isinstance(sources, dict):
        sources = [sources]
    sources = list(sources or [])
    src0 = sources[0] if sources and isinstance(sources[0], dict) else {}

    b = open_bundle(report_id, "backtest")
    b.add_input("forecast.json",
                {"claim_id": claim_id, "value": forecast, "unit": unit, "note": "원 보고서의 전망치"})
    b.add_input("actual.json",
                {"claim_id": claim_id, "value": actual, "unit": unit, "note": "오늘 확인한 실적치"},
                source_url=src0.get("url"), grade=src0.get("grade"), asof=src0.get("asof"))
    b.add_input("sources.json", sources)
    b.add_code(inspect.getsource(_error_pct), name="error_pct.py")

    diff = forecast - actual
    b.add_intermediate("diff", {"formula": "전망 - 실적", "forecast": forecast, "actual": actual, "diff": diff})

    pct = _error_pct(forecast, actual)
    result = {"claim_id": claim_id, "forecast": forecast, "actual": actual, "unit": unit,
              "diff": diff, "error_pct": (None if pct is None else round(pct, 6)),
              "formula": "(전망 - 실적) / 실적 × 100",
              "direction": ("과대 전망" if pct and pct > 0 else "과소 전망" if pct and pct < 0 else
                            "일치" if pct == 0 else "산출 불가(실적 0)"),
              "grade": (src0.get("grade") or "C"), "asof": (src0.get("asof") or ""),
              "sources": sources, "note": code_note}
    b.add_output("backtest", result)
    manifest = b.close(status=("ok" if pct is not None else "failed"), note=code_note)

    out = dict(result)
    out.update({"bundle_id": manifest["bundle_id"], "bundle_dir": str(b.dir),
                "reproducibility": manifest["reproducibility"], "verify_cmd": manifest["verify_cmd"]})
    return out


# ---------------------------------------------------------------- 명령줄
def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(s))


def _pad(s: str, w: int) -> str:
    return str(s) + " " * max(0, w - _width(s))


def _print_table(rows: list) -> None:
    headers = ("구분", "이름", "결과", "비고")
    keys = ("kind", "name", "status", "detail")
    widths = [max(_width(h), *(_width(r.get(k, "")) for r in rows)) if rows else _width(h)
              for h, k in zip(headers, keys)]
    line = "  ".join(_pad(h, w) for h, w in zip(headers, widths)).rstrip()
    print(line)
    print("-" * min(_width(line) + 2, 100))
    for r in rows:
        print("  ".join(_pad(r.get(k, ""), w) for k, w in zip(keys, widths)).rstrip())


def _cmd_verify(bundle_dir: str) -> int:
    rows, problems, manifest = _verify_details(bundle_dir)
    print(f"실행 묶음 검증: {Path(bundle_dir)}")
    if manifest:
        repro = manifest.get("reproducibility")
        repro_ko = "계산 재현(결정적)" if repro == REPRO_DETERMINISTIC else "판정 재추적(비결정적)"
        env = manifest.get("environment") or {}
        print(f"묶음 ID: {manifest.get('bundle_id', '')} · 보고서: {manifest.get('report_id', '')} · "
              f"단계: {manifest.get('stage', '')} · 상태: {manifest.get('status', '')}")
        print(f"재현 유형: {repro_ko} · 만든 때: {manifest.get('created_at', '')} · "
              f"파이썬 {env.get('python', '?')} / 패키지 {len(env.get('packages') or {})}개")
        if manifest.get("llm"):
            print(f"LLM 기록: {manifest['llm'].get('model', '')} · 온도 {manifest['llm'].get('temperature')} · "
                  f"{manifest['llm'].get('note', '')}")
    print()
    if rows:
        _print_table(rows)
        print()
    if problems:
        print(f"결과: 실패 - 검사 {len(rows)}건 중 문제 {len(problems)}건")
        for msg in problems:
            print(f"  · {msg}")
        return 1
    print(f"결과: 통과 - 검사 {len(rows)}건, 문제 없음")
    return 0


def _make_console_safe() -> None:
    """한국어 윈도 콘솔(cp949)에서 표를 찍다가 UnicodeEncodeError 로 죽지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _make_console_safe()
    if len(args) >= 2 and args[0] == "verify":
        return _cmd_verify(args[1])
    print("사용법: python -m engine.provenance verify <묶음 폴더>", file=sys.stderr)
    print("  예:   python -m engine.provenance verify reports/R01/runs/backtest_20260918_153000", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
