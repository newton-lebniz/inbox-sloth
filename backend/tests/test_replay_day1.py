"""Replay of the REAL Day 1 gemma3:1b outputs through the current pipeline.

Day 1 scored (fixed evaluator): 6/12 found, 5/12 dates right, 6 false positives.
Same model answers in, better pipeline: each test below pins one observed failure.
Caveat: the rules were written after seeing these 18 emails, so this is a
development-set result, not a generalisation claim (see test_rules_generalise.py)."""
import json
from pathlib import Path

import pytest

from app.pipeline import process_all
from app.samples import evaluate, import_sample

FIXTURE = Path(__file__).parent / "fixtures" / "gemma_day1_outputs.json"


class ReplayLLM:
    model = "gemma3:1b-replay"

    def __init__(self):
        self.data = {k: v for k, v in json.loads(FIXTURE.read_text(encoding="utf-8")).items() if k != "_note"}

    def analyze(self, system, user, schema):
        import re
        subject = re.search(r"^Subject: (.*)$", user, re.M).group(1)
        d = self.data[subject]
        return {"category": d["category"], "summary": d["summary"], "tasks": d["tasks"]}


@pytest.fixture
def run(store):
    import_sample(store)
    process_all(store, ReplayLLM())
    return store


def one(store, fragment):
    items = [c for c in store.list_commitments() if fragment.lower() in c["title"].lower()]
    assert len(items) == 1, [c["title"] for c in store.list_commitments()]
    return store.get_commitment(items[0]["id"])


def test_scores_beat_day1_baseline(run):
    r = evaluate(run)
    assert r["found"] == 12 and r["dates_correct"] == 12 and r["kinds_correct"] == 12
    assert r["flags_correct"] == 12 and r["false_positives"] == 0, r["extras"]
    assert r["unexpected_flags"] == []


# 1. correction did not update the original deadline
def test_probability_correction_updates_original(run):
    c = one(run, "probability assignment 3")
    assert c["due_at"] == "2026-10-22T23:59" and c["previous_due_at"] == "2026-10-23T23:59"
    assert "deadline_changed" in c["flags"] and c["source_email_id"] == "e02"
    assert c["origin"] == "model"    # created by the model from e01; e02 was recovered by the rules


# 2 + 3. informational emails must not create tasks
def test_informational_emails_are_skipped_not_tracked(run):
    assert not [c for c in run.list_commitments() if "matplotlib" in c["title"].lower()]
    assert not [c for c in run.list_commitments() if "khichdi" in c["title"].lower()]
    reasons = {s["email_id"]: s["reason"] for s in run.list_skipped()}
    assert reasons["e04"] == "informational" and reasons["e13"] == "informational"


# 4. python quiz was 'Attend class' / meeting
def test_python_quiz_is_an_exam_with_the_right_name(run):
    c = one(run, "quiz")
    assert c["kind"] == "exam" and c["title"] == "Quiz in Python lab"
    assert c["due_at"] == "2026-10-26T09:00"


# 5. exam was a 'task' and flagged uncertain despite an explicit date
def test_data_structures_exam_kind_and_confident_date(run):
    c = one(run, "data structures")
    assert c["kind"] == "exam" and c["title"] == "Data structures exam"
    assert c["due_at"] == "2026-11-09T10:00" and c["date_confidence"] == "high"
    assert "uncertain_date" not in c["flags"]


# 6. internship title
def test_internship_title_names_the_programme(run):
    c = one(run, "internship")
    assert "summer internship" in c["title"].lower() and c["due_at"] == "2026-11-02T23:59"


# 7. undated scholarship request kept as undated, not given a borrowed date
def test_scholarship_form_is_undated_and_flagged(run):
    c = one(run, "scholarship")
    assert c["due_at"] is None and "no_date" in c["flags"] and c["origin"] == "rules"


# 8. viva reply had the generic title 'Respond to email'
def test_viva_reply_title(run):
    c = one(run, "viva")
    assert c["kind"] == "reply" and c["title"] == "Reply: Lab 5 viva slots" and c["due_at"] == "2026-10-23T23:59"


# 9. source quotes failed verification
def test_every_commitment_has_a_real_evidence_sentence(run):
    for c in run.list_commitments():
        email = run.get_email(c["source_email_id"])
        assert c["source_quote"] and c["source_quote"] in email["body"] + email["subject"], c["title"]
        assert "unverified" not in c["flags"], c["title"]


# 10. workshop meeting got the title of an action inside it
def test_workshop_meeting_title(run):
    c = one(run, "workshop")
    assert c["kind"] == "meeting" and c["title"] == "Workshop planning meeting"


def test_rescheduled_meeting_is_one_commitment_with_history(run):
    c = one(run, "project review")
    assert c["due_at"] == "2026-10-22T11:00" and c["previous_due_at"] == "2026-10-21T16:00"
    assert "deadline_changed" in c["flags"]


def test_fee_payment_recovered_by_rules(run):
    c = one(run, "fee")
    assert c["due_at"] == "2026-10-30T23:59" and c["origin"] == "rules"


def test_model_cache_makes_second_run_free(store):
    import_sample(store)
    llm = ReplayLLM()
    calls = []
    inner = llm.analyze
    llm.analyze = lambda *a: calls.append(1) or inner(*a)
    process_all(store, llm)
    first = len(calls)
    store.reset_results()
    process_all(store, llm)
    assert first == 18 and len(calls) == 18, "second run must be served from the cache"
    assert len(store.list_commitments()) == 12
