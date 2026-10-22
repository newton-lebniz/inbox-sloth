"""Command line helper: run the whole pipeline without the web UI.

    python -m app.cli check          # is Ollama up, is the model pulled?
    python -m app.cli demo           # reset, load sample inbox, process it, score it
    python -m app.cli import-sample  # just load the 18 sample emails
    python -m app.cli process        # analyse any new emails
    python -m app.cli tasks          # print tracked commitments
    python -m app.cli eval           # score against data/expected.json
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

from . import config
from .db import Store
from .llm import OllamaLLM
from .pipeline import process_all
from .samples import evaluate, import_sample


def _fmt_due(c) -> str:
    if not c["due_at"]:
        return "no date"
    d = datetime.fromisoformat(c["due_at"])
    return d.strftime("%a %d %b") + ("" if c["all_day"] else d.strftime(" %H:%M"))


def cmd_check(store: Store, llm: OllamaLLM) -> int:
    h = llm.health()
    print(f"Ollama: {llm.url}   model: {llm.model}")
    print("OK" if h["ok"] else f"PROBLEM: {h['error']}")
    return 0 if h["ok"] else 1


def cmd_process(store: Store, llm: OllamaLLM) -> int:
    started = time.time()

    def progress(i, total, email):
        row = store.get_email(email["id"])
        print(f"[{i}/{total}] {email['id']} {row['status']:<9} {row['category'] or '-':<16} {email['subject'][:50]}")

    out = process_all(store, llm, progress)
    print(f"\nProcessed {out['processed']}/{out['total']} emails in {time.time() - started:.0f}s")
    for err in out["errors"]:
        print(f"  ERROR {err['email_id']}: {err['error']}")
    return 0


def cmd_tasks(store: Store, llm: OllamaLLM) -> int:
    for c in store.list_commitments():
        flags = f"  [{', '.join(c['flags'])}]" if c["flags"] else ""
        print(f"#{c['id']:<3} {c['kind']:<8} {_fmt_due(c):<16} {c['title']}{flags}")
        if "deadline_changed" in c["flags"] and c["previous_due_at"]:
            old = datetime.fromisoformat(c["previous_due_at"]).strftime("%a %d %b")
            print(f"       was {old}")
    return 0


def cmd_eval(store: Store, llm: OllamaLLM) -> int:
    r = evaluate(store)
    print(f"Commitments found:   {r['found']}/{r['expected']}")
    print(f"Dates correct:       {r['dates_correct']}/{r['expected']}")
    print(f"Changes flagged:     {r['flags_correct']}/{r['expected']}")
    print(f"False positives:     {r['false_positives']}  {r['extras']}")
    print()
    for row in r["rows"]:
        mark = "OK " if row["found"] and row["date_ok"] else "BAD"
        print(f"{mark} {row['expected']:<38} want {row['want_due']}  got {row['got_due']}  ({row['got_title']})")
    return 0


def cmd_demo(store: Store, llm: OllamaLLM) -> int:
    if cmd_check(store, llm):
        return 1
    store.reset()
    print(f"Loaded {import_sample(store)} sample emails\n")
    cmd_process(store, llm)
    print()
    cmd_tasks(store, llm)
    print()
    return cmd_eval(store, llm)


COMMANDS = {
    "check": cmd_check,
    "demo": cmd_demo,
    "process": cmd_process,
    "tasks": cmd_tasks,
    "eval": cmd_eval,
    "import-sample": lambda s, l: print(f"Loaded {import_sample(s)} sample emails") or 0,
}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](Store(config.DB_PATH), OllamaLLM())


if __name__ == "__main__":
    raise SystemExit(main())
