from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import models
from app.db.session import SessionLocal
from app.services.solver_runtime import SolverRuntimeService
from app.utils.ids import new_id
from app.utils.json import dumps, loads


logger = get_logger(__name__)


class JobCancelledError(Exception):
    pass


class JobManager:
    def __init__(self) -> None:
        settings = get_settings()
        self.executor = ThreadPoolExecutor(max_workers=settings.job_max_workers, thread_name_prefix="pulseroute-job")
        self.solver_runtime = SolverRuntimeService()

    def submit_solver_job(self, project_id: str, matrix_id: str, solver_key: str, solver_params: dict) -> str:
        with SessionLocal() as db:
            job = models.Job(
                id=new_id(),
                project_id=project_id,
                matrix_snapshot_id=matrix_id,
                job_type="solve",
                solver_key=solver_key,
                status="queued",
                progress=0.0,
                logs_json=dumps([]),
            )
            db.add(job)
            db.commit()
            job_id = job.id

        self.executor.submit(self._run_solver_job, job_id, solver_params)
        return job_id

    def cancel_job(self, job_id: str) -> None:
        with SessionLocal() as db:
            job = db.get(models.Job, job_id)
            if job is None:
                raise ValueError("Job not found.")
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.completed_at = datetime.utcnow()
            self._append_log(job, "warning", "Cancellation requested.")
            db.commit()

    def _run_solver_job(self, job_id: str, solver_params: dict) -> None:
        stop_flag = [False]
        with SessionLocal() as db:
            job = db.get(models.Job, job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = datetime.utcnow()
            job.progress = 3.0
            self._append_log(job, "info", "Job started.")
            db.commit()

        def progress_callback(payload: dict) -> None:
            with SessionLocal() as callback_db:
                callback_job = callback_db.get(models.Job, job_id)
                if callback_job is None:
                    return
                callback_db.refresh(callback_job)
                if callback_job.cancel_requested:
                    stop_flag[0] = True
                    callback_job.status = "cancelling"
                    self._append_log(callback_job, "warning", "Cancellation signal received.")
                    callback_db.commit()
                    raise JobCancelledError("Job cancelled by user.")
                self._ingest_progress(callback_job, payload)
                callback_db.commit()

        try:
            with SessionLocal() as db:
                job = db.get(models.Job, job_id)
                if job is None:
                    return
                project = db.get(models.Project, job.project_id)
                matrix = db.get(models.MatrixSnapshot, job.matrix_snapshot_id)
                if project is None or matrix is None:
                    raise ValueError("Project or matrix not found for job.")

                result = self.solver_runtime.run_solver(
                    project=project,
                    matrix=matrix,
                    solver_key=job.solver_key or "nsga2",
                    solver_params=solver_params,
                    progress_callback=progress_callback,
                    stop_flag=stop_flag,
                )

                if stop_flag[0]:
                    job.status = "cancelled"
                    job.progress = min(job.progress, 99.0)
                    self._append_log(job, "warning", "Job cancelled before completion.")
                else:
                    primary = result["primary_solution"]
                    runtime_seconds = max(0.0, (datetime.utcnow() - (job.started_at or datetime.utcnow())).total_seconds())
                    primary["summary"]["runtime_seconds"] = round(runtime_seconds, 3)
                    primary["summary"]["algorithm_parameters"] = solver_params
                    solution = models.Solution(
                        id=new_id(),
                        project_id=project.id,
                        solver_key=result["solver_key"],
                        summary_json=dumps(primary["summary"]),
                        routes_json=dumps(primary["routes"]),
                        analytics_json=dumps(primary["analytics"]),
                        raw_payload_json=dumps(primary["raw_payload"]),
                    )
                    db.add(solution)
                    db.flush()
                    job.solution_id = solution.id
                    job.result_json = dumps(result)
                    job.status = "completed"
                    job.progress = 100.0
                    project.status = "solved"
                    self._append_log(job, "info", "Solver completed successfully.")
                job.completed_at = datetime.utcnow()
                db.commit()
        except JobCancelledError as exc:
            with SessionLocal() as db:
                job = db.get(models.Job, job_id)
                if job is None:
                    return
                job.status = "cancelled"
                job.completed_at = datetime.utcnow()
                job.error_json = dumps({"message": str(exc)})
                self._append_log(job, "warning", str(exc))
                db.commit()
        except Exception as exc:
            logger.exception("Solver job failed", exc_info=exc)
            with SessionLocal() as db:
                job = db.get(models.Job, job_id)
                if job is None:
                    return
                job.status = "failed"
                job.error_json = dumps({"message": str(exc)})
                job.completed_at = datetime.utcnow()
                self._append_log(job, "error", str(exc))
                db.commit()

    def _ingest_progress(self, job: models.Job, payload: dict) -> None:
        phase = payload.get("phase", "update")
        message = payload.get("message")
        if phase == "evolution":
            generation = int(payload.get("generation", 0))
            progress = min(95.0, 8.0 + generation * 0.4)
            job.progress = max(job.progress, progress)
            job.message = f"Generation {generation} | rank-1 fronts: {payload.get('rank1_count', 0)}"
        elif phase == "bloodhound_log":
            current_hunt = payload.get("current_hunt")
            total_hunts = payload.get("total_hunts")
            if current_hunt and total_hunts:
                job.progress = max(job.progress, min(95.0, 8.0 + (current_hunt / total_hunts) * 82.0))
                job.message = f"Hunt {current_hunt}/{total_hunts}"
        elif phase == "initialization":
            job.progress = max(job.progress, 6.0)
            job.message = "Solver initialization"

        if message:
            self._append_log(job, "info", message, payload)

    def _append_log(self, job: models.Job, level: str, message: str, context: dict | None = None) -> None:
        items = loads(job.logs_json, [])
        items.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "level": level,
                "message": message,
                "context": context or {},
            }
        )
        job.logs_json = dumps(items[-200:])


job_manager = JobManager()
