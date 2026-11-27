"""Talking to Claude: one request in, one Reply out, and every way it can go wrong.

The request (Claude.summarize):

- `client.beta.messages.create(...)` with the official `anthropic` SDK. The
  beta endpoint is for the **refusal fallback**: if a safety check stops the
  chosen model (`stop_reason == "refusal"`), the API itself can hand the
  request to another model (`fallbacks="default"`, beta
  `server-side-fallback-2026-07-01`). Haiku has no fallback.
- `output_config.format` is the JSON schema from schema.MeetingNotes, made
  with `anthropic.transform_schema()`: **structured outputs**, so the answer
  is always JSON of that shape.
- `output_config.effort` is "medium" (Opus 5.5's own default, set out loud).
  Thinking is adaptive and always on with these models; it isn't set here.
- No streaming: an answer is at most 16,000 tokens, well inside the SDK's
  timeouts, and the page shows progress by asking the server (summarize.py).

Every failure becomes an LLMError with a plain message for the page and a
`code` for the Quality Lab. The SDK's errors are caught from the most
specific to the least (an auth error is also a status error, which is also
an API error), so each one gets the right words.

FakeClaude has the same two methods. It answers in tests (always), and in
**practice mode** when no ANTHROPIC_API_KEY is set: then it writes simple
notes from the transcript's own words, so the whole app can be tried for free.
"""
import json
import re
from dataclasses import dataclass, field

from . import pricing
from .schema import MeetingNotes

MAX_TOKENS = 16_000
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
TIMEOUT_SECONDS = 300


@dataclass
class Reply:
    text: str                    # the JSON answer
    content: list                # the answer's content blocks, to send back unchanged in a repair turn
    stop_reason: str
    model: str                   # the model that actually answered (a fallback may have stepped in)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    fallback_used: bool = False

    def cost_micros(self):
        return pricing.cost_micros(self.model, self.input_tokens, self.output_tokens, self.cache_read, self.cache_write)


class LLMError(Exception):
    """Claude couldn't give an answer. `message` is for people; `code` for the Quality Lab."""

    def __init__(self, code, message, retry=False, reply=None):
        super().__init__(message)
        self.code, self.message, self.retry, self.reply = code, message, retry, reply


def output_config(effort=EFFORT):
    return {"effort": effort, "format": {"type": "json_schema", "schema": _schema()}}


_SCHEMA = None


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        import anthropic
        _SCHEMA = anthropic.transform_schema(MeetingNotes)
    return _SCHEMA


def text_of(content):
    """The answer's text: the text blocks, joined (thinking blocks have none to show)."""
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")


class Claude:
    practice = False

    def __init__(self, api_key):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=2)

    def count_tokens(self, model, system, messages):
        """What the request would cost in input tokens, asked before sending it (free)."""
        try:
            return self.client.messages.count_tokens(model=model, system=system, messages=messages,
                                                     output_config=output_config()).input_tokens
        except self._anthropic.APIError as error:
            raise self._translate(error) from error

    def summarize(self, model, system, messages, effort=EFFORT):
        extra = {}
        if pricing.model(model).fallback:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self.client.beta.messages.create(
                model=model, max_tokens=MAX_TOKENS, system=system, messages=messages,
                output_config=output_config(effort), **extra)
        except self._anthropic.APIError as error:
            raise self._translate(error) from error
        content = [block.to_dict() for block in response.content
                   if block.type in ("text", "thinking", "redacted_thinking")]
        usage = response.usage
        reply = Reply(
            text=text_of(content), content=content, stop_reason=response.stop_reason or "", model=response.model or model,
            input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0,
            cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            fallback_used=any(getattr(entry, "type", "") == "fallback_message" for entry in (getattr(usage, "iterations", None) or [])))
        return check_stop(reply, getattr(response, "stop_details", None))

    def _translate(self, error):
        a = self._anthropic
        # Most specific first: AuthenticationError is an APIStatusError, which is an APIError.
        if isinstance(error, a.AuthenticationError):
            return LLMError("auth", "Claude refused the API key. Check ANTHROPIC_API_KEY.")
        if isinstance(error, a.PermissionDeniedError):
            return LLMError("permission", "This API key can't use that model. Choose another one in Settings.")
        if isinstance(error, a.RateLimitError):
            return LLMError("rate_limit", "Claude is getting too many requests from this site. Try again in a minute.", retry=True)
        if isinstance(error, (a.RequestTooLargeError, a.ContentTooLargeError)):
            return LLMError("too_large", "This transcript is too big for one request. Split the meeting in two.")
        if isinstance(error, a.BadRequestError):
            detail = str(getattr(error, "message", "") or error).rstrip(".")
            return LLMError("bad_request", f"Claude couldn't take this request ({detail}).")
        if isinstance(error, a.APIStatusError):
            if error.status_code in (500, 502, 503, 504, 529):
                return LLMError("overloaded", "Claude is very busy right now. Try again in a few minutes.", retry=True)
            return LLMError("api", f"Claude answered with an error ({error.status_code}).")
        if isinstance(error, a.APITimeoutError):
            return LLMError("timeout", "Claude took too long to answer. Try again.", retry=True)
        if isinstance(error, a.APIConnectionError):
            return LLMError("connection", "We couldn't reach Claude. Check the internet connection and try again.", retry=True)
        return LLMError("api", "Something went wrong talking to Claude.")


