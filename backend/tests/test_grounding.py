from datetime import datetime

import pytest

from app.grounding import (fallback_candidates, ground_task, infer_kind, looks_bulk, refine_title)
from app.schemas import ExtractedTask

SENT = datetime(2026, 10, 20, 10, 0)


def T(title, when="", kind="task"):
    return ExtractedTask(title=title, when=when, kind=kind)


MESS = "Hi all,\n\nDue to supply issues the Thursday dinner menu changes to khichdi and papad. Sunday breakfast stays the same.\n\nMess Committee"
LAB4 = ("I have updated the instruction sheet for Lab 5. Question 3 now asks you to plot the results with "
        "matplotlib instead of Excel. The revised PDF is on the portal. No change to the submission process.")


def test_menu_and_instruction_changes_are_informational():
    # 'Due to ...' is not a deadline; 'submission' is not an action
    assert ground_task("Mess menu change", MESS, T("Khichdi dinner", "Thursday"), SENT).reason == "informational"
    g = ground_task("Updated lab instructions", LAB4, T("Plot results with matplotlib", "Tuesday 20 October 2026"), SENT)
    assert not g.ok and g.reason == "informational"


def test_reformatted_dates_are_still_supported():
    body = "Data Structures exam: 9 November, 10:00 AM, Room LH-2."
    g = ground_task("Mid-semester examination timetable", body, T("Data structures exam", "November 9th, 10:00 AM"), SENT)
    assert g.ok and g.strong and not g.healed and g.date_text == "November 9th, 10:00 AM"


def test_invented_date_is_replaced_by_the_emails_own():
    body = "Please return it by 25 October to avoid a fine of Rs. 5 per day."
    g = ground_task("Book return reminder", body, T("Return book", "31 December"), SENT)
    assert g.ok and g.healed and "25 October" in g.date_text


def test_invented_date_with_no_date_in_email_is_dropped_not_kept():
    body = "Please submit the scholarship form to the welfare office."
    g = ground_task("Scholarship form", body, T("Submit scholarship form", "Monday 2 November"), SENT)
    assert g.ok and g.date_text == ""          # task kept, date discarded


def test_title_needs_most_of_its_words_in_the_email():
    assert not ground_task("Lab 5 viva slots", "Please reply with your viva slot by Friday.",
                           T("Book a hotel for the viva", "Friday"), SENT).ok
    assert ground_task("Lab 5 viva slots", "Please reply with your viva slot by Friday.",
                       T("Reply with viva slot", "Friday"), SENT).ok


def test_title_must_come_from_the_email():
    g = ground_task("Lab 5 viva slots", "Please reply with your slot by Friday.", T("Book a hotel", "Friday"), SENT)
    assert g.reason == "title_not_in_email"


def test_date_without_a_cue_in_its_sentence_is_weak():
    body = "Please read the notes carefully. The papers will be handed out on Monday."
    g = ground_task("Notes", body, T("Read the notes", "Monday"), SENT)
    assert g.ok and not g.strong


@pytest.mark.parametrize("model_kind,title,subject,evidence,want", [
    ("task", "Submit data structures exam", "Mid-semester examination timetable", "Data Structures exam: 9 November", "exam"),
    ("meeting", "Attend class", "Quiz in Python lab", "There will be a short quiz", "exam"),
    ("reply", "Respond to email", "Lab 5 viva slots", "Please reply to this email", "reply"),
    ("task", "Review meeting", "Project review meeting", "meeting is rescheduled", "meeting"),
    ("task", "Pay semester fee", "Fee payment - odd semester", "The last date for payment is 30 October", "task"),
    ("task", "Upload report", "Lab 5 report", "report is due this Thursday", "task"),
])
def test_infer_kind(model_kind, title, subject, evidence, want):
    assert infer_kind(model_kind, title, subject, evidence) == want


