"""백그라운드 작업 저장소. DESIGN.md 5절·7절(/api/runs).

- start(run_config, force_from) -> job_id : 스레드로 run_pipeline 실행. 보고서당 동시 1개(RunningError).
- get(job_id) / list() : 상태 dict. 상태는 runs/<job_id>.json 에 저장(재시작 후에도 목록에 남는다).
- cancel(job_id) : 취소 이벤트 set(다음 단계·다음 LLM 호출 경계에서 중단).
- subscribe(job_id) -> queue.Queue : 진행 이벤트 큐(SSE 용). 작업이 끝나면 None 을 넣는다.
"""
from __future__ import annotations
import json
import queue
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import config

ACTIVE = ("queued", "running")
MAX_MESSAGES = 20


class RunningError(RuntimeError):
    """같은 보고서의 작업이 이미 실행 중."""


class JobStore:
    def __init__(self, runs_dir: Optional[Path] = None, runner: Optional[Callable] = None):
        self.runs_dir = Path(runs_dir) if runs_dir else config.RUNS_DIR
        self._runner = runner
        self._jobs: dict = {}
        self._cancels: dict = {}
        self._subs: dict = {}
        self._threads: dict = {}
        self._lock = threading.RLock()

    # ---------- 내부 ----------
    def _run_pipeline(self):
        if self._runner:
            return self._runner
        from engine.runner import run_pipeline
        return run_pipeline

    def _path(self, job_id: str) -> Path:
        return self.runs_dir / f"{job_id}.json"

    def _save(self, job: dict) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(job["job_id"]).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._path(job["job_id"]))

    def _publish(self, job_id: str, item) -> None:
        for q in list(self._subs.get(job_id, [])):
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    def _on_progress(self, job_id: str, ev: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["messages"] = (job.get("messages") or [])[-(MAX_MESSAGES - 1):] + [ev]
            if ev.get("tokens"):
                job["tokens"] = dict(ev["tokens"])
            if ev.get("cost_usd") is not None:
                job["cost_usd"] = ev["cost_usd"]
            stage = ev.get("stage")
            if stage and stage != "pipeline":
                job["current_stage"] = stage
                st = next((s for s in job["stages"] if s["name"] == stage), None)
                if st is None:
                    st = {"name": stage, "status": "queued", "steps": 0}
                    job["stages"].append(st)
                st["status"] = ev.get("status", st["status"])
                st["steps"] = ev.get("step", st.get("steps", 0))
                st["message"] = ev.get("message", "")
                if ev.get("status") == "failed":
                    st["error"] = ev.get("message", "")
            self._save(job)
            self._publish(job_id, ev)  # 잠금 안에서 발행 → subscribe 의 재생(replay)과 순서가 어긋나지 않는다

    def _thread_main(self, job_id: str) -> None:
        job = self._jobs[job_id]
        cancel = self._cancels[job_id]
        try:
            with self._lock:
                job["status"] = "running"
                self._save(job)
            summary = self._run_pipeline()(job["report_id"], job["run_config"],
                                           progress=lambda ev: self._on_progress(job_id, ev), cancel=cancel,
                                           force_from=job.get("force_from"), job_id=job_id)
            with self._lock:
                job["status"] = summary.get("status", "done")
                job["error"] = summary.get("error", "")
                job["tokens"] = summary.get("tokens", job.get("tokens"))
                job["cost_usd"] = summary.get("cost_usd", job.get("cost_usd"))
                job["result"] = {k: summary.get(k) for k in ("stages", "started_at", "ended_at")}
                # 단계 결과를 stages 에 합친다(상세 토큰·오류 포함)
                for sr in summary.get("stages") or []:
                    st = next((s for s in job["stages"] if s["name"] == sr["stage"]), None)
                    if st is None:
                        st = {"name": sr["stage"]}
                        job["stages"].append(st)
                    st.update({"status": sr["status"], "steps": sr["steps"], "tokens_in": sr["tokens_in"],
                               "tokens_out": sr["tokens_out"], "cost_usd": sr["cost_usd"], "error": sr["error"],
                               "started_at": sr["started_at"], "ended_at": sr["ended_at"], "outputs": sr["outputs"]})
        except Exception as e:  # 파이프라인 자체 예외
            with self._lock:
                job["status"] = "failed"
                job["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        finally:
            with self._lock:
                job["ended_at"] = datetime.now().isoformat(timespec="seconds")
                if job["status"] in ACTIVE:
                    job["status"] = "done"
                self._save(job)
                self._threads.pop(job_id, None)
            self._publish(job_id, None)

    # ---------- 공개 ----------
    def start(self, run_config: dict, force_from: Optional[str] = None) -> str:
        report_id = (run_config or {}).get("report_id")
        if not report_id:
            raise ValueError("run_config.report_id 가 필요합니다")
        config.report_dir(report_id)  # 형식 검사
        with self._lock:
            for j in self._jobs.values():
                if j["report_id"] == report_id and j["status"] in ACTIVE:
                    raise RunningError(f"{report_id} 는 이미 실행 중입니다 (job {j['job_id']})")
            job_id = f"{datetime.now():%Y%m%d_%H%M%S}_{report_id}_{uuid.uuid4().hex[:6]}"
            job = {"job_id": job_id, "report_id": report_id, "status": "queued",
                   "started_at": datetime.now().isoformat(timespec="seconds"), "ended_at": "",
                   "cost_usd": 0.0, "tokens": {"in": 0, "out": 0}, "stages": [], "messages": [],
                   "run_config": dict(run_config), "force_from": force_from, "error": "", "current_stage": ""}
            self._jobs[job_id] = job
            self._cancels[job_id] = threading.Event()
            self._subs.setdefault(job_id, [])
            self._save(job)
            t = threading.Thread(target=self._thread_main, args=(job_id,), name=f"job-{job_id}", daemon=True)
            self._threads[job_id] = t
            t.start()
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return json.loads(json.dumps(job, ensure_ascii=False))
        p = self._path(job_id)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None

    def list(self) -> list:
        """메모리의 작업 + runs/ 에 저장된 이전 작업. 최신순."""
        out = {}
        if self.runs_dir.exists():
            for p in self.runs_dir.glob("*.json"):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(d, dict) and d.get("job_id"):
                        if d.get("status") in ACTIVE and d["job_id"] not in self._jobs:
                            d["status"] = "failed"  # 프로세스 재시작으로 끊긴 작업
                            d["error"] = d.get("error") or "프로세스 재시작으로 중단"
                        out[d["job_id"]] = d
                except (json.JSONDecodeError, OSError):
                    continue
        with self._lock:
            for j in self._jobs.values():
                out[j["job_id"]] = json.loads(json.dumps(j, ensure_ascii=False))
        return sorted(out.values(), key=lambda d: d.get("started_at", ""), reverse=True)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            ev = self._cancels.get(job_id)
            if not job or not ev or job["status"] not in ACTIVE:
                return False
            ev.set()
            job["cancel_requested"] = True
            self._save(job)
        return True

    def subscribe(self, job_id: str) -> queue.Queue:
        """진행 이벤트 큐. 늦게 붙은 구독자도 놓치지 않도록 지금까지의 최근 이벤트를 먼저 넣어 준다."""
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            job = self._jobs.get(job_id)
            for ev in (job or {}).get("messages") or []:
                q.put_nowait(ev)
            self._subs.setdefault(job_id, []).append(q)
            if job is None or job["status"] not in ACTIVE:
                q.put_nowait(None)  # 이미 끝난 작업이면 바로 종료 신호
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subs.get(job_id, [])
            if q in subs:
                subs.remove(q)

    def is_running(self, report_id: str) -> bool:
        with self._lock:
            return any(j["report_id"] == report_id and j["status"] in ACTIVE for j in self._jobs.values())

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[dict]:
        """테스트·CLI 용: 스레드 종료까지 대기."""
        t = self._threads.get(job_id)
        if t:
            t.join(timeout)
        return self.get(job_id)