def check_stop(reply, stop_details=None):
    """Why the answer ended, read BEFORE its content is used."""
    if reply.stop_reason == "refusal":
        category = getattr(stop_details, "category", None) if stop_details is not None else None
        raise LLMError("refusal", "Claude declined to summarize this transcript"
                       + (f" (its safety check: {category})." if category else "."), reply=reply)
    if reply.stop_reason == "max_tokens":
        raise LLMError("max_tokens", "Claude's answer was cut off because it was too long. Try a shorter transcript.",
                       reply=reply)
    return reply


# ---------- The stand-in: tests and practice mode ----------

LINE = re.compile(r"^\[(\d+)\] (.+?)(?: \(([\d:]+)\))?: (.*)$")
DECIDED = re.compile(r"\b(we agreed|agreed|we'll go with|let's go with|we decided|decided|we're going with|settled on|final(?:ly)?,? we)\b", re.I)
WILL_DO = re.compile(r"\b(I'll|I will|I can take|I'll take|I'm going to|let me)\b", re.I)
DUE = re.compile(r"\b(by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week|the end of the (?:week|month))"
                 r"|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|tomorrow|next (?:week|monday|tuesday|wednesday|thursday|friday))\b", re.I)


def transcript_lines(messages):
    """The (n, speaker, text) lines inside the first message's <transcript> block."""
    first = messages[0]["content"]
    blocks = first if isinstance(first, list) else [{"type": "text", "text": first}]
    text = next((block["text"] for block in blocks if "<transcript>" in block.get("text", "")), "")
    found = []
    for row in text.splitlines():
        if match := LINE.match(row):
            found.append((int(match[1]), match[2], match[4]))
    return found


def quote(text, words=18):
    return " ".join(text.split()[:words])


def first_sentence(text, limit=280):
    sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return sentence[:limit].rstrip()


def practice_notes(messages):
    """Simple notes made from the words in the transcript, without any AI. Not clever, but real:
    every item points at a line that says it, so the checks pass."""
    lines = transcript_lines(messages)
    speakers = []
    for _, who, _ in lines:
        if who != "Unknown speaker" and who not in speakers:
            speakers.append(who)
    evidence = lambda n, text: [{"line": n, "quote": quote(text)}]  # noqa: E731
    decisions = [{"text": first_sentence(text), "rationale": None, "evidence": evidence(n, text)}
                 for n, _, text in lines if DECIDED.search(text)][:6]
    actions = []
    for n, who, text in lines:
        if WILL_DO.search(text):
            due = DUE.search(text)
            actions.append({"task": first_sentence(text), "owner": None if who == "Unknown speaker" else who,
                            "due_phrase": due[0] if due else None, "due_date": None, "priority": "medium",
                            "evidence": evidence(n, text)})
    questions = [{"text": next(part for part in re.split(r"(?<=[.!?])\s", text) if part.endswith("?"))[:280],
                  "evidence": evidence(n, text)} for n, _, text in lines if "?" in text][:4]
    longest = sorted(lines, key=lambda line: -len(line[2]))[:4]
    points = [{"text": first_sentence(text), "evidence": evidence(n, text)} for n, _, text in sorted(longest)]
    people = ", ".join(speakers[:4]) + (" and others" if len(speakers) > 4 else "")
    overview = (f"Practice notes, made from the transcript's own words without Claude. "
                f"{len(speakers) or 'Some'} people spoke over {len(lines)} lines{': ' + people if people else ''}. "
                f"It found {len(decisions)} decision{'s' if len(decisions) != 1 else ''} and "
                f"{len(actions[:8])} action item{'s' if len(actions[:8]) != 1 else ''}.")
    title = ("Meeting with " + " and ".join(speakers[:2])) if speakers else "Practice notes"
    return {"title": title[:80], "overview": overview, "key_points": points, "decisions": decisions,
            "action_items": actions[:8], "open_questions": questions}


@dataclass
class FakeClaude:
    """Answers without the internet. `script` is a list of answers, used in order: a dict (sent as
    JSON), a str (sent as it is, broken JSON included), an LLMError (raised), or a function of the
    messages. When the script runs out, the last answer repeats. No script: practice notes."""
    script: list | None = None
    practice: bool = True
    calls: list = field(default_factory=list)
    tokens_per_char: float = 0.25

    def count_tokens(self, model, system, messages):
        return int(len(json.dumps(system)) * self.tokens_per_char + len(json.dumps(messages)) * self.tokens_per_char)

    def summarize(self, model, system, messages, effort=EFFORT):
        self.calls.append({"model": model, "system": system, "messages": messages, "effort": effort})
        if self.script is None:
            answer = practice_notes(messages)
        else:
            answer = self.script[min(len(self.calls), len(self.script)) - 1]
        if isinstance(answer, LLMError):
            raise answer
        if callable(answer):
            answer = answer(messages)
        stop_reason = "end_turn"
        if isinstance(answer, tuple):  # (stop_reason, text): a cut-off or refused answer
            stop_reason, answer = answer
        text = answer if isinstance(answer, str) else json.dumps(answer)
        reply = Reply(text=text, content=[{"type": "text", "text": text}], stop_reason=stop_reason, model=model,
                      input_tokens=self.count_tokens(model, system, messages), output_tokens=len(text) // 4)
        return check_stop(reply)


def client_for(app):
    """The real Claude when there is a key, else the practice stand-in. Made once per app.
    Tests put their own FakeClaude on app.extensions["claude"] first."""
    if "claude" not in app.extensions:
        key = app.config.get("ANTHROPIC_API_KEY")
        app.extensions["claude"] = Claude(key) if key else FakeClaude()
    return app.extensions["claude"]


def is_practice(app):
    """True when summaries are the free practice notes (no API key): no money, no limits."""
    return client_for(app).practice
