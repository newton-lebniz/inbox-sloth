"""Small text helpers shared by matching, grounding and evaluation."""
from __future__ import annotations

import re
from typing import List, Set, Tuple

from .dates import MONTHS, WEEKDAYS

# Words that describe the email or the verb, not the thing being done.
STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "and", "your", "you", "please", "in", "on", "at", "by",
    "submit", "complete", "attend", "send", "reply", "respond", "finish", "do", "make",
    "moved", "rescheduled", "reschedule", "updated", "update", "correction", "corrected",
    "reminder", "revised", "new", "extended", "extension", "deadline", "due", "changed", "change",
}
# Nouns so generic that sharing one proves nothing.
WEAK_WORDS = {"form", "email", "mail", "message", "file", "document", "it", "this", "that",
              "thing", "stuff", "one", "work"}
# Words that carry no date information.
DATE_FILLER = {"the", "a", "an", "on", "at", "by", "of", "this", "next", "in", "to", "from", "till",
               "until", "before", "for", "coming", "upcoming", "around", "about", "and", "is", "be",
               "will", "it"}

_ORDINAL = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b")


def stem(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def words(text: str) -> List[str]:
    t = text.lower().replace("’", "'")
    t = _ORDINAL.sub(r"\1", t)                              # 9th -> 9
    t = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", t)  # 4pm -> 4 pm
    return re.findall(r"[a-z0-9]+(?::[0-9]{2})?", t)


def content_tokens(text: str, drop_weak: bool = True) -> Set[str]:
    out: Set[str] = set()
    for w in words(text):
        if w in STOPWORDS or (drop_weak and w in WEAK_WORDS):
            continue
        if len(w) > 1 or w.isdigit():
            out.add(stem(w))
    return out


def date_tokens(text: str) -> Set[str]:
    """Canonical date/time tokens: 'Oct'/'October' -> m10, 'Thu'/'Thursday' -> w3."""
    out: Set[str] = set()
    for w in words(text):
        if w in DATE_FILLER:
            continue
        if w in MONTHS:
            out.add(f"m{MONTHS[w]}")
        elif w in WEEKDAYS:
            out.add(f"w{WEEKDAYS[w]}")
        else:
            out.add(w)
    return out


def text_date_tokens(text: str) -> Set[str]:
    """Email-side tokens: '10:00' also counts as '10', so 'at 10 AM' is supported."""
    out = date_tokens(text)
    for t in list(out):
        if ":" in t:
            out.add(t.split(":")[0])
    return out


# -- sentences -----------------------------------------------------------------
_ABBR = re.compile(r"\b(Mr|Mrs|Ms|Dr|Prof|St|No|Rs|Inc|Ltd|vs|etc)\.", re.I)
_BREAK = re.compile(r"[.!?]+(?=\s|$)|\n\s*\n|\n(?=\s*[*•\-]\s)")


def split_sentences(text: str) -> List[Tuple[int, int, str]]:
    """Exact sentences of `text` as (start, end, substring). Single newlines are
    treated as spaces (hard-wrapped email), blank lines and bullets split."""
    masked = _ABBR.sub(lambda m: m.group(0)[:-1] + "\u0001", text)
    out: List[Tuple[int, int, str]] = []
    start = 0
    for m in list(_BREAK.finditer(masked)) + [None]:
        end = m.end() if m else len(text)
        seg = text[start:end]
        stripped = seg.strip()
        if len(stripped) >= 3:
            lead = len(seg) - len(seg.lstrip())
            out.append((start + lead, start + lead + len(stripped), stripped))
        start = end
    return out


# -- subjects ------------------------------------------------------------------
_NOISE = r"(reminder|rescheduled|postponed|updated|correction|revised|urgent|notice)"
_WEEKDAY_TAIL = r"(mon|tues?|wed(nes)?|thu(rs)?|fri|sat(ur)?|sun)\w*"


def clean_subject(subject: str) -> str:
    """'Re: Project review meeting - rescheduled' -> 'Project review meeting'."""
    s = subject.strip()
    s = re.sub(r"^\s*((re|fwd?|fw|correction|updated?|reminder|revised|urgent|important)\s*[:\-]\s*)+",
               "", s, flags=re.I)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(rf"\b{_NOISE}\b", " ", s, flags=re.I)
    for _ in range(3):
        s = re.sub(rf"\s+(due|by|on)\s+(this\s+|next\s+)?{_WEEKDAY_TAIL}\s*$", "", s, flags=re.I)
        s = re.sub(r"\s+(deadline|open|opens|opened|released|announced|available|extended|changed|moved)\s*$",
                   "", s, flags=re.I)
        s = re.sub(r"[\s\-–—:]+$", "", s)
    s = re.sub(r"\s+[-–—]\s+[-–—]\s+", " - ", s)
    s = " ".join(s.split())[:100]
    if not s:
        s = " ".join(subject.split())[:100]
    return s[:1].upper() + s[1:]


def subject_key(subject: str) -> str:
    """Stable key so a correction email lands in the same thread as the original."""
    return re.sub(r"[^a-z0-9]+", " ", clean_subject(subject).lower()).strip()
