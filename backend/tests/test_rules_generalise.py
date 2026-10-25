"""The rules were written after seeing the 18 sample emails. These 12 emails were written
afterwards with different wording, and the model is replaced by one that finds NOTHING, so only
the deterministic rules act. Expected: the rule layer should catch real commitments and
ignore informational mail, without being told about these emails."""
import pytest

from app.pipeline import process_email
from app.schemas import Profile

# (id, subject, body, sent_at, expected)  expected = None or (kind, due_at)
CASES = [
    ("g01", "Hackathon registration",
     "Registration for the college hackathon closes on 3 November at 6 PM. Teams of up to 4 can register on the portal.",
     "2026-10-22T09:00:00", ("task", "2026-11-03T18:00")),
    ("g02", "Guest lecture on cloud computing",
     "We are hosting a guest lecture on Friday at 3 PM in the seminar hall. Attendance is compulsory for all second-year students.",
     "2026-10-21T10:00:00", ("meeting", "2026-10-23T15:00")),
    ("g03", "Library closed on Sunday",
     "The central library will remain closed this Sunday due to maintenance. Regular hours resume on Monday.",
     "2026-10-22T09:00:00", None),
    ("g04", "Your order has been delivered",
     "Your order #4821 was delivered today at 2:15 PM. Thank you for shopping with us.",
     "2026-10-22T14:20:00", None),
    ("g05", "Project report submission",
     "Please upload the final project report to the portal before 28 October, 5 PM. Late uploads will not be accepted.",
     "2026-10-22T09:00:00", ("task", "2026-10-28T17:00")),
    ("g06", "Re: Team sync moved",
     "Quick update: tomorrow's sync is now at 11 AM instead of 10 AM.",
     "2026-10-22T16:00:00", ("meeting", "2026-10-23T11:00")),
    ("g07", "Weekly digest",
     "Top stories this week. Register by 30 October for the open mic night. Unsubscribe at any time.",
     "2026-10-22T07:00:00", None),
    ("g08", "Results declared",
     "The mid-semester results are available on the student portal.",
     "2026-10-22T11:00:00", None),
    ("g09", "Course feedback form",
     "Please fill the course feedback form when you get time.",
     "2026-10-22T11:30:00", ("task", None)),
    ("g10", "Interview schedule",
     "Your interview is scheduled for 2 November at 10:30 AM. Please carry a printed resume.",
     "2026-10-22T12:00:00", ("meeting", "2026-11-02T10:30")),
    ("g11", "Congratulations!",
     "Congratulations on winning the coding contest! Your certificate will be emailed next week.",
     "2026-10-22T12:30:00", None),
    ("g12", "Viva on Tuesday",
     "Your project viva is on Tuesday at 2 PM in Room 204. Please bring your report.",
     "2026-10-22T13:00:00", ("task", "2026-10-27T14:00")),
]


class FindsNothing:
    model = "nothing"

    def analyze(self, system, user, schema):
        return {"category": "other", "summary": "", "tasks": []}


@pytest.mark.parametrize("cid,subject,body,sent,expected", CASES, ids=[c[0] for c in CASES])
def test_rules_alone(store, cid, subject, body, sent, expected):
    email = {"id": cid, "thread_id": "", "sender": "x", "subject": subject, "body": body, "sent_at": sent}
    store.add_emails([email])
    process_email(store, FindsNothing(), store.get_email(cid), Profile())
    got = store.list_commitments()
    if expected is None:
        assert got == [], [(c["title"], c["due_at"]) for c in got]
    else:
        assert len(got) == 1, got
        assert (got[0]["kind"], got[0]["due_at"]) == expected
        assert got[0]["origin"] == "rules"
