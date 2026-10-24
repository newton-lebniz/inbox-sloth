"""Email -> structured analysis -> verified commitments.

The model is only trusted to *read*. Everything that can be checked in
plain code is checked in plain code:
  - dates are resolved by app.dates, not by the model
  - every task must quote the email; quotes are verified against the text
  - the same task arriving twice (or corrected) is merged by app.commitments
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from . import config
from .commitments import apply_task
from .dates import Resolved, resolve
from .db import Store
from .grounding import (Grounding, fallback_candidates, ground_task, infer_kind, looks_bulk,
                        refine_title)
from .llm import LLM, LLMError
from .schemas import NO_TASK_CATEGORIES, EmailAnalysis, ExtractedTask, Profile
from .textnorm import date_tokens, text_date_tokens

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


def _cache_key(llm: LLM, msgs: Dict[str, str], schema: Dict[str, Any]) -> str:
    model = getattr(llm, "model", type(llm).__name__)
    blob = "\x00".join([str(model), msgs["system"], msgs["user"], json.dumps(schema, sort_keys=True)])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def analyze_email(llm: LLM, email: Dict[str, Any], profile: Profile,
                  store: Optional[Store] = None) -> EmailAnalysis:
    """Ask the model, validate the JSON, retry once if it is malformed. With a store, valid
    answers are cached so re-running after a code change needs no model calls."""
    msgs = build_messages(email, profile)
    schema = EmailAnalysis.model_json_schema()
    key = _cache_key(llm, msgs, schema) if (store is not None and config.USE_CACHE) else None
    if key:
        hit = store.cache_get(key)  # type: ignore[union-attr]
        if hit is not None:
            try:
                return EmailAnalysis.model_validate(hit)
            except ValidationError:
                pass
    last_error: Optional[Exception] = None
    for _ in range(2):
        try:
            raw = llm.analyze(msgs["system"], msgs["user"], schema)
            analysis = EmailAnalysis.model_validate(raw)
        except (ValidationError, LLMError) as e:
            last_error = e
            continue
        if key:
            store.cache_put(key, str(getattr(llm, "model", "?")), raw)  # type: ignore[union-attr]
        return analysis
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
    """Do all the date/time words the model gave appear in the email? (Oct = October, 9th = 9)"""
    need = date_tokens(phrase)
    return not need or need <= text_date_tokens(text)


# -- main entry points ------------------------------------------------------
def process_email(store: Store, llm: LLM, email: Dict[str, Any], profile: Profile) -> Dict[str, Any]:
    analysis = analyze_email(llm, email, profile, store)
    sent_at = datetime.fromisoformat(email["sent_at"])
    subject, body = email["subject"], email["body"]
    store.clear_skipped(email["id"])

    bulk = analysis.category in NO_TASK_CATEGORIES or looks_bulk(subject, body)
    proposed: List[Tuple[ExtractedTask, str]] = [(t, "model") for t in ([] if bulk else analysis.tasks)]
    if bulk:
        for t in analysis.tasks:
            store.add_skipped(email["id"], t.title, "bulk_mail")

    accepted: List[Tuple[ExtractedTask, Grounding, str]] = []
    for t, origin in proposed:
        g = ground_task(subject, body, t, sent_at)
        if g.ok:
            accepted.append((t, g, origin))
        else:
            store.add_skipped(email["id"], t.title, g.reason)

    if not accepted and not bulk:            # the model found nothing usable: try the rules
        for t in fallback_candidates(subject, body, sent_at, analysis.category):
            g = ground_task(subject, body, t, sent_at)
            if g.ok:
                accepted.append((t, g, "rules"))

    results: List[Dict[str, Any]] = []
    for t, g, origin in accepted:
        kind = infer_kind(t.kind, t.title, subject, g.sentence)
        title = refine_title(t.title, kind, subject)
        r = resolve(g.date_text, sent_at) if g.date_text else Resolved(None, False, "none")
        confidence = "low" if (g.healed and r.due is not None) else r.confidence
        out = apply_task(
            store, email,
            title=title, kind=kind,
            due_at=r.due.isoformat(timespec="minutes") if r.due else None,
            all_day=r.all_day, date_phrase=g.date_text[:80], date_confidence=confidence,
            details=t.details, source_quote=g.sentence, verified=g.strong, origin=origin,
        )
        out["title"] = title
        out["origin"] = origin
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
