"""Grounding: check the model's output against the email text, in plain code.

A 1B model is a noisy witness. Day 1 showed it (a) returns no task for clear
emails, (b) invents tasks for informational emails, (c) rewrites dates and
quotes, (d) picks poor titles and kinds. So the model proposes and this module
corroborates:

  * a task needs a cue in the email: an action/deadline/meeting/exam word
  * a date must literally be in the email, in a sentence that also has a cue
  * the evidence sentence is chosen by code, never trusted from the model
  * kind and title are normalised from the email subject and evidence
  * if the model returns nothing, a small rule-based fallback may propose ONE
    task, subject to the same checks
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .dates import resolve
from .schemas import ExtractedTask
from .textnorm import (clean_subject, content_tokens, date_tokens, split_sentences,
                       text_date_tokens)

# Something the reader must do, attend, reply to, or a deadline/event.
CUE_RE = re.compile(r"""\b(
    submit\w*|upload\w*|attend\w*|reply|respond\w*|send|pay\w*|return\w*|bring|fill|apply|
    register\w*|complete\w*|finish\w*|book|review|prepare|confirm\w*|sign|collect|join|enrol\w*|
    please|must|required|mandatory|need\s+to|needs\s+to|should|kindly|
    deadline|due(?!\s+to)|last\s+date|closes?|closing|expires?|
    meeting|standup|stand-up|sync|workshop|seminar|webinar|lecture|interview|session|appointment|
    exam|exams|examination|quiz|viva|presentation|demo|contest|hackathon|class
)\b""", re.I | re.X)

# Talking about something that already happened is not a commitment.
PAST_RE = re.compile(
    r"\b(thanks?|thank you)\s+for\b|\blast\s+(week|month|mon|tues?|wed|thu|fri|sat|sun)\w*|"
    r"\b(attended|was held|were held|has been held|have been held|took place)\b", re.I)

# Mass mail never creates tasks, whatever the model says.
BULK_RE = re.compile(
    r"unsubscribe|view (this )?(email )?in (your )?browser|manage (your )?(email )?preferences|"
    r"you are receiving this|\buse code\b|\bpromo code\b|\bcoupon\b|\b\d{1,3}\s?% off\b", re.I)

# An explicit request to the reader, used for the undated fallback.
REQUEST_RE = re.compile(
    r"\b(please|kindly|you (must|need to|should))\s+"
    r"(submit|send|reply|respond|bring|fill|upload|pay|return|complete|attend|register|confirm|collect)\b",
    re.I)

EXAM_RE = re.compile(
    r"\b(exam|exams|examination|quiz|quizzes|mid-?sem(ester)?|end-?sem(ester)?|"
    r"unit test|class test|written test|online test)\b", re.I)
MEETING_RE = re.compile(
    r"\b(meeting|standup|stand-up|sync|workshop|seminar|webinar|lecture|interview|session|appointment)\b", re.I)
REPLY_RE = re.compile(r"\b(reply|respond|rsvp|get back to)\b", re.I)

LEAD_VERBS = {"submit", "attend", "take", "complete", "do", "join", "go", "write", "give", "finish", "prepare"}
GENERIC_REPLY = re.compile(r"^(reply|respond)( to)?( the| this| your)?( email| message| mail)?$", re.I)


@dataclass
class Grounding:
    ok: bool
    strong: bool = False        # cue and date found together in one sentence
    sentence: str = ""          # evidence, an exact substring of the email
    date_text: str = ""         # the words resolve() should read ("" = no date)
    healed: bool = False        # model's date was not in the email; used the email's own
    reason: str = ""            # why the task was skipped


CANCEL_RE = re.compile(r"\bcancel\w*|\bcalled off\b|\bno longer\b|\bwill not be held\b", re.I)
RESCHED_RE = re.compile(r"\b(reschedul\w*|postpon\w*|moved|instead|new date|new time|shifted)\b", re.I)


def has_cue(sentence: str) -> bool:
    """Does this sentence ask the reader to do, attend or meet something in the future?"""
    if not CUE_RE.search(sentence) or PAST_RE.search(sentence):
        return False
    return not (CANCEL_RE.search(sentence) and not RESCHED_RE.search(sentence))


def looks_bulk(subject: str, body: str) -> bool:
    return bool(BULK_RE.search(f"{subject}\n{body}"))


def title_supported(title: str, text: str) -> bool:
    """At least half of the title's content words must be in the email. One shared word is
    not enough ('Book a hotel for the viva' shares 'viva' with a viva-slots email)."""
    toks = content_tokens(title)
    return not toks or len(toks & content_tokens(text)) / len(toks) >= 0.5


def _overlap(title_toks: set, sentence: str) -> float:
    return len(title_toks & content_tokens(sentence)) / len(title_toks) if title_toks else 0.0


def date_specificity(sentence: str) -> int:
    """How precisely a sentence states a date; used to pick the best of several."""
    s = sentence.lower()
    score = 0
    if re.search(r"\b\d{1,2}(st|nd|rd|th)?\s+(of\s+)?[a-z]{3,9}\b", s) and date_tokens(s) & {
            f"m{i}" for i in range(1, 13)}:
        score += 3
    elif re.search(r"\b\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2}", s):
        score += 3
    if date_tokens(s) & {f"w{i}" for i in range(7)} or re.search(r"\b(today|tomorrow)\b", s):
        score += 1
    if re.search(r"\d\s*(am|pm)|\d:\d\d|noon", s):
        score += 1
    if re.search(r"\b(please|must|submit|by|before)\b", s):
        score += 1
    return score


def ground_task(subject: str, body: str, task: ExtractedTask, sent_at: datetime) -> Grounding:
    text = f"{subject}\n{body}"
    if not title_supported(task.title, text):
        return Grounding(False, reason="title_not_in_email")
    sents = [s for _, _, s in split_sentences(body)]
    if resolve(subject, sent_at).due is not None:     # a subject is evidence only if it states a date
        sents.append(subject.strip())                 # (otherwise a title copied from it proves itself)
    if not any(has_cue(s) for s in sents):
        return Grounding(False, reason="informational")
    ttoks = content_tokens(task.title)

    def overlap(s: str) -> float:
        return _overlap(ttoks, s)

    had_date = False
    ptoks = date_tokens(task.when) if task.when.strip() else set()
    if ptoks:
        had_date = True
        supported = [s for s in sents if ptoks <= text_date_tokens(s)]
        if supported:
            cue = [s for s in supported if has_cue(s)]
            best = max(cue or supported, key=overlap)
            return Grounding(True, strong=bool(cue), sentence=best, date_text=task.when)
        # The model's date words are not in the email. Use the email's own date if a
        # cue sentence has exactly one to offer; never keep an invented one.
        dated = [s for s in sents if has_cue(s) and resolve(s, sent_at).due is not None]
        if dated:
            best = max(dated, key=lambda s: (date_specificity(s), overlap(s)))
            return Grounding(True, strong=True, sentence=best, date_text=best, healed=True)

    cands = [s for s in sents if has_cue(s) and overlap(s) >= 0.25]
    if cands:
        return Grounding(True, strong=True, sentence=max(cands, key=overlap), date_text="")
    return Grounding(False, reason="date_not_in_email" if had_date else "no_evidence")


def infer_kind(model_kind: str, title: str, subject: str, sentence: str) -> str:
    """Kind from the words in the email beats the model's guess. exam > meeting > reply."""
    head = f"{title}\n{subject}"
    if EXAM_RE.search(head) or EXAM_RE.search(sentence):
        return "exam"
    if MEETING_RE.search(head) or (model_kind == "meeting" and MEETING_RE.search(sentence)):
        return "meeting"
    if REPLY_RE.search(title) or REPLY_RE.search(sentence):
        return "reply"
    return model_kind


