"""Deterministic date resolution.

Small local models are bad at calendar arithmetic ("Thursday" sent on a
Monday is which date?). So the model only copies the date words from the
email, and this module turns them into a real datetime relative to the
date the email was sent. No LLM involved, fully unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thurs": 3, "thu": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_WD_RE = "|".join(sorted(WEEKDAYS, key=len, reverse=True))

END_OF_DAY = time(23, 59)
EOD_TIME = time(17, 0)


@dataclass
class Resolved:
    due: Optional[datetime]
    all_day: bool
    confidence: str  # high | medium | low | none
    note: str = ""


def _extract_time(t: str) -> Tuple[Optional[time], str, str]:
    """Pull a time of day out of the text. Returns (time, confidence, text_without_time)."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        pm = m.group(3).startswith("p")
        if 1 <= hour <= 12 and minute < 60:
            if hour == 12:
                hour = 12 if pm else 0
            elif pm:
                hour += 12
            return time(hour, minute), "high", t[: m.start()] + " " + t[m.end():]
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t)
    if m:
        return time(int(m.group(1)), int(m.group(2))), "high", t[: m.start()] + " " + t[m.end():]
    m = re.search(r"\bnoon\b", t)
    if m:
        return time(12, 0), "high", t[: m.start()] + " " + t[m.end():]
    m = re.search(r"\bmidnight\b", t)
    if m:
        return END_OF_DAY, "medium", t[: m.start()] + " " + t[m.end():]
    m = re.search(r"\b(eod|cob|end of (the )?day|close of business)\b", t)
    if m:
        return EOD_TIME, "medium", t[: m.start()] + " " + t[m.end():]
    return None, "high", t


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _with_year(sent: date, month: int, day: int, year: Optional[int]) -> Optional[date]:
    """No year given: use the sent year, or next year if that would be long past."""
    if year is not None:
        return _safe_date(year, month, day)
    d = _safe_date(sent.year, month, day)
    if d is None:
        return None
    if d < sent - timedelta(days=7):
        return _safe_date(sent.year + 1, month, day)
    return d


def _extract_date(t: str, sent: date) -> Tuple[Optional[date], str, str]:
    """Return (date, confidence, note)."""
    # ISO: 2026-10-23
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d, "high", ""

    # 23 October [2026], 23rd of October
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b\.?,?\s*(\d{{4}})?", t)
    if m:
        d = _with_year(sent, MONTHS[m.group(2)], int(m.group(1)), int(m.group(3)) if m.group(3) else None)
        if d:
            return d, "high", ""

    # October 23[rd] [, 2026]
    m = re.search(rf"\b({_MONTH_RE})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(\d{{4}}))?", t)
    if m:
        d = _with_year(sent, MONTHS[m.group(1)], int(m.group(2)), int(m.group(3)) if m.group(3) else None)
        if d:
            return d, "high", ""

    # 23/10[/2026]  (day first, the Indian convention)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        day, month = (a, b) if b <= 12 else (b, a)
        year = int(m.group(3)) if m.group(3) else None
        if year is not None and year < 100:
            year += 2000
        d = _with_year(sent, month, day, year)
        if d:
            return d, "medium", "numeric date read as day/month"

    # relative words
    if re.search(r"\bday after tomorrow\b", t):
        return sent + timedelta(days=2), "high", ""
    if re.search(r"\btomorrow\b", t):
        return sent + timedelta(days=1), "high", ""
    if re.search(r"\b(today|tonight|this evening)\b", t):
        return sent, "high", ""
    m = re.search(r"\bin (\d{1,2}) (day|days|week|weeks)\b", t)
    if m:
        n = int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)
        return sent + timedelta(days=n), "medium", ""

    # weekday names, with optional this/next
    m = re.search(rf"\b(?:(next|this|coming|upcoming)\s+)?({_WD_RE})\b", t)
    if m:
        modifier, wd = m.group(1), WEEKDAYS[m.group(2)]
        if modifier == "next":
            start_next_week = sent - timedelta(days=sent.weekday()) + timedelta(days=7)
            return start_next_week + timedelta(days=wd), "medium", "'next <weekday>' read as next calendar week"
        ahead = (wd - sent.weekday()) % 7
        if ahead == 0:
            return sent, "medium", "same weekday as the email, assumed today"
        return sent + timedelta(days=ahead), "high", ""

    return None, "none", "no date found"


def resolve(phrase: str, sent_at: datetime) -> Resolved:
    """Turn words like 'Thursday 5 PM' into a datetime, relative to when the email was sent."""
    text = " ".join((phrase or "").lower().replace(",", " ").split())
    if not text:
        return Resolved(None, False, "none", "no date given")

    tod, time_conf, rest = _extract_time(text)
    d, date_conf, note = _extract_date(rest, sent_at.date())

    if d is None:
        if tod is not None:
            # a time with no day, e.g. "by 4 PM": assume the day the email was sent
            return Resolved(datetime.combine(sent_at.date(), tod), False, "low",
                            "time only, assumed the day the email was sent")
        return Resolved(None, False, "none", note)

    confidence = date_conf
    if tod is None:
        due, all_day = datetime.combine(d, END_OF_DAY), True
    else:
        due, all_day = datetime.combine(d, tod), False
        if time_conf == "medium" and confidence == "high":
            confidence = "medium"
            note = note or "time inferred (end of day)"

    if due.date() < sent_at.date():
        confidence, note = "low", "date is before the email was sent"
    return Resolved(due, all_day, confidence, note)
