import copy

from app.llm import LLMError
from app.pipeline import (ExtractionError, analyze_email, phrase_in_email,
                          process_all, quote_in_email)
from app.samples import evaluate, import_sample
from app.schemas import Profile
from fake_model import SCRIPT, FakeLLM, task


def by_title(store, fragment):
    return [c for c in store.list_commitments() if fragment.lower() in c["title"].lower()]


def test_full_sample_inbox_matches_ground_truth(store, llm):
    assert import_sample(store) == 18
    result = process_all(store, llm)
    assert result == {"total": 18, "processed": 18, "errors": []}

    report = evaluate(store)
    assert report["expected"] == 12
    assert report["found"] == 12
    assert report["dates_correct"] == 12
    assert report["flags_correct"] == 12
    assert report["false_positives"] == 0


def test_correction_email_updates_the_same_task(store, llm):
    import_sample(store)
    process_all(store, llm)
    items = by_title(store, "probability assignment 3")
    assert len(items) == 1, "correction must update, not duplicate"
    c = store.get_commitment(items[0]["id"])
    assert c["due_at"] == "2026-10-22T23:59"
    assert c["previous_due_at"] == "2026-10-23T23:59"
    assert "deadline_changed" in c["flags"]
    assert c["source_email_id"] == "e02" and c["first_email_id"] == "e01"
    assert [e["event"] for e in c["events"]] == ["created", "deadline_changed"]


def test_rescheduled_meeting_updates_the_same_meeting(store, llm):
    import_sample(store)
    process_all(store, llm)
    items = by_title(store, "project review")
    assert len(items) == 1
    assert items[0]["due_at"] == "2026-10-22T11:00"
    assert items[0]["previous_due_at"] == "2026-10-21T16:00"


def test_newsletter_and_promo_emails_create_nothing(store, llm):
    import_sample(store)
    process_all(store, llm)
    assert by_title(store, "diwali") == []
    for eid in ("e04", "e08", "e13", "e14"):
        assert store.get_email(eid)["status"] == "processed"
    sources = {c["source_email_id"] for c in store.list_commitments()}
    assert not sources & {"e04", "e08", "e13", "e14"}


def test_undated_email_is_kept_and_flagged(store, llm):
    import_sample(store)
    process_all(store, llm)
    c = by_title(store, "scholarship")[0]
    assert c["due_at"] is None and "no_date" in c["flags"]


def test_processing_is_idempotent(store, llm):
    import_sample(store)
    process_all(store, llm)
    calls = llm.calls
    again = process_all(store, llm)
    assert again["total"] == 0 and llm.calls == calls
    assert len(store.list_commitments()) == 12


def test_invented_task_is_skipped_with_a_reason(store):
    script = copy.deepcopy(SCRIPT)
    script["Lab 5 viva slots"]["tasks"] = [
        task("Book a hotel for the viva", "Friday", "Please book a hotel room for the viva.", kind="task")]
    import_sample(store)
    process_all(store, FakeLLM(script))
    assert by_title(store, "hotel") == []
    assert ("e18", "Book a hotel for the viva", "title_not_in_email") in [
        (s["email_id"], s["title"], s["reason"]) for s in store.list_skipped()]


def test_models_own_quote_is_irrelevant_evidence_comes_from_the_email(store):
    """Day 1 silently ignored a correction because the model's quote failed verification."""
    script = copy.deepcopy(SCRIPT)
    script["Correction: Probability Assignment 3 deadline"]["tasks"][0]["source_quote"] = "Totally made up sentence here."
    import_sample(store)
    process_all(store, FakeLLM(script))
    c = by_title(store, "probability assignment 3")[0]
    assert c["due_at"] == "2026-10-22T23:59" and "deadline_changed" in c["flags"]
    assert "Thursday 22 October" in c["source_quote"]


def test_weakly_grounded_update_never_overwrites_a_tracked_task(store):
    """Date words present in the email but no action/deadline cue in that sentence -> flagged, not applied."""
    from app.commitments import apply_task
    import_sample(store)
    process_all(store, FakeLLM())
    email = store.get_email("e02")
    out = apply_task(store, email, title="Submit Probability Assignment 3", kind="task",
                     due_at="2026-10-30T23:59", all_day=True, date_phrase="30 October", date_confidence="high",
                     details="", source_quote="x", verified=False)
    assert out["action"] == "ignored_unverified"
    c = store.get_commitment(by_title(store, "probability assignment 3")[0]["id"])
    assert c["due_at"] == "2026-10-22T23:59"
    assert c["events"][-1]["event"] == "ignored_unverified"


def test_made_up_date_words_lower_confidence(store):
    script = copy.deepcopy(SCRIPT)
    script["Book return reminder"]["tasks"][0]["when"] = "31 December"   # not in the email
    import_sample(store)
    process_all(store, FakeLLM(script))
    c = by_title(store, "library")[0]
    assert c["date_confidence"] == "low" and "uncertain_date" in c["flags"]


def test_old_email_cannot_undo_a_newer_one(store, llm):
    """Import out of order: the correction is processed first, the original second."""
    import_sample(store)
    process_all(store, llm)
    before = by_title(store, "probability assignment 3")[0]["due_at"]
    # replay the *original* email as if it arrived late
    original = store.get_email("e01")
    from app.pipeline import process_email
    process_email(store, llm, original, Profile())
    after = store.get_commitment(by_title(store, "probability assignment 3")[0]["id"])
    assert after["due_at"] == before == "2026-10-22T23:59"
    assert any(e["event"] == "stale_ignored" for e in after["events"])


def test_malformed_model_output_is_retried_once():
    class Flaky:
        calls = 0

        def analyze(self, system, user, schema):
            self.calls += 1
            if self.calls == 1:
                return {"category": "not-a-real-category", "tasks": "oops"}
            return {"category": "announcement", "summary": "ok", "tasks": []}

    email = {"sent_at": "2026-10-19T09:00:00", "sender": "x", "subject": "s", "body": "b"}
    flaky = Flaky()
    assert analyze_email(flaky, email, Profile()).category == "announcement"
    assert flaky.calls == 2


def test_llm_failure_marks_email_as_error_and_continues(store):
    class Broken:
        def analyze(self, system, user, schema):
            raise LLMError("ollama is down")

    import_sample(store)
    out = process_all(store, Broken())
    # gives up after 3 failures in a row instead of grinding through the inbox
    assert out["processed"] == 0 and len(out["errors"]) == 3
    assert store.get_email("e01")["status"] == "error"
    # everything is still waiting for the next run
    assert len(store.emails_to_process()) == 18


def test_quote_and_phrase_checks():
    text = "Hello. The assignment is due Friday 23 October, 11:59 PM. Bye."
    assert quote_in_email("The assignment is due Friday 23 October, 11:59 PM.", text)
    assert quote_in_email("the assignment is due friday 23 october 11:59 pm.", text)   # tiny differences ok
    assert not quote_in_email("The exam is on Monday.", text)
    assert not quote_in_email("", text)
    assert phrase_in_email("Friday 23 October, 11:59 PM", text)
    assert not phrase_in_email("Tuesday 3 November", text)
