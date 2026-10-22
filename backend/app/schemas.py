"""Pydantic models: what we ask the LLM for, and what the API accepts."""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

Category = Literal[
    "assignment",
    "meeting",
    "reply_needed",
    "announcement",
    "deadline_notice",
    "newsletter",
    "promotion",
    "other",
]
Kind = Literal["task", "meeting", "exam", "reply"]

# Categories whose emails never create commitments (a newsletter that lists
# campus events is not *your* obligation).
NO_TASK_CATEGORIES = {"newsletter", "promotion"}


class ExtractedTask(BaseModel):
    """One commitment as the model sees it. Flat and simple on purpose:
    small local models are much more reliable with flat string fields."""

    title: str = Field(description="Short action phrase, max 8 words")
    kind: Kind = "task"
    when: str = Field(default="", description="Date/time words copied from the email, or ''")
    details: str = ""
    source_quote: str = Field(default="", description="One sentence copied word-for-word from the email")

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("empty title")
        return v[:120]

    @field_validator("when", "details", "source_quote")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join((v or "").split())


class EmailAnalysis(BaseModel):
    category: Category = "other"
    summary: str = ""
    tasks: List[ExtractedTask] = Field(default_factory=list, max_length=3)

    @field_validator("summary")
    @classmethod
    def _summary(cls, v: str) -> str:
        return " ".join((v or "").split())[:240]


class Profile(BaseModel):
    role: Literal["student", "professional", "freelancer", "other"] = "student"
    study_start: str = "09:00"
    study_end: str = "22:00"
    priorities: List[str] = Field(default_factory=lambda: ["deadlines", "exams", "meetings"])
    reminder_style: Literal["early", "last_minute"] = "early"
    onboarded: bool = False


class EmailIn(BaseModel):
    id: str
    sender: str = Field(alias="from")
    subject: str
    body: str
    sent_at: str  # ISO 8601, local time
    thread_id: str = ""

    model_config = {"populate_by_name": True}