@pytest.mark.parametrize("title,kind,subject,want", [
    ("Finalise speaker list", "meeting", "Workshop planning meeting", "Workshop planning meeting"),
    ("Fill the form", "task", "Summer internship applications open", "Fill the form — Summer internship applications"),
    ("Respond to email", "reply", "Lab 5 viva slots", "Reply: Lab 5 viva slots"),
    ("Review meeting", "meeting", "Re: Project review meeting - rescheduled", "Project review meeting"),
    ("Upload report", "task", "Lab 5 report due Thursday", "Upload report"),
    ("Attend class", "exam", "Quiz in Python lab", "Quiz in Python lab"),
    ("Submit data structures exam", "exam", "Mid-semester examination timetable", "Data structures exam"),
    ("Reply with Lab 5 viva slot", "reply", "Lab 5 viva slots", "Reply with Lab 5 viva slot"),
])
def test_refine_title(title, kind, subject, want):
    assert refine_title(title, kind, subject) == want


def test_fallback_picks_the_sentence_that_states_the_new_deadline():
    body = ("A correction to my earlier email: because of the department holiday on Friday, the deadline for "
            "Assignment 3 has moved earlier. Please submit Probability Assignment 3 by Thursday 22 October, 11:59 PM instead.")
    (c,) = fallback_candidates("Correction: Probability Assignment 3 deadline", body, datetime(2026, 10, 20, 14, 30), "x")
    assert c.title == "Probability Assignment 3" and "Thursday 22 October" in c.when


def test_fallback_undated_needs_an_explicit_request():
    body = "Hello,\n\nPlease submit the scholarship verification form to the welfare office soon."
    (c,) = fallback_candidates("Scholarship verification form", body, SENT, "deadline_notice")
    assert c.when == "" and "Please submit" in c.source_quote
    assert fallback_candidates("Update", "The canteen has a new menu.", SENT, "other") == []


def test_fallback_never_fires_on_bulk_mail_or_cueless_dates():
    assert fallback_candidates("Digest", "Register by 30 October. Unsubscribe here.", SENT, "x") == []
    assert fallback_candidates("Menu", MESS, datetime(2026, 10, 21, 7, 30), "assignment") == []


def test_bulk_markers():
    assert looks_bulk("50% off Premium", "Use code SLOTH50 at checkout.")
    assert looks_bulk("Campus Weekly", "...Unsubscribe at the bottom of this email.")
    assert not looks_bulk("Lab 5", "Please submit by Friday.")


@pytest.mark.parametrize("subject,body", [
    ("Thanks for coming", "Thanks for attending the workshop on Monday. Slides are on the portal."),
    ("Session notes", "Notes from last Tuesday's session are attached. Please review them when free."),
    ("Workshop cancelled", "The workshop has been cancelled. We will announce a new date soon."),
    ("Free pizza night", "Free pizza at the club room on Friday at 5 PM! Come join us."),
])
def test_past_events_and_social_invites_make_no_task(subject, body):
    assert fallback_candidates(subject, body, datetime(2026, 10, 22, 9, 0), "other") == []
    g = ground_task(subject, body, T(subject, "Monday"), datetime(2026, 10, 22, 9, 0))
    assert not g.ok or not g.strong


def test_subject_alone_is_not_evidence_unless_it_states_a_date():
    sent = datetime(2026, 10, 22, 9, 0)
    assert not ground_task("Session notes", "Notes attached.", T("Session notes"), sent).ok
    g = ground_task("Team meeting tomorrow 3 PM", "See you there.", T("Team meeting", "tomorrow 3 PM"), sent)
    assert g.ok and g.strong


def test_cancellation_is_not_a_commitment_but_a_reschedule_is():
    sent = datetime(2026, 10, 22, 9, 0)
    assert fallback_candidates("Workshop", "The workshop has been cancelled.", sent, "x") == []
    (c,) = fallback_candidates("Workshop", "The workshop is cancelled on Friday but will be rescheduled to Monday at 3 PM.", sent, "x")
    assert "Monday" in c.when
