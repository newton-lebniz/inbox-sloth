"""Priority scoring, the daily/weekly plan, and conflict detection.

Pure functions over stored commitments, no model involved: the same inputs always give the same
plan, and every score comes with the reasons that produced it, so the user can see *why* the sloth
put something first and disagree with it.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .schemas import Profile

DURATION_MIN = {"meeting": 60, "exam": 120, "reply": 0, "task": 0}
HIGH, MEDIUM = 85, 55
# Urgency first: something due today always outranks something due tomorrow, whatever the boosts.
BUCKET_ORDER = {"overdue": 0, "today": 1, "tomorrow": 2, "week": 3, "later": 4, "undated": 5}


def _fmt_time(d: datetime) -> str:
    return d.strftime("%I:%M %p").lstrip("0")


def _fmt_day(d: date) -> str:
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def due_label(c: Dict[str, Any], as_of: datetime) -> str:
    if not c["due_at"]:
        return "No date"
    due = datetime.fromisoformat(c["due_at"])
    when = "" if c["all_day"] else f" {_fmt_time(due)}"
    if due < as_of:
        hours = (as_of - due).total_seconds() / 3600
        return f"Overdue by {int(hours // 24)} day(s)" if hours >= 24 else f"Overdue by {max(1, int(hours))} h"
    days = (due.date() - as_of.date()).days
    if days == 0:
        return "Today" + (" (end of day)" if c["all_day"] else when)
    if days == 1:
        return "Tomorrow" + when
    return _fmt_day(due.date()) + when


def _profile_boosts(c: Dict[str, Any], profile: Profile) -> List[tuple]:
    """(points, reason) from what the user said matters and from their role."""
    text = f"{c['title']} {c.get('details', '')}".lower()
    kind, prio, out = c["kind"], set(profile.priorities), []

    def add(points: int, why: str) -> None:
        out.append((points, why))

    if "deadlines" in prio and kind == "task":
        add(10, "you said deadlines matter")
    if "exams" in prio and kind == "exam":
        add(20, "you said exams matter")
    if "meetings" in prio and kind == "meeting":
        add(10, "you said meetings matter")
    if "replies" in prio and kind == "reply":
        add(10, "you said replies matter")
    if "club activities" in prio and re.search(r"club|workshop|ehacs|society|fest", text):
        add(10, "you said club activities matter")
    if "internships" in prio and re.search(r"internship|placement|interview|resume", text):
        add(15, "you said internships matter")
    if "invoices" in prio and re.search(r"invoice|fee|payment|bill|receipt", text):
        add(15, "you said invoices matter")

    if profile.role == "student" and (kind == "exam" or re.search(r"assignment|lab|report|quiz", text)):
        add(5, "coursework counts for a student")
    elif profile.role == "professional" and kind in ("meeting", "reply"):
        add(5, "meetings and replies drive a working day")
    elif profile.role == "freelancer" and (kind == "reply" or re.search(r"invoice|payment|client|proposal", text)):
        add(10, "clients and invoices drive a freelancer's week")
    return out


def score_item(c: Dict[str, Any], profile: Profile, as_of: datetime) -> Dict[str, Any]:
    soon_days = 3 if profile.reminder_style == "early" else 1
    reasons: List[str] = []
    due = datetime.fromisoformat(c["due_at"]) if c["due_at"] else None

    if due is None:
        bucket, score = "undated", 35
        reasons.append("no date in the email: check it")
    elif due < as_of:
        bucket, score = "overdue", 100
        reasons.append("overdue")
    else:
        days = (due.date() - as_of.date()).days
        if days == 0:
            bucket, score = "today", 90
            reasons.append("due today")
        elif days == 1:
            bucket, score = "tomorrow", 75
            reasons.append("due tomorrow")
        elif days <= 7:
            bucket, score = "week", 60 - 3 * days
            reasons.append(f"due in {days} days")
        else:
            bucket, score = "later", max(5, 25 - days)
            reasons.append(f"due in {days} days")
        if profile.reminder_style == "early" and 0 < days <= soon_days:
            score += 10
            reasons.append("you prefer early reminders")

    for points, why in _profile_boosts(c, profile):
        score += points
        reasons.append(why)

    flags = c["flags"]
    if "deadline_changed" in flags:
        score += 10
        reasons.append("the date changed: double-check it")
    if "uncertain_date" in flags or "unverified" in flags:
        reasons.append("the sloth is not sure about this one")

    score = int(min(score, 150))
    level = "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"
    days_left = (due.date() - as_of.date()).days if due else None
    attention = bucket in ("overdue", "today") or (
        bucket in ("tomorrow", "week") and days_left is not None and days_left <= soon_days)
    return {
        "id": c["id"], "title": c["title"], "kind": c["kind"], "due_at": c["due_at"], "all_day": c["all_day"],
        "status": c["status"], "flags": flags, "origin": c.get("origin", "model"),
        "score": score, "level": level, "bucket": bucket, "attention": attention,
        "due_label": due_label(c, as_of), "reasons": reasons,
    }


def find_conflicts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clashes and overloaded days among pending, dated commitments."""
    dated = [i for i in items if i["due_at"] and i["bucket"] != "overdue"]
    out: List[Dict[str, Any]] = []

    timed = [i for i in dated if not i["all_day"] and DURATION_MIN.get(i["kind"], 0) > 0]
    timed.sort(key=lambda i: i["due_at"])
    for a_idx, a in enumerate(timed):
        a_start = datetime.fromisoformat(a["due_at"])
        a_end = a_start + timedelta(minutes=DURATION_MIN[a["kind"]])
        for b in timed[a_idx + 1:]:
            b_start = datetime.fromisoformat(b["due_at"])
            if b_start >= a_end:
                break
            out.append({
                "type": "clash", "severity": "high", "ids": [a["id"], b["id"]],
                "message": f"“{a['title']}” and “{b['title']}” overlap on "
                           f"{_fmt_day(a_start.date())} around {_fmt_time(b_start)}.",
            })

    by_day: Dict[date, List[Dict[str, Any]]] = {}
    for i in dated:
        by_day.setdefault(datetime.fromisoformat(i["due_at"]).date(), []).append(i)
    for day, group in sorted(by_day.items()):
        exams = [g for g in group if g["kind"] == "exam"]
        if exams and len(group) > 1:
            others = [g["title"] for g in group if g["kind"] != "exam"]
            out.append({"type": "exam_day", "severity": "high", "ids": [g["id"] for g in group],
                        "message": f"{_fmt_day(day)} has an exam (“{exams[0]['title']}”) and "
                                   f"{len(others)} other thing(s): {', '.join(others)}."})
        elif len(group) >= 3:
            out.append({"type": "heavy_day", "severity": "medium", "ids": [g["id"] for g in group],
                        "message": f"{len(group)} things land on {_fmt_day(day)}: "
                                   f"{', '.join(g['title'] for g in group)}."})
    order = {"high": 0, "medium": 1}
    out.sort(key=lambda c: order[c["severity"]])
    return out


