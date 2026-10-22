"""Loading the bundled sample inbox and scoring extraction against ground truth."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from . import config
from .commitments import similarity
from .db import Store
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


def evaluate(store: Store) -> Dict[str, Any]:
    """Compare what the app extracted with data/expected.json."""
    expected = json.loads((config.DATA_DIR / "expected.json").read_text(encoding="utf-8"))
    actual = [c for c in store.list_commitments() if c["status"] != "dismissed"]
    used: set = set()
    rows: List[Dict[str, Any]] = []

    for exp in expected["commitments"]:
        best, best_score = None, 0.0
        for a in actual:
            if a["id"] in used or a["kind"] != exp["kind"]:
                continue
            s = similarity(exp["title"], a["title"])
            if s > best_score:
                best, best_score = a, s
        # titles from a small model vary a lot, so be generous on the title
        # and strict on what matters: the date
        if best is None or best_score < 0.25:
            for a in actual:
                if a["id"] in used:
                    continue
                if exp["due"] and a["due_at"] == exp["due"] and a["kind"] == exp["kind"]:
                    best, best_score = a, 0.25
                    break
        found = best is not None
        if found:
            used.add(best["id"])
        date_ok = found and (best["due_at"] == exp["due"])
        flags_ok = found and all(f in best["flags"] for f in exp.get("flags", []))
        rows.append({
            "expected": exp["title"], "found": found, "date_ok": bool(date_ok), "flags_ok": bool(flags_ok),
            "got_title": best["title"] if found else None,
            "got_due": best["due_at"] if found else None, "want_due": exp["due"],
        })

    extras = [a for a in actual if a["id"] not in used]
    n = len(rows)
    found_n = sum(r["found"] for r in rows)
    date_n = sum(r["date_ok"] for r in rows)
    flags_n = sum(r["flags_ok"] for r in rows)
    return {
        "expected": n, "found": found_n, "dates_correct": date_n, "flags_correct": flags_n,
        "false_positives": len(extras), "extras": [e["title"] for e in extras], "rows": rows,
    }
