"""The Claude request (without the network), its errors, and the practice stand-in."""
import json
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from stickyminutes import llm, schema
from stickyminutes.llm import Claude, FakeClaude, LLMError

from .samples import GOOD


class Recorder:
    """Stands in for client.beta.messages: remembers the request, answers with `response`."""

    def __init__(self, response=None, error=None):
        self.kwargs, self.response, self.error = None, response, error

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def response(text, stop_reason="end_turn", model="claude-opus-5-5", iterations=None, stop_details=None):
    blocks = [SimpleNamespace(type="thinking", to_dict=lambda: {"type": "thinking", "thinking": "", "signature": "sig"}),
              SimpleNamespace(type="text", to_dict=lambda: {"type": "text", "text": text})]
    usage = SimpleNamespace(input_tokens=1200, output_tokens=800, cache_read_input_tokens=0,
                            cache_creation_input_tokens=1000, iterations=iterations)
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, model=model, usage=usage, stop_details=stop_details)


def claude_with(recorder):
    claude = Claude("sk-test")
    claude.client = SimpleNamespace(beta=SimpleNamespace(messages=recorder))
    return claude


MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "<transcript>\n[1] A: hi\n</transcript>"}]}]
SYSTEM = [{"type": "text", "text": "You write meeting minutes."}]


def test_the_request_asks_for_our_json_shape_with_the_refusal_fallback():
    recorder = Recorder(response(json.dumps(GOOD)))
    reply = claude_with(recorder).summarize("claude-opus-5-5", SYSTEM, MESSAGES)
    sent = recorder.kwargs
    assert sent["model"] == "claude-opus-5-5" and sent["max_tokens"] == 16_000
    assert sent["output_config"]["effort"] == "medium"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert set(sent["output_config"]["format"]["schema"]["properties"]) == set(schema.MeetingNotes.model_fields)
    assert sent["betas"] == ["server-side-fallback-2026-07-01"] and sent["fallbacks"] == "default"
    assert "thinking" not in sent and "temperature" not in sent  # adaptive thinking is the default; sampling is gone
    assert reply.text == json.dumps(GOOD)
    # The thinking block is kept, so a repair turn can send the answer back unchanged.
    assert [block["type"] for block in reply.content] == ["thinking", "text"]
    assert (reply.input_tokens, reply.output_tokens, reply.cache_write) == (1200, 800, 1000)


def test_haiku_has_no_fallback():
    recorder = Recorder(response("{}"))
    claude_with(recorder).summarize("claude-haiku-5-5", SYSTEM, MESSAGES)
    assert "fallbacks" not in recorder.kwargs


def test_a_fallback_is_noticed():
    recorder = Recorder(response("{}", model="claude-opus-4-8", iterations=[SimpleNamespace(type="fallback_message")]))
    reply = claude_with(recorder).summarize("claude-opus-5-5", SYSTEM, MESSAGES)
    assert reply.fallback_used and reply.model == "claude-opus-4-8"


def test_a_refusal_is_read_before_the_content():
    recorder = Recorder(response("", stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")))
    with pytest.raises(LLMError) as caught:
        claude_with(recorder).summarize("claude-opus-5-5", SYSTEM, MESSAGES)
    assert caught.value.code == "refusal" and "cyber" in caught.value.message
    assert caught.value.reply is not None  # it was still paid for


def test_a_cut_off_answer_is_an_error():
    with pytest.raises(LLMError) as caught:
        claude_with(Recorder(response('{"title": "Laun', stop_reason="max_tokens"))).summarize("claude-opus-5-5", SYSTEM, MESSAGES)
    assert caught.value.code == "max_tokens"


def status_error(cls, code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(code, request=request), body=None)


@pytest.mark.parametrize("error, code, retry", [
    (status_error(anthropic.AuthenticationError, 401), "auth", False),
    (status_error(anthropic.PermissionDeniedError, 403), "permission", False),
    (status_error(anthropic.RateLimitError, 429), "rate_limit", True),
    (status_error(anthropic.BadRequestError, 400), "bad_request", False),
    (status_error(anthropic.InternalServerError, 500), "overloaded", True),
    (anthropic.APITimeoutError(httpx.Request("POST", "https://api.anthropic.com")), "timeout", True),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "connection", True),
])
def test_every_sdk_error_gets_its_own_plain_message(error, code, retry):
    with pytest.raises(LLMError) as caught:
        claude_with(Recorder(error=error)).summarize("claude-opus-5-5", SYSTEM, MESSAGES)
    assert caught.value.code == code and caught.value.retry is retry
    assert caught.value.message.endswith(".")


def test_practice_notes_come_from_the_transcripts_own_words():
    from stickyminutes import transcripts

    from .samples import MEETING
    lines = transcripts.parse(MEETING).lines
    messages = [{"role": "user", "content": [{"type": "text", "text": f"<transcript>\n{transcripts.numbered(lines)}\n</transcript>"}]}]
    reply = FakeClaude().summarize("claude-opus-5-5", SYSTEM, messages)
    notes, problems = schema.validate(reply.text)
    assert problems == [] and notes.title == "Meeting with Maria Santos and Ben Cruz"
    assert [d.evidence[0].line for d in notes.decisions] == [4, 5]
    assert {a.owner for a in notes.action_items} >= {"Ben Cruz", "Ana Reyes"}
    by_line = {line.n: line.text for line in lines}
    for item in notes.decisions + notes.action_items + notes.key_points + notes.open_questions:
        for e in item.evidence:
            assert e.quote in by_line[e.line]


def test_the_fake_follows_its_script():
    fake = FakeClaude(script=["not json", GOOD, LLMError("overloaded", "Busy.")])
    assert fake.summarize("m", SYSTEM, MESSAGES).text == "not json"
    assert json.loads(fake.summarize("m", SYSTEM, MESSAGES).text) == GOOD
    with pytest.raises(LLMError):
        fake.summarize("m", SYSTEM, MESSAGES)


def test_no_key_means_practice_mode(app):
    assert llm.is_practice(app)
