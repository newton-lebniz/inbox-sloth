from datetime import datetime

from app.priority import build_plan, default_as_of, due_label, find_conflicts, score_item
from app.schemas import Profile

NOW = datetime(2026, 10, 21, 9, 0)   # Wednesday


def C(i, title, kind="task", due="2026-10-23T23:59", all_day=False, flags=None, status="pending", prev=None):
    return {"id": i, "title": title, "kind": kind, "due_at": due, "all_day": all_day, "flags": flags or [],
            "status": status, "previous_due_at": prev, "details": "", "origin": "model"}


def plan(cs, **profile):
    return build_plan(cs, Profile(**profile), NOW)


def test_today_outranks_tomorrow_whatever_the_boosts():
    cs = [C(1, "Submit report", due="2026-10-22T10:00", flags=["deadline_changed"], prev="2026-10-23T10:00"),
          C(2, "Send slides", due="2026-10-21T18:00")]
    assert [i["id"] for i in plan(cs, role="student")["focus"]] == [2, 1]


def test_overdue_comes_first_and_is_labelled():
    p = plan([C(1, "Old thing", due="2026-10-20T10:00"), C(2, "Today thing", due="2026-10-21T17:00")])
    assert p["overdue"][0]["id"] == 1 and p["overdue"][0]["due_label"].startswith("Overdue")
    assert [i["id"] for i in p["focus"]][0] == 1 and p["counts"]["overdue"] == 1


def test_done_and_dismissed_are_not_planned():
    p = plan([C(1, "A", status="done"), C(2, "B", status="dismissed"), C(3, "C")])
    assert [i["id"] for i in p["focus"] + p["can_wait"] + p["later"]] == [3] or p["counts"]["pending"] == 1


def test_profile_changes_the_ranking_and_explains_why():
    cs = [C(1, "Workshop planning meeting", "meeting", "2026-10-24T10:00"),
          C(2, "Reply: Lab 5 viva slots", "reply", "2026-10-24T10:00")]
    student = {i["id"]: i for i in plan(cs, role="student", priorities=["meetings"])["week"][3]["items"]}
    free = {i["id"]: i for i in plan(cs, role="freelancer", priorities=["replies", "invoices"])["week"][3]["items"]}
    assert student[1]["score"] > student[2]["score"]
    assert free[2]["score"] > free[1]["score"]
    assert "you said replies matter" in free[2]["reasons"]


def test_reminder_style_widens_what_needs_attention():
    cs = [C(1, "Report", due="2026-10-24T12:00")]               # 3 days away
    assert plan(cs, reminder_style="early")["focus"][0]["id"] == 1
    assert plan(cs, reminder_style="last_minute")["focus"] == []


def test_undated_is_surfaced_not_hidden():
    p = plan([C(1, "Scholarship form", due=None, flags=["no_date"])])
    assert p["undated"][0]["due_label"] == "No date" and "check it" in p["undated"][0]["reasons"][0]


def test_changed_date_is_listed_with_old_and_new():
    p = plan([C(1, "Project review meeting", "meeting", "2026-10-22T11:00", flags=["deadline_changed"],
                prev="2026-10-21T16:00")])
    assert "moved from Wed 21 Oct 4:00 PM to Thu 22 Oct 11:00 AM" in p["changes"][0]["message"]


def test_overlapping_events_clash():
    items = [score_item(c, Profile(), NOW) for c in [
        C(1, "Project review", "meeting", "2026-10-22T11:00"),
        C(2, "Guest lecture", "meeting", "2026-10-22T11:30"),
        C(3, "Lab", "meeting", "2026-10-22T13:00")]]
    clashes = [c for c in find_conflicts(items) if c["type"] == "clash"]
    assert len(clashes) == 1 and clashes[0]["ids"] == [1, 2]


def test_back_to_back_is_not_a_clash():
    items = [score_item(c, Profile(), NOW) for c in [
        C(1, "A", "meeting", "2026-10-22T11:00"), C(2, "B", "meeting", "2026-10-22T12:00")]]
    assert find_conflicts(items) == []


def test_heavy_day_and_exam_day():
    heavy = [score_item(C(i, f"T{i}", due="2026-10-22T20:00"), Profile(), NOW) for i in (1, 2, 3)]
    assert find_conflicts(heavy)[0]["type"] == "heavy_day"
    exam = [score_item(C(1, "DS exam", "exam", "2026-10-22T10:00"), Profile(), NOW),
            score_item(C(2, "Report", due="2026-10-22T23:59", all_day=True), Profile(), NOW)]
    found = find_conflicts(exam)
    assert found[0]["type"] == "exam_day" and found[0]["severity"] == "high"


def test_labels():
    assert due_label(C(1, "x", due="2026-10-21T17:00"), NOW) == "Today 5:00 PM"
    assert due_label(C(1, "x", due="2026-10-22T11:00"), NOW) == "Tomorrow 11:00 AM"
    assert due_label(C(1, "x", due="2026-10-25T23:59", all_day=True), NOW) == "Sun 25 Oct"
    assert due_label(C(1, "x", due="2026-10-21T08:00"), NOW) == "Overdue by 1 h"


def test_static_mailbox_is_planned_as_of_its_newest_email():
    d = default_as_of("2026-10-21T08:50:00", datetime(2026, 10, 24, 14, 0))
    assert d["as_of"] == datetime(2026, 10, 21, 8, 50) and "newest email" in d["reason"]
    d = default_as_of("2026-10-24T09:00:00", datetime(2026, 10, 24, 14, 0))
    assert d["reason"] == "now" and d["as_of"].hour == 14
    assert default_as_of(None, datetime(2026, 10, 24, 14, 0))["reason"] == "now"
