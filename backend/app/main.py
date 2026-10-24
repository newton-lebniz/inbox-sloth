"""FastAPI app: JSON API under /api, the frontend served from /."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import config
from .db import Store
from .llm import LLM, OllamaLLM
from .pipeline import process_all
from .samples import import_sample, normalise_email
from .schemas import Profile


class StatusUpdate(BaseModel):
    status: str  # pending | done | dismissed


class ProcessJob:
    """Progress of a background 'analyse my emails' run (CPU inference is slow)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.state = "idle"        # idle | running | done
        self.total = 0
        self.done = 0
        self.current = ""
        self.errors: List[Dict[str, str]] = []
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": self.state, "total": self.total, "done": self.done,
            "current": self.current, "errors": self.errors,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1) if self.started_at else 0,
        }


def create_app(store: Optional[Store] = None, llm: Optional[LLM] = None) -> FastAPI:
    store = store or Store(config.DB_PATH)
    llm = llm or OllamaLLM()
    job = ProcessJob()
    app = FastAPI(title="Inbox Sloth", version="0.1.0")

    def run_job() -> None:
        def progress(i: int, total: int, email: Dict[str, Any]) -> None:
            job.done, job.total = i, total
            job.current = email["subject"]

        try:
            result = process_all(store, llm, progress)
            job.errors = result["errors"]
        finally:
            job.state = "done"
            job.finished_at = time.time()

    # -- health & profile ----------------------------------------------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        if hasattr(llm, "health"):
            return llm.health()  # type: ignore[attr-defined]
        return {"ok": True, "model": "fake", "error": None}

    @app.get("/api/profile")
    def get_profile() -> Profile:
        return store.get_profile()

    @app.put("/api/profile")
    def put_profile(profile: Profile) -> Profile:
        profile.onboarded = True
        return store.set_profile(profile)

    # -- emails --------------------------------------------------------------
    @app.post("/api/emails/sample")
    def load_sample() -> Dict[str, Any]:
        return {"added": import_sample(store), "total": len(store.list_emails())}

    @app.post("/api/emails")
    def add_emails(emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            clean = [normalise_email(e) for e in emails]
        except ValidationError as e:
            raise HTTPException(422, detail=e.errors(include_url=False, include_context=False))
        return {"added": store.add_emails(clean), "total": len(store.list_emails())}

    @app.get("/api/emails")
    def list_emails() -> List[Dict[str, Any]]:
        # the list view does not need the full body
        return [{k: v for k, v in e.items() if k != "body"} for e in store.list_emails()]

    @app.get("/api/emails/{email_id}")
    def get_email(email_id: str) -> Dict[str, Any]:
        email = store.get_email(email_id)
        if not email:
            raise HTTPException(404, "Email not found")
        return email

    # -- processing ----------------------------------------------------------
    @app.post("/api/process")
    def start_process(wait: bool = False) -> Dict[str, Any]:
        if hasattr(llm, "health"):
            h = llm.health()  # type: ignore[attr-defined]
            if not h["ok"]:
                raise HTTPException(503, detail=h["error"])
        with job.lock:
            if job.state == "running":
                return job.snapshot()
            todo = len(store.emails_to_process())
            job.reset()
            job.state, job.total, job.started_at = "running", todo, time.time()
        if wait:
            run_job()
        else:
            threading.Thread(target=run_job, daemon=True).start()
        return job.snapshot()

    @app.get("/api/process/status")
    def process_status() -> Dict[str, Any]:
        return job.snapshot()

    # -- commitments ---------------------------------------------------------
    @app.get("/api/commitments")
    def list_commitments(status: Optional[str] = None) -> List[Dict[str, Any]]:
        return store.list_commitments(status)

    @app.get("/api/commitments/{cid}")
    def get_commitment(cid: int) -> Dict[str, Any]:
        c = store.get_commitment(cid)
        if not c:
            raise HTTPException(404, "Commitment not found")
        return c

    @app.patch("/api/commitments/{cid}")
    def set_status(cid: int, body: StatusUpdate) -> Dict[str, Any]:
        if body.status not in ("pending", "done", "dismissed"):
            raise HTTPException(422, "status must be pending, done or dismissed")
        if not store.get_commitment(cid):
            raise HTTPException(404, "Commitment not found")
        store.update_commitment(cid, status=body.status)
        return store.get_commitment(cid)  # type: ignore[return-value]

    @app.get("/api/skipped")
    def list_skipped() -> List[Dict[str, Any]]:
        """Things the model proposed that the sloth refused to track, with the reason."""
        return store.list_skipped()

    @app.post("/api/reset")
    def reset() -> Dict[str, str]:
        store.reset()
        job.reset()
        return {"ok": "true"}

    if config.FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
    return app


app = create_app()
