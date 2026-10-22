"""Commitment tracking: decide whether an extracted task is NEW or an UPDATE
to something we already track (e.g. a correction email moving a deadline)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set

from .db import Store

# Words that describe the *email*, not the task, so they must not affect matching.
STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "and", "your", "you", "please", "in", "on", "at", "by",
    "submit", "complete", "attend", "send", "reply", "respond", "finish", "do", "make",
    "moved", "rescheduled", "reschedule", "updated", "update", "correction", "corrected",
    "reminder", "revised", "new", "extended", "extension", "deadline", "due", "changed", "change",
}

TITLE_MATCH = 0.8          # similar enough on its own
THREAD_MATCH = 0.4         # similar enough when the email is in the same thread


def _tokens(title: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return [w for w in words if w not in STOPWORDS]


def _numbers(tokens: List[str]) -> Set[str]:
    return {t for t in tokens if t.isdigit()}


def similarity(a: str, b: str) -> float:
    """0..1 title similarity. Numbers must agree: 'assignment 3' is not 'assignment 4'."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    if (_numbers(ta) or _numbers(tb)) and _numbers(ta) != _numbers(tb):
        return 0.0
    seq = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    sa, sb = set(ta), set(tb)
    jac = len(sa & sb) / len(sa | sb)
    return max(seq, jac)


def thread_key(subject: str, thread_id: str = "") -> str:
    """Stable thread id: use the provided one, else the subject minus Re:/Fwd:/Correction: noise."""
    if thread_id:
        return thread_id
    s = subject.lower()
    s = re.sub(r"^\s*((re|fwd?|fw|correction|updated?|reminder|revised|urgent)\s*[:\-]\s*)+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def find_match(
    open_items: List[Dict[str, Any]], title: str, kind: str, thread: str
) -> Optional[Dict[str, Any]]:
    best, best_score = None, 0.0
    for item in open_items:
        if item["kind"] != kind:
            continue
        score = similarity(title, item["title"])
        same_thread = bool(thread) and item["thread_id"] == thread
        needed = THREAD_MATCH if same_thread else TITLE_MATCH
        if score >= needed and score > best_score:
            best, best_score = item, score
    return best


def _add_flag(flags: List[str], flag: str) -> List[str]:
    return flags if flag in flags else [*flags, flag]


def apply_task(
    store: Store,
    email: Dict[str, Any],
    *,
    title: str,
    kind: str,
    due_at: Optional[str],
    all_day: bool,
    date_phrase: str,
    date_confidence: str,
    details: str,
    source_quote: str,
    verified: bool,
) -> Dict[str, Any]:
    """Insert a new commitment or update an existing one. Returns {'action', 'id'}."""
    thread = thread_key(email["subject"], email.get("thread_id", ""))
    match = find_match(store.open_commitments(), title, kind, thread)

    flags: List[str] = []
    if date_confidence in ("low", "none") and date_phrase:
        flags.append("uncertain_date")
    if not date_phrase and not due_at:
        flags.append("no_date")
    if not verified:
        flags.append("unverified")

    if match is None:
        cid = store.insert_commitment({
            "title": title, "kind": kind, "due_at": due_at, "all_day": all_day,
            "date_phrase": date_phrase, "date_confidence": date_confidence,
            "details": details, "thread_id": thread, "flags": flags,
            "email_id": email["id"], "source_quote": source_quote, "sent_at": email["sent_at"],
        })
        store.add_event(cid, email["id"], "created", None, due_at)
        return {"action": "created", "id": cid}

    cid = match["id"]

    # An unverified guess must never overwrite something we already track.
    if not verified:
        return {"action": "ignored_unverified", "id": cid}

    # Out-of-order import: an older email must not undo a newer one.
    if email["sent_at"] < match["last_sent_at"]:
        store.add_event(cid, email["id"], "stale_ignored", match["due_at"], due_at)
        return {"action": "stale_ignored", "id": cid}

    old_due = match["due_at"]
    new_flags = [f for f in match["flags"] if f not in ("uncertain_date", "no_date", "unverified")]
    for f in flags:
        if f != "unverified":
            new_flags = _add_flag(new_flags, f)

    fields: Dict[str, Any] = {
        "source_email_id": email["id"],
        "last_sent_at": email["sent_at"],
        "source_quote": source_quote or match["source_quote"],
    }
    if details:
        fields["details"] = details

    if due_at and old_due and due_at != old_due:
        new_flags = _add_flag(new_flags, "deadline_changed")
        fields.update(due_at=due_at, previous_due_at=old_due, all_day=all_day,
                      date_phrase=date_phrase, date_confidence=date_confidence)
        action = "deadline_changed"
        store.add_event(cid, email["id"], "deadline_changed", old_due, due_at)
    elif due_at and not old_due:
        fields.update(due_at=due_at, all_day=all_day, date_phrase=date_phrase,
                      date_confidence=date_confidence)
        new_flags = [f for f in new_flags if f not in ("no_date", "uncertain_date")]
        for f in flags:
            if f == "uncertain_date":
                new_flags = _add_flag(new_flags, f)
        action = "date_added"
        store.add_event(cid, email["id"], "date_added", None, due_at)
    else:
        action = "confirmed"
        store.add_event(cid, email["id"], "confirmed", old_due, due_at or old_due)
        # keep the old date and its flags if the new email gave no usable date
        if not due_at:
            new_flags = match["flags"]

    fields["flags"] = new_flags
    store.update_commitment(cid, **fields)
    return {"action": action, "id": cid}
