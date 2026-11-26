"""The Claude models Sticky Minutes can use, and what they cost.

Prices are US dollars per million tokens (Anthropic's price list, November
2026). We count money in MICRO-DOLLARS (an int: 1_000_000 = $1), so a
thousand small calls add up exactly.

- input: what we send (the instructions + the transcript)
- output: what Claude writes, its thinking included (thinking is billed as output)
- cache_write / cache_read: the transcript is marked for the prompt cache, so a
  repair retry (summarize.py) reads it back for a small part of the price.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    note: str
    input: float        # $ per million tokens
    output: float
    cache_read: float
    cache_write: float
    # Server-side refusal fallback (llm.py): Opus and Sonnet have it, Haiku doesn't.
    fallback: bool


MODELS = {
    "claude-opus-5-5": Model("claude-opus-5-5", "Claude Opus 5.5", "The best notes. About 10 cents for an hour of meeting.",
                             4.00, 20.00, 0.20, 5.00, True),
    "claude-sonnet-5-5": Model("claude-sonnet-5-5", "Claude Sonnet 5.5", "Fast and good, about half the price of Opus.",
                               2.00, 10.00, 0.10, 2.50, True),
    "claude-haiku-5-5": Model("claude-haiku-5-5", "Claude Haiku 5.5", "The quickest and cheapest, with simpler notes.",
                              0.10, 0.50, 0.01, 0.125, False),
}
DEFAULT_MODEL = "claude-opus-5-5"


def model(model_id):
    return MODELS.get(model_id) or MODELS[DEFAULT_MODEL]


def cost_micros(model_id, input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
    """What one call cost, in micro-dollars (rounded up, so we never count too little)."""
    m = model(model_id)
    # $ per million tokens x tokens = millionths of a dollar: exactly micro-dollars.
    micros = (input_tokens * m.input + output_tokens * m.output
              + cache_read * m.cache_read + cache_write * m.cache_write)
    return int(-(-micros // 1))


def dollars(micros):
    """125000 -> '$0.13'. Amounts under a cent keep 4 places, so they don't show as $0.00."""
    amount = (micros or 0) / 1_000_000
    if 0 < amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:,.2f}"


def cents(micros):
    """A short estimate for buttons: 'under 1 cent', 'about 3 cents', 'about $1.20'."""
    amount = (micros or 0) / 10_000
    if amount < 1:
        return "under 1 cent"
    if amount < 100:
        whole = round(amount)
        return f"about {whole} cent{'s' if whole != 1 else ''}"
    return f"about {dollars(micros)}"
