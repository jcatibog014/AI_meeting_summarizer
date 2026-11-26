"""The shape Claude's answer must have: MeetingNotes, written as Pydantic models.

This one class does two jobs, and they are the first two of our three
layers of checking:

1. **The API's layer (structured outputs).** llm.py sends
   `anthropic.transform_schema(MeetingNotes)` as `output_config.format`, so
   Claude can only write JSON with these fields and these types. The API
   enforces the SHAPE: every field present, strings are strings, `priority`
   is one of three words, no extra fields.
2. **Our layer (Pydantic).** Some rules the API can't enforce in its JSON
   schema: lengths, number ranges, "not blank", "at most 4 sentences".
   transform_schema moves those into the field descriptions (so Claude still
   reads them), and `validate()` below checks them here, in Python. A broken
   rule becomes a Problem that the repair turn (summarize.py) sends back.

The third layer, that every note really comes from the transcript, is in
checks.py: that needs the transcript, and a schema can't know it.
"""
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

TEXT_MAX = 300
QUOTE_MAX = 300


def _not_blank(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be empty")
    return value


Text = Annotated[str, Field(min_length=1, max_length=TEXT_MAX)]


class Evidence(BaseModel):
    """Where in the transcript a note comes from."""
    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=1, description="The number in [brackets] at the start of the transcript line this comes from.")
    quote: str = Field(min_length=1, max_length=QUOTE_MAX,
                       description="Words copied exactly, letter for letter, from that one line: 3 to 25 words. Never reworded.")

    _clean = field_validator("quote")(_not_blank)


EvidenceList = Annotated[list[Evidence], Field(min_length=1, max_length=3,
                                                description="1 to 3 places in the transcript that show this.")]


class KeyPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Text = Field(description="One thing that was discussed or learned, in one sentence.")
    evidence: EvidenceList
    _clean = field_validator("text")(_not_blank)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Text = Field(description="What the group agreed or decided, as a plain statement.")
    rationale: str | None = Field(max_length=TEXT_MAX, description="Why, if the transcript says why; otherwise null.")
    evidence: EvidenceList
    _clean = field_validator("text")(_not_blank)


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: Text = Field(description="What must be done, starting with a verb: 'Send the price list to Ana'.")
    owner: str | None = Field(max_length=60, description=(
        "Who will do it: their name exactly as the transcript's speaker label writes it, "
        "or a name said in the meeting. null if nobody took it on."))
    due_phrase: str | None = Field(max_length=80, description="The words used for when it is due ('by Friday', 'next week'), or null.")
    due_date: date | None = Field(description="That day as YYYY-MM-DD, worked out from the meeting's date, or null if no day was said.")
    priority: Literal["low", "medium", "high"] = Field(description="high if the meeting called it urgent or it blocks other work.")
    evidence: EvidenceList
    _clean = field_validator("task")(_not_blank)


class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Text = Field(description="A question the meeting raised but did not answer.")
    evidence: EvidenceList
    _clean = field_validator("text")(_not_blank)


class MeetingNotes(BaseModel):
    """Everything Claude writes about one meeting."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80, description="A short name for the meeting, 2 to 8 words.")
    overview: str = Field(min_length=1, max_length=700, description="What the meeting was about and what came of it, in 2 to 4 sentences.")
    key_points: list[KeyPoint] = Field(max_length=8)
    decisions: list[Decision] = Field(max_length=12)
    action_items: list[ActionItem] = Field(max_length=20)
    open_questions: list[OpenQuestion] = Field(max_length=8)

    _clean = field_validator("title", "overview")(_not_blank)

    @field_validator("overview")
    @classmethod
    def at_most_five_sentences(cls, value):
        sentences = [part for part in re.split(r"(?<=[.!?])\s+", value) if part.strip()]
        if len(sentences) > 5:
            raise ValueError(f"has {len(sentences)} sentences; use 2 to 4")
        return value


# ---------- Checking an answer ----------

@dataclass
class Problem:
    """One thing wrong with an answer: which layer found it, where, and what."""
    layer: str      # "schema" (not JSON / wrong shape), "rules" (Pydantic), "grounding" (checks.py)
    path: str       # "action_items.2.owner", or "" for the whole answer
    message: str

    def __str__(self):
        return f"{self.path}: {self.message}" if self.path else self.message


def path_of(location):
    return ".".join(str(part) for part in location)


def validate(text):
    """Claude's text -> (MeetingNotes, []) or (None, [Problem, ...])."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        return None, [Problem("schema", "", f"the answer is not valid JSON ({error})")]
    try:
        return MeetingNotes.model_validate(data), []
    except ValidationError as error:
        problems = []
        for issue in error.errors(include_url=False):
            # A wrong type or a missing field is the API's layer failing (it shouldn't, with
            # structured outputs on); a broken length or range is our rules' layer.
            layer = "schema" if issue["type"] in ("missing", "extra_forbidden", "model_type", "list_type",
                                                  "string_type", "int_type", "int_parsing", "literal_error") else "rules"
            message = issue["msg"].removeprefix("Value error, ")
            problems.append(Problem(layer, path_of(issue["loc"]), message))
        return None, problems
