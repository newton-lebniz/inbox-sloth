"""A scripted stand-in for Gemma so the whole pipeline can be tested offline.
Each entry is what a good model should answer for that sample email."""
import re
from typing import Any, Dict


def task(title, when, quote, kind="task", details=""):
    return {"title": title, "kind": kind, "when": when, "details": details, "source_quote": quote}


# keyed by the email subject
SCRIPT: Dict[str, Dict[str, Any]] = {
    "Probability Assignment 3": {
        "category": "assignment", "summary": "Assignment 3 due Friday night.",
        "tasks": [task("Submit probability assignment 3", "Friday 23 October, 11:59 PM",
                       "The assignment is due Friday 23 October, 11:59 PM.")]},
    "Correction: Probability Assignment 3 deadline": {
        "category": "assignment", "summary": "Deadline moved earlier to Thursday.",
        "tasks": [task("Submit Probability Assignment 3", "Thursday 22 October, 11:59 PM",
                       "Please submit Probability Assignment 3 by Thursday 22 October, 11:59 PM instead.")]},
    "Lab 5 report due Thursday": {
        "category": "assignment", "summary": "Lab 5 report due Thursday 5 PM.",
        "tasks": [task("Submit Lab 5 report", "this Thursday by 5 PM",
                       "the Lab 5 report is due this Thursday by 5 PM.")]},
    "Updated lab instructions for Lab 5": {
        "category": "announcement", "summary": "Lab 5 question 3 now uses matplotlib.", "tasks": []},
    "Project review meeting": {
        "category": "meeting", "summary": "Project review Wednesday 4 PM.",
        "tasks": [task("Project review meeting", "this Wednesday at 4 PM",
                       "Let's have our project review meeting this Wednesday at 4 PM in Lab 3.", kind="meeting")]},
    "Re: Project review meeting - rescheduled": {
        "category": "meeting", "summary": "Meeting moved to Thursday 11 AM.",
        "tasks": [task("Project review meeting", "Thursday at 11 AM",
                       "the project review meeting is rescheduled to Thursday at 11 AM.", kind="meeting")]},
    "Workshop planning meeting": {
        "category": "meeting", "summary": "Planning meeting Saturday morning.",
        "tasks": [task("Attend workshop planning meeting", "Saturday, 24 October at 10:00 AM",
                       "Planning meeting is on Saturday, 24 October at 10:00 AM in the club room.", kind="meeting")]},
    # A weak model might pull events out of a newsletter. The pipeline must drop them.
    "Campus Weekly: Diwali fest, photography club and more": {
        "category": "newsletter", "summary": "Campus news roundup.",
        "tasks": [task("Visit Diwali fest stalls", "28 October",
                       "Diwali fest stalls open from 28 October near the main lawn.")]},
    "Summer internship applications open": {
        "category": "deadline_notice", "summary": "Internship applications close 2 November.",
        "tasks": [task("Apply for summer internship", "2 November",
                       "Applications close on 2 November.")]},
    "Mid-semester examination timetable": {
        "category": "announcement", "summary": "Data Structures exam on 9 November.",
        "tasks": [task("Data Structures mid-sem exam", "9 November, 10:00 AM",
                       "Data Structures exam: 9 November, 10:00 AM, Room LH-2.", kind="exam")]},
    "Slides for the Friday presentation": {
        "category": "reply_needed", "summary": "Send your slides by tomorrow 6 PM.",
        "tasks": [task("Send slides to Ananya", "tomorrow 6 PM",
                       "Can you send me your part of the slides by tomorrow 6 PM?")]},
    "Book return reminder": {
        "category": "deadline_notice", "summary": "Return the library book by 25 October.",
        "tasks": [task("Return library book", "25 October",
                       "Please return it by 25 October to avoid a fine of Rs. 5 per day.")]},
    "Mess menu change this week": {
        "category": "announcement", "summary": "Thursday dinner changes.", "tasks": []},
    "50% off Premium - this weekend only!": {
        "category": "promotion", "summary": "Discount offer.", "tasks": []},
    "Quiz in Python lab": {
        "category": "announcement", "summary": "Quiz Monday 9 AM.",
        "tasks": [task("Python quiz", "Monday at 9:00 AM",
                       "There will be a short quiz on functions and file handling at the start of class on Monday at 9:00 AM.",
                       kind="exam")]},
    "Fee payment reminder - odd semester": {
        "category": "deadline_notice", "summary": "Pay fee by 30 October.",
        "tasks": [task("Pay semester fee", "30 October 2026",
                       "The last date for payment without a late fine is 30 October 2026.")]},
    "Scholarship verification form": {
        "category": "reply_needed", "summary": "Submit the form soon (no date).",
        "tasks": [task("Submit scholarship verification form", "",
                       "Please submit the scholarship verification form to the welfare office soon.")]},
    "Lab 5 viva slots": {
        "category": "reply_needed", "summary": "Reply with a viva slot by Friday.",
        "tasks": [task("Reply with Lab 5 viva slot", "Friday",
                       "Please reply to this email with your preferred slot by Friday.", kind="reply")]},
}


class FakeLLM:
    """Looks up the email subject in the prompt and returns the scripted answer."""

    def __init__(self, script=None):
        self.script = script if script is not None else SCRIPT
        self.calls = 0

    def analyze(self, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        m = re.search(r"^Subject: (.*)$", user, re.M)
        subject = m.group(1) if m else ""
        return self.script[subject]
