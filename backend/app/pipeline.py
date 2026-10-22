"""Email -> structured analysis -> verified commitments.

The model is only trusted to *read*. Everything that can be checked in
plain code is checked in plain code:
  - dates are resolved by app.dates, not by the model
  - every task must quote the email; quotes are verified against the text
  - the same task arriving twice (or corrected) is merged by app.commitments
"""
from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional

from pydantic import ValidationError

from . import config
from .commitments import apply_task
from .dates import resolve
from .db import Store
from .llm import LLM, LLMError
from .schemas import NO_TASK_CATEGORIES, EmailAnalysis, Profile

SYSTEM_PROMPT = """You read ONE email for a {role} and find what the reader must DO, ATTEND, or REPLY to.
Answer with JSON only.

Rules:
- category: assignment, meeting, reply_needed, announcement, deadline_notice, newsletter, promotion, or other.
- tasks: only real actions, meetings, exams or replies the reader has to handle. Never invent one.
  Newsletters, promotions and plain information have NO tasks (use an empty list).
- title: a short action phrase, max 8 words, e.g. "Submit probability assignment 3".
- kind: task, meeting, exam, or reply.
- when: copy the date and time words EXACTLY as written in the email (e.g. "Friday 23 October, 11:59 PM"). Use "" if the email gives none. Do not work out dates yourself.
- source_quote: copy ONE sentence from the email, word for word, that proves the task.
- If the email corrects or reschedules something, give the task with the NEW date.
- summary: one short sentence about what the email means for the reader.

Example email: "Hi all, the lab report is due this Thursday by 5 PM. Upload it on the portal."
Example answer: {{"category":"assignment","summary":"Lab report due Thursday evening.","tasks":[{{"title":"Submit lab report","kind":"task","when":"Thursday by 5 PM","details":"Upload on the portal","source_quote":"the lab report is due this Thursday by 5 PM."}}]}}"""


MAX_CONSECUTIVE_FAILURES = 3


class ExtractionError(Exception):
    pass


def build_messages(email: Dict[str, Any], profile: Profile) -> Dict[str, str]:
    sent = datetime.fromisoformat(email["sent_at"])
    body = email["body"][: config.MAX_BODY_CHARS]
    user = (
        f"Reader cares most about: {', '.join(profile.priorities) or 'deadlines'}.\n"
        f"Email sent: {sent.strftime('%A %d %B %Y, %I:%M %p')}\n"
        f"From: {email['sender']}\n"
        f"Subject: {email['subject']}\n\n"
        f"{body}"
    )
    return {"system": SYSTEM_PROMPT.format(role=profile.role), "user": user}


def analyze_email(llm: LLM, email: Dict[str, Any], profile: Profile) -> EmailAnalysis:
    """Ask the model, validate the JSON, retry once if it is malformed."""
    msgs = build_messages(email, profile)
    schema = EmailAnalysis.model_json_schema()
    last_error: Optional[Exception] = None
    for _ in range(2):
        try:
            raw = llm.analyze(msgs["system"], msgs["user"], schema)
            return EmailAnalysis.model_validate(raw)
        except (ValidationError, LLMError) as e:
            last_error = e
    raise ExtractionError(str(last_error))


# -- verification helpers ---------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _words(s: str) -> List[str]:
    return re.findall(r"[a-z0-9:]+", s.lower())


def quote_in_email(quote: str, text: str, threshold: float = 0.85) -> bool:
    """Is `quote` really in the email (allowing tiny differences)?"""
    q, t = _norm(quote), _norm(text)
    if len(q) < 8:
        return False
    if q in t:
        return True
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", t):
        if sentence and SequenceMatcher(None, q, sentence).ratio() >= threshold:
            return True
    return False


def phrase_in_email(phrase: str, text: str) -> bool:
    """Do all the date/time words the model gave actually appear in the email?"""
    words = _words(phrase)
    if not words:
        return True
    present = set(_words(text))
    return all(w in present for w in words)


# -- main entry points ------------------------------------------------------
def process_email(store: Store, llm: LLM, email: Dict[str, Any], profile: Profile) -> Dict[str, Any]:
    analysis = analyze_email(llm, email, profile)
    sent_at = datetime.fromisoformat(email["sent_at"])
    full_text = f"{email['subject']}\n{email['body']}"

    tasks = [] if analysis.category in NO_TASK_CATEGORIES else analysis.tasks
    results: List[Dict[str, Any]] = []
    for t in tasks:
        verified = quote_in_email(t.source_quote, full_text)
        when = t.when
        confidence_cap = None
        if when and not phrase_in_email(when, full_text):
            confidence_cap = "low"  # the model made the date words up

        r = resolve(when, sent_at)
        confidence = confidence_cap or r.confidence
        out = apply_task(
            store, email,
            title=t.title, kind=t.kind,
            due_at=r.due.isoformat(timespec="minutes") if r.due else None,
            all_day=r.all_day, date_phrase=when, date_confidence=confidence,
            details=t.details, source_quote=t.source_quote, verified=verified,
        )
        out["title"] = t.title
        results.append(out)

    store.save_email_result(email["id"], "processed", analysis.category, analysis.summary)
    return {"email_id": email["id"], "category": analysis.category, "results": results}


def process_all(
    store: Store,
    llm: LLM,
    on_progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Process every new email oldest-first, so corrections land after the original."""
    profile = store.get_profile()
    todo = store.emails_to_process()
    errors: List[Dict[str, str]] = []
    done = 0
    streak = 0
    for i, email in enumerate(todo, start=1):
        try:
            process_email(store, llm, email, profile)
            done += 1
            streak = 0
        except ExtractionError as e:
            store.save_email_result(email["id"], "error", error=str(e)[:300])
            errors.append({"email_id": email["id"], "error": str(e)[:300]})
            streak += 1
        if on_progress:
            on_progress(i, len(todo), email)
        if streak >= MAX_CONSECUTIVE_FAILURES:
            # the model is probably down; don't grind through the whole inbox
            break
    return {"total": len(todo), "processed": done, "errors": errors}
