"""SQLite storage. Plain sqlite3, no ORM, one lock so the background
processing thread and API requests can share a connection safely."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .schemas import Profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL DEFAULT '',
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',      -- new | processed | error
    category TEXT,
    summary TEXT,
    error TEXT,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'task',        -- task | meeting | exam | reply
    due_at TEXT,                              -- ISO local datetime, NULL if no date
    all_day INTEGER NOT NULL DEFAULT 0,
    date_phrase TEXT NOT NULL DEFAULT '',     -- words copied from the email
    date_confidence TEXT NOT NULL DEFAULT 'none',  -- high | medium | low | none
    details TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | dismissed
    origin TEXT NOT NULL DEFAULT 'model',     -- model | rules (deterministic safety net)
    thread_id TEXT NOT NULL DEFAULT '',
    flags TEXT NOT NULL DEFAULT '[]',         -- JSON list: deadline_changed, uncertain_date, no_date, unverified
    previous_due_at TEXT,
    source_email_id TEXT NOT NULL,            -- email that last confirmed/changed it
    first_email_id TEXT NOT NULL,
    source_quote TEXT NOT NULL DEFAULT '',
    last_sent_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skipped (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    title TEXT NOT NULL,
    reason TEXT NOT NULL,      -- informational | title_not_in_email | no_evidence | bulk_mail
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    response TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commitment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commitment_id INTEGER NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
    email_id TEXT NOT NULL,
    event TEXT NOT NULL,       -- created | deadline_changed | date_added | confirmed | stale_ignored
    old_due_at TEXT,
    new_due_at TEXT,
    at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:"):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(commitments)")}
        if "origin" not in cols:     # database created by Day 1
            self._conn.execute("ALTER TABLE commitments ADD COLUMN origin TEXT NOT NULL DEFAULT 'model'")
        self._conn.commit()

    # -- low-level helpers -------------------------------------------------
    def _run(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _all(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def _one(self, sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    # -- profile -----------------------------------------------------------
    def get_profile(self) -> Profile:
        row = self._one("SELECT data FROM profile WHERE id = 1")
        return Profile(**json.loads(row["data"])) if row else Profile()

    def set_profile(self, profile: Profile) -> Profile:
        self._run(
            "INSERT INTO profile (id, data) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            [profile.model_dump_json()],
        )
        return profile

    # -- emails ------------------------------------------------------------
    def add_emails(self, emails: List[Dict[str, Any]]) -> int:
        """Insert emails, ignoring ids we already have. Returns number added."""
        added = 0
        for e in emails:
            thread = e.get("thread_id") or ""
            cur = self._run(
                "INSERT OR IGNORE INTO emails (id, thread_id, sender, subject, body, sent_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [e["id"], thread, e["sender"], e["subject"], e["body"], e["sent_at"]],
            )
            added += cur.rowcount
        return added

    def list_emails(self) -> List[Dict[str, Any]]:
        return self._all("SELECT * FROM emails ORDER BY sent_at, id")

    def get_email(self, email_id: str) -> Optional[Dict[str, Any]]:
        return self._one("SELECT * FROM emails WHERE id = ?", [email_id])

    def emails_to_process(self, include_errors: bool = True) -> List[Dict[str, Any]]:
        statuses = ("new", "error") if include_errors else ("new",)
        marks = ",".join("?" for _ in statuses)
        return self._all(
            f"SELECT * FROM emails WHERE status IN ({marks}) ORDER BY sent_at, id", statuses
        )

    def save_email_result(
        self,
        email_id: str,
        status: str,
        category: Optional[str] = None,
        summary: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self._run(
            "UPDATE emails SET status = ?, category = ?, summary = ?, error = ?, processed_at = ? "
            "WHERE id = ?",
            [status, category, summary, error, now_iso(), email_id],
        )

    # -- commitments -------------------------------------------------------
    def open_commitments(self) -> List[Dict[str, Any]]:
        """Commitments that a new email could still update (not dismissed)."""
        rows = self._all("SELECT * FROM commitments WHERE status != 'dismissed' ORDER BY id")
        return [_decode(r) for r in rows]

    def list_commitments(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status:
            rows = self._all(
                "SELECT * FROM commitments WHERE status = ? "
                "ORDER BY (due_at IS NULL), due_at, id",
                [status],
            )
        else:
            rows = self._all("SELECT * FROM commitments ORDER BY (due_at IS NULL), due_at, id")
        return [_decode(r) for r in rows]

    def get_commitment(self, cid: int) -> Optional[Dict[str, Any]]:
        row = self._one("SELECT * FROM commitments WHERE id = ?", [cid])
        if not row:
            return None
        out = _decode(row)
        out["events"] = self._all(
            "SELECT * FROM commitment_events WHERE commitment_id = ? ORDER BY id", [cid]
        )
        return out

    def insert_commitment(self, c: Dict[str, Any]) -> int:
        ts = now_iso()
        cur = self._run(
            "INSERT INTO commitments (title, kind, due_at, all_day, date_phrase, date_confidence, "
            "details, thread_id, flags, source_email_id, first_email_id, source_quote, "
            "last_sent_at, created_at, updated_at, origin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                c["title"], c["kind"], c.get("due_at"), int(c.get("all_day", False)),
                c.get("date_phrase", ""), c.get("date_confidence", "none"), c.get("details", ""),
                c.get("thread_id", ""), json.dumps(c.get("flags", [])), c["email_id"], c["email_id"],
                c.get("source_quote", ""), c["sent_at"], ts, ts, c.get("origin", "model"),
            ],
        )
        return int(cur.lastrowid)

    def update_commitment(self, cid: int, **fields: Any) -> None:
        if not fields:
            return
        if "flags" in fields:
            fields["flags"] = json.dumps(fields["flags"])
        if "all_day" in fields:
            fields["all_day"] = int(fields["all_day"])
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._run(f"UPDATE commitments SET {cols} WHERE id = ?", [*fields.values(), cid])

    def add_event(
        self,
        cid: int,
        email_id: str,
        event: str,
        old_due: Optional[str] = None,
        new_due: Optional[str] = None,
    ) -> None:
        self._run(
            "INSERT INTO commitment_events (commitment_id, email_id, event, old_due_at, new_due_at, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [cid, email_id, event, old_due, new_due, now_iso()],
        )

    # -- skipped (things the model proposed that we refused to track) --------
    def clear_skipped(self, email_id: str) -> None:
        self._run("DELETE FROM skipped WHERE email_id = ?", [email_id])

    def add_skipped(self, email_id: str, title: str, reason: str) -> None:
        self._run("INSERT INTO skipped (email_id, title, reason, at) VALUES (?, ?, ?, ?)",
                  [email_id, title, reason, now_iso()])

    def list_skipped(self) -> List[Dict[str, Any]]:
        return self._all(
            "SELECT s.id, s.email_id, s.title, s.reason, e.subject FROM skipped s "
            "LEFT JOIN emails e ON e.id = s.email_id ORDER BY s.id")

    # -- model response cache (re-running after a code change needs no model) ----
    def cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        row = self._one("SELECT response FROM llm_cache WHERE key = ?", [key])
        return json.loads(row["response"]) if row else None

    def cache_put(self, key: str, model: str, response: Dict[str, Any]) -> None:
        self._run("INSERT OR REPLACE INTO llm_cache (key, model, response, at) VALUES (?, ?, ?, ?)",
                  [key, model, json.dumps(response), now_iso()])

    def cache_clear(self) -> int:
        return self._run("DELETE FROM llm_cache").rowcount

    def cache_size(self) -> int:
        return int(self._one("SELECT COUNT(*) AS n FROM llm_cache")["n"])  # type: ignore[index]

    # -- resets --------------------------------------------------------------
    def reset_results(self) -> None:
        """Forget what was extracted but keep the emails, so they can be re-analysed."""
        with self._lock:
            self._conn.executescript(
                "DELETE FROM commitment_events; DELETE FROM commitments; DELETE FROM skipped; "
                "UPDATE emails SET status='new', category=NULL, summary=NULL, error=NULL, processed_at=NULL;"
            )
            self._conn.commit()

    def reset(self) -> None:
        """Remove emails and results. The model cache is kept on purpose."""
        with self._lock:
            self._conn.executescript(
                "DELETE FROM commitment_events; DELETE FROM commitments; DELETE FROM skipped; "
                "DELETE FROM emails;"
            )
            self._conn.commit()


def _decode(row: Dict[str, Any]) -> Dict[str, Any]:
    row["flags"] = json.loads(row.get("flags") or "[]")
    row["all_day"] = bool(row.get("all_day"))
    return row
