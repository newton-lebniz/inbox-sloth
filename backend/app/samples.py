"""Loading the bundled sample inbox and scoring extraction against ground truth."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from . import config
from .commitments import similarity
from .db import Store
from .textnorm import content_tokens
from .schemas import EmailIn


def load_sample_emails() -> List[Dict[str, Any]]:
    raw = json.loads((config.DATA_DIR / "sample_emails.json").read_text(encoding="utf-8"))
    return [normalise_email(r) for r in raw]


def normalise_email(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an email dict (accepts 'from' or 'sender') and return DB-shaped fields."""
    e = EmailIn.model_validate(raw)
    return {"id": e.id, "thread_id": e.thread_id, "sender": e.sender,
            "subject": e.subject, "body": e.body, "sent_at": e.sent_at}


def import_sample(store: Store) -> int:
    return store.add_emails(load_sample_emails())


def _eval_tokens(title: str) -> set:
    return content_tokens(title, drop_weak=False)


def _pair_score(exp: Dict[str, Any], act: Dict[str, Any]) -> float:
    """How well an extracted commitment matches an expected one. 0 means 'not the same thing'.
    A match needs real evidence: the same due date AND a shared content word, or a very
    similar title. A shared date alone (two things due Thursday) is not enough."""
    shared = len(_eval_tokens(exp["title"]) & _eval_tokens(act["title"]))
    sim = similarity(exp["title"], act["title"])
    if exp["due"] is None:                       # expected: no date at all
        return 1.0 + sim if act["due_at"] is None and (sim >= 0.4 or shared >= 2) else 0.0
    if act["due_at"] == exp["due"]:
        return 2.0 + sim + 0.1 * shared if shared >= 1 else 0.0
    return sim if sim >= 0.6 else 0.0            # right thing, wrong date


def evaluate(store: Store) -> Dict[str, Any]:
    """Compare what the app extracted with data/expected.json (one-to-one matching)."""
    expected = json.loads((config.DATA_DIR / "expected.json").read_text(encoding="utf-8"))
    actual = [c for c in store.list_commitments() if c["status"] != "dismissed"]

    pairs = []
    for i, exp in enumerate(expected["commitments"]):
        for a in actual:
            score = _pair_score(exp, a)
            if score > 0:
                pairs.append((score, i, a["id"]))
    pairs.sort(key=lambda p: -p[0])
    chosen: Dict[int, Dict[str, Any]] = {}
    used_actual: set = set()
    by_id = {a["id"]: a for a in actual}
    for score, i, aid in pairs:
        if i in chosen or aid in used_actual:
            continue
        chosen[i] = by_id[aid]
        used_actual.add(aid)

    rows: List[Dict[str, Any]] = []
    for i, exp in enumerate(expected["commitments"]):
        got = chosen.get(i)
        rows.append({
            "expected": exp["title"], "found": got is not None,
            "date_ok": bool(got and got["due_at"] == exp["due"]),
            "kind_ok": bool(got and got["kind"] == exp["kind"]),
            "flags_ok": bool(got and all(f in got["flags"] for f in exp.get("flags", []))),
            "got_title": got["title"] if got else None, "got_kind": got["kind"] if got else None,
            "got_due": got["due_at"] if got else None, "want_due": exp["due"], "want_kind": exp["kind"],
            "origin": got.get("origin", "model") if got else None,
        })

    extras = [a for a in actual if a["id"] not in used_actual]
    unexpected_flags = sorted({
        f for i, a in chosen.items() for f in a["flags"]
        if f in ("unverified", "uncertain_date") and f not in expected["commitments"][i].get("flags", [])})
    n = len(rows)
    return {
        "expected": n,
        "found": sum(r["found"] for r in rows),
        "dates_correct": sum(r["date_ok"] for r in rows),
        "kinds_correct": sum(r["kind_ok"] for r in rows),
        "flags_correct": sum(r["flags_ok"] for r in rows),
        "false_positives": len(extras),
        "extras": [e["title"] for e in extras],
        "unexpected_flags": unexpected_flags,
        "from_rules": sum(1 for r in rows if r["origin"] == "rules"),
        "rows": rows,
    }