def refine_title(title: str, kind: str, subject: str) -> str:
    """Make titles name the thing, not a step inside it ('Finalise speaker list' for a
    meeting becomes the meeting's own name from the subject)."""
    t = " ".join(title.split())
    cs = clean_subject(subject)
    ttok, stok = content_tokens(t), content_tokens(cs)

    if kind in ("meeting", "exam"):
        parts = t.split()
        if len(parts) > 1 and parts[0].lower() in LEAD_VERBS:
            t = " ".join(parts[1:])
        rx = EXAM_RE if kind == "exam" else MEETING_RE
        t_has, cs_has = bool(rx.search(t)), bool(rx.search(cs))
        if cs_has and (not t_has or content_tokens(t) <= stok):
            t = cs
    elif kind == "reply":
        if GENERIC_REPLY.match(t) or not ttok or not (ttok & stok):
            t = f"Reply: {cs}"
    else:
        if not ttok:
            t = cs
        elif not (ttok & stok):
            t = f"{t} \u2014 {cs}"
    return t[:1].upper() + t[1:]


def fallback_candidates(subject: str, body: str, sent_at: datetime, category: str) -> List[ExtractedTask]:
    """The model found nothing. Propose at most ONE task from the email itself, only if a
    sentence has a cue and a usable date (or is an explicit request when undated)."""
    if looks_bulk(subject, body):
        return []
    title = clean_subject(subject)
    if not title:
        return []
    sents = [s for _, _, s in split_sentences(body)]
    dated = []
    for s in sents:
        if has_cue(s):
            r = resolve(s, sent_at)
            if r.due is not None and r.confidence != "low":
                dated.append(s)
    if dated:
        best = max(dated, key=date_specificity)        # first wins ties
        return [ExtractedTask(title=title, kind="task", when=best, source_quote=best)]
    for s in sents:
        if REQUEST_RE.search(s):
            return [ExtractedTask(title=title, kind="task", when="", source_quote=s)]
    return []
