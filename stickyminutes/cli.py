"""`flask --app stickyminutes try-claude`: one real summary of a sample meeting, from the command line.

It is the quick way to check that the API key, the model and the request
are right before trusting the website with them: it sends one demo sample
through the very same loop (summarize.ask_and_check) and prints what
happened. It costs real money (a few cents with Opus 5.5), and nothing is
saved in the database.
"""
import time
from types import SimpleNamespace

import click
from flask import current_app
from flask.cli import with_appcontext

from . import demo_samples, llm, pricing, summarize, transcripts
from .dates import local_today


@click.command("try-claude")
@click.option("--sample", "key", default="standup", type=click.Choice([spec["key"] for spec in demo_samples.SAMPLES]),
              help="Which demo meeting to summarize.")
@click.option("--model", default=pricing.DEFAULT_MODEL, type=click.Choice(list(pricing.MODELS)))
@click.option("--prompt", "version", default=summarize.PROMPT_VERSION, help="The prompt version, like v1 or v2.")
@with_appcontext
def try_claude_command(key, model, version):
    """Summarize one demo meeting with the real Claude and print the tries, problems and cost."""
    app = current_app._get_current_object()
    client = llm.client_for(app)
    if client.practice:
        raise click.ClickException("There is no ANTHROPIC_API_KEY, so this would only use practice notes. "
                                   "Put the key in .env first.")
    spec = next(spec for spec in demo_samples.SAMPLES if spec["key"] == key)
    parsed = transcripts.parse(spec["transcript"], spec["kind"])
    meeting = SimpleNamespace(title=spec["title"], title_from_user=True, meeting_date=local_today("Asia/Manila"),
                              speakers=parsed.speakers)
    system = summarize.system_blocks(version)
    messages = summarize.build_messages(meeting, parsed.lines)
    try:
        tokens = client.count_tokens(model, system, messages)
    except llm.LLMError as error:
        raise click.ClickException(error.message) from error
    click.echo(f"{spec['title']}: {len(parsed.lines)} lines, {tokens:,} input tokens, model {model}, prompt {version}.")
    replies, began = [], time.perf_counter()

    def on_checked(attempt, problems):
        click.echo(f"  Try {attempt}: " + ("passed every check." if not problems else f"{len(problems)} problem(s):"))
        for problem in problems:
            click.echo(f"    - [{problem.layer}] {problem}")

    outcome = summarize.ask_and_check(client, model, llm.EFFORT, system, messages, parsed.lines, meeting,
                                      on_reply=lambda reply, attempt: replies.append(reply), on_checked=on_checked)
    seconds = time.perf_counter() - began
    cost = sum(reply.cost_micros() for reply in replies)
    usage = lambda field: sum(getattr(reply, field) for reply in replies)  # noqa: E731
    click.echo(f"Tokens: {usage('input_tokens'):,} in, {usage('output_tokens'):,} out, "
               f"cache {usage('cache_write'):,} written / {usage('cache_read'):,} read.")
    click.echo(f"Cost: {pricing.dollars(cost)}. Time: {seconds:.1f} s. Answered by: {', '.join(sorted({r.model for r in replies})) or '-'}.")
    if outcome.error is not None:
        raise click.ClickException(f"[{outcome.error.code}] {outcome.error.message}")
    notes = outcome.notes
    if notes is None:
        raise click.ClickException("No answer had the right shape.")
    click.echo(f"\n{notes.title}\n{notes.overview}")
    for heading, entries in (("Decisions", notes.decisions), ("Action items", notes.action_items)):
        click.echo(f"\n{heading}:")
        for entry in entries:
            extra = f" ({entry.owner or 'unassigned'}, due {entry.due_date or entry.due_phrase or '-'})" if heading == "Action items" else ""
            click.echo(f"  - {getattr(entry, 'text', None) or entry.task}{extra}")


def init_app(app):
    app.cli.add_command(try_claude_command)