def find_changes(commitments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Commitments whose date changed after an earlier email: the ones worth re-checking."""
    out = []
    for c in commitments:
        if c["status"] == "pending" and "deadline_changed" in c["flags"] and c.get("previous_due_at"):
            old, new = datetime.fromisoformat(c["previous_due_at"]), datetime.fromisoformat(c["due_at"])
            out.append({
                "id": c["id"], "title": c["title"],
                "message": f"“{c['title']}” moved from {_fmt_day(old.date())}"
                           f"{'' if c['all_day'] else ' ' + _fmt_time(old)} to {_fmt_day(new.date())}"
                           f"{'' if c['all_day'] else ' ' + _fmt_time(new)}.",
            })
    return out


def build_plan(commitments: List[Dict[str, Any]], profile: Profile, as_of: datetime) -> Dict[str, Any]:
    pending = [c for c in commitments if c["status"] == "pending"]
    items = [score_item(c, profile, as_of) for c in pending]
    key = lambda i: (BUCKET_ORDER[i["bucket"]], -i["score"], i["due_at"] or "9999")  # noqa: E731

    focus = sorted([i for i in items if i["attention"]], key=key)
    week_days: List[Dict[str, Any]] = []
    for offset in range(7):
        day = as_of.date() + timedelta(days=offset)
        todays = sorted(
            [i for i in items if i["due_at"] and datetime.fromisoformat(i["due_at"]).date() == day
             and i["bucket"] != "overdue"],
            key=lambda i: i["due_at"])
        week_days.append({"date": day.isoformat(), "label": _fmt_day(day) if offset else "Today", "items": todays})

    return {
        "as_of": as_of.isoformat(timespec="minutes"),
        "focus": focus,
        "overdue": sorted([i for i in items if i["bucket"] == "overdue"], key=key),
        "week": week_days,
        "later": sorted([i for i in items if i["bucket"] == "later"], key=lambda i: i["due_at"]),
        "undated": sorted([i for i in items if i["bucket"] == "undated"], key=key),
        "can_wait": sorted([i for i in items if i["level"] == "low" and i["bucket"] in ("week", "later")], key=key),
        "conflicts": find_conflicts(items),
        "changes": find_changes(commitments),
        "counts": {"pending": len(items), "attention": len(focus),
                   "overdue": sum(1 for i in items if i["bucket"] == "overdue")},
    }


def default_as_of(newest_email_sent_at: Optional[str], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Real 'now', unless the mailbox is a static snapshot (newest email > 36 h old): then plan
    as of that email, so imported or sample inboxes are not shown as all overdue."""
    now = now or datetime.now()
    if newest_email_sent_at:
        newest = datetime.fromisoformat(newest_email_sent_at)
        if now - newest > timedelta(hours=36):
            return {"as_of": newest, "reason": f"your newest email is from {_fmt_day(newest.date())}, "
                                               "so the plan is shown as of then"}
    return {"as_of": now.replace(second=0, microsecond=0), "reason": "now"}
