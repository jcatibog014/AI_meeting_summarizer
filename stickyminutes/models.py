"""The data model: every table, as a Python class (SQLAlchemy 2.0, typed).

A Workspace holds meetings. The owner has one real workspace (made by
`flask --app stickyminutes create-owner`); every Try Demo click makes a
sandbox workspace of its own, deleted after 24 hours with everything in it
(ON DELETE CASCADE does the deleting).

Times are naive UTC. Money is in MICRO-DOLLARS (1 = $0.000001), an int, so
adding up many small Claude calls never collects float rounding errors.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .dates import utcnow
from .db import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    # AUTOINCREMENT: SQLite would otherwise give a deleted demo's id to the next one,
    # and an old cookie could open the new demo (ShiroMoto's lesson).
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    demo_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    time_zone: Mapped[str] = mapped_column(String(64), default="Asia/Manila", server_default="Asia/Manila")
    # Which Claude model summarizes (pricing.MODELS). Settings changes it.
    model: Mapped[str] = mapped_column(String(40), default="claude-opus-5-5", server_default="claude-opus-5-5")
    # Part of the calendar feed's signed link (actions.py). A new one ends every old link.
    feed_nonce: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="workspace", cascade="all, delete-orphan",
                                               passive_deletes=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Part of the login cookie. Changing the password adds 1, so every old cookie stops working.
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="users")

    @property
    def initial(self):
        return (self.name or "?")[:1].upper()

    @property
    def first_name(self):
        return (self.name or "").split(" ")[0]


class RateLimit(Base):
    """A counter per key ("login-ip:1.2.3.4") and when its window started (limits.py)."""
    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime)


class Meeting(Base):
    """One meeting: its transcript (as TranscriptLine rows) and, once summarized, its notes."""
    __tablename__ = "meetings"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    # False while the title is our own stand-in ("Meeting on 24 Nov"): the summary may then name it.
    title_from_user: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    meeting_date: Mapped[date] = mapped_column(Date)
    source_kind: Mapped[str] = mapped_column(String(10))        # transcripts.KINDS
    source_name: Mapped[str | None] = mapped_column(String(200))  # the uploaded file's name
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    speakers: Mapped[list] = mapped_column(JSON, default=list)
    # new -> queued -> running -> ready | needs_review | failed (summarize.py)
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new")
    # The summary's 2-4 sentences, from the accepted run (summarize.py).
    overview: Mapped[str | None] = mapped_column(Text)
    # The read-only share link (exports.py): None = off. Turning it on again makes a new number,
    # so an old link never comes back to life.
    share_nonce: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    lines: Mapped[list["TranscriptLine"]] = relationship(back_populates="meeting", order_by="TranscriptLine.n",
                                                         cascade="all, delete-orphan", passive_deletes=True)


class TranscriptLine(Base):
    """One numbered line of a transcript. The numbers never change once saved: notes point at them."""
    __tablename__ = "transcript_lines"
    __table_args__ = (UniqueConstraint("meeting_id", "n"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    n: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(String(60))
    at: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)

    meeting: Mapped[Meeting] = relationship(back_populates="lines")


class Run(Base):
    """One summary of one meeting: every Claude call it took, what they cost, and how it ended."""
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    # queued -> running -> done | needs_review | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    model: Mapped[str] = mapped_column(String(40))                 # the model asked for
    served_model: Mapped[str | None] = mapped_column(String(40))   # the one that answered (a fallback may step in)
    prompt_version: Mapped[str] = mapped_column(String(20))
    effort: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")
    practice: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_micros: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimate_micros: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text)
    raw_output: Mapped[str | None] = mapped_column(Text)           # the last answer, as Claude wrote it
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    meeting: Mapped[Meeting] = relationship()
    issues: Mapped[list["RunIssue"]] = relationship(back_populates="run", order_by="RunIssue.id",
                                                    cascade="all, delete-orphan", passive_deletes=True)

    @property
    def seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class RunIssue(Base):
    """One problem one attempt's answer had (schema.Problem), and whether a later attempt fixed it."""
    __tablename__ = "run_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    layer: Mapped[str] = mapped_column(String(20))     # schema, rules, grounding
    path: Mapped[str] = mapped_column(String(120), default="")
    message: Mapped[str] = mapped_column(Text)
    fixed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    run: Mapped[Run] = relationship(back_populates="issues")


class Item(Base):
    """One note on the board: a key point, a decision, an action item or an open question."""
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(10))      # point, decision, action, question
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)   # a decision's reason
    owner: Mapped[str | None] = mapped_column(String(60))
    due_phrase: Mapped[str | None] = mapped_column(String(80))
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str | None] = mapped_column(String(10))
    # Action items: open or done.
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Review & Proof: unreviewed, accepted or rejected; flag says why a check doubted it.
    review: Mapped[str] = mapped_column(String(12), default="unreviewed", server_default="unreviewed")
    flag: Mapped[str | None] = mapped_column(Text)
    # [{"line": 12, "quote": "...", "found": true}, ...]
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UsageEntry(Base):
    """What one Claude call cost, for the daily spending cap (budget.py). Kept when a demo is deleted."""
    __tablename__ = "usage_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)  # the UTC day
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    cost_micros: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
