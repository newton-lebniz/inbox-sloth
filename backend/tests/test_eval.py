"""The Day 1 evaluator accepted the best title match even when it was bad, so unrelated rows
were compared and wrong results looked right. These pin the fixed behaviour."""
from app.samples import evaluate


def add(store, title, kind, due, flags=None):
    store.add_emails([{"id": f"x{title}", "thread_id": "", "sender": "s", "subject": title, "body": "b",
                       "sent_at": "2026-10-19T09:00:00"}])
    cid = store.insert_commitment({"title": title, "kind": kind, "due_at": due, "email_id": f"x{title}",
                                   "sent_at": "2026-10-19T09:00:00", "flags": flags or []})
    return cid


def row(report, fragment):
    return next(r for r in report["rows"] if fragment in r["expected"].lower())


def test_same_date_alone_is_not_a_match(store):
    # both due Thursday 23:59, no shared word: must NOT be paired
    add(store, "Khichdi and papad dinner", "task", "2026-10-22T23:59")
    r = evaluate(store)
    assert not row(r, "probability assignment")["found"]
    assert r["false_positives"] == 1 and r["extras"] == ["Khichdi and papad dinner"]


def test_weak_title_match_is_rejected(store):
    add(store, "Plot results with matplotlib", "task", "2026-10-20T23:59")
    add(store, "Fill the form", "task", "2026-11-09T10:00")
    r = evaluate(store)
    assert r["found"] == 0 and r["false_positives"] == 2


def test_wrong_kind_still_matches_but_is_scored_separately(store):
    add(store, "Submit data structures exam", "task", "2026-11-09T10:00")
    r = evaluate(store)
    ds = row(r, "data structures")
    assert ds["found"] and ds["date_ok"] and not ds["kind_ok"]
    assert r["kinds_correct"] == 0 and r["dates_correct"] == 1


def test_right_task_wrong_date_is_found_but_not_correct(store):
    add(store, "Submit Probability Assignment 3", "task", "2026-10-23T23:59")
    r = evaluate(store)
    pa = row(r, "probability assignment")
    assert pa["found"] and not pa["date_ok"]


def test_one_actual_commitment_matches_only_one_expectation(store):
    add(store, "Lab 5 report", "task", "2026-10-22T17:00")
    r = evaluate(store)
    assert r["found"] == 1 and sum(1 for x in r["rows"] if x["found"]) == 1


def test_undated_expectation_needs_an_undated_actual(store):
    add(store, "Scholarship verification form", "task", "2026-10-30T23:59")
    assert not row(evaluate(store), "scholarship")["found"]
