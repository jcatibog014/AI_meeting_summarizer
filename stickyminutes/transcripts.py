"""Reading a transcript into numbered lines: who spoke, when, and what they said.

Meetings come in a few shapes:

- **Pasted text** or a **.txt** file: "Maria Santos: Let's start.", maybe with a
  time in front ("[00:01:23] Maria: ...", "00:01:23 Maria: ...").
- **.vtt** (WebVTT), which Zoom, Google Meet and Teams all export. Zoom writes
  "Maria Santos: Hello" inside each cue; Teams writes "<v Maria Santos>Hello</v>".
- **.srt** (subtitles): numbered cues with "00:00:01,000 --> 00:00:04,000" times.
- **.docx**: a Word file with one paragraph per line, read like pasted text.

Every shape becomes the same list of `Line(n, speaker, at, text)`, numbered
from 1. Claude sees those numbers and must point at them as its evidence
("line 42"), and checks.py makes sure the quote really is on that line. So
the numbers must never change once the meeting is saved.

Video subtitles cut speech into short pieces (one sentence over three cues),
so a person's cues that follow each other are joined into one line, up to
MERGE_CHARS characters.
"""
import io
import re
from dataclasses import dataclass, field

MAX_BYTES = 2 * 1000 * 1000        # an upload (views also cap the request at 3 MB)
MAX_CHARS = 300_000                # about 75,000 tokens: a long day of meetings
MAX_LINES = 5000
MIN_WORDS = 12                     # fewer words than this isn't a meeting
MERGE_CHARS = 600
SPEAKER_MAX = 60
KINDS = {"paste": "Pasted text", "txt": "Text file", "vtt": "WebVTT (Zoom, Meet, Teams)",
         "srt": "Subtitles (.srt)", "docx": "Word document"}

TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"
CUE_TIME = re.compile(rf"^\s*({TIME})\s*-->\s*({TIME})")
# "Maria Santos: ...", at most 4 words and SPEAKER_MAX characters, starting with a capital or a digit-free word.
SPEAKER_LINE = re.compile(r"^(?P<speaker>[^\W\d_][\w.'’()&-]*(?: [\w.'’()&-]+){0,3}):\s+(?P<text>\S.*)$")
# A time in front: "[00:01:23]", "(1:05)", "00:01:23 -"
LEADING_TIME = re.compile(rf"^[\[(]?(?P<at>{TIME})[\])]?\s*[-–:]?\s+")
# "Maria Santos (00:01:23): ..." or "Maria Santos 00:01:23" (Otter, Google Meet text) on its own line
SPEAKER_WITH_TIME = re.compile(rf"^(?P<speaker>[^\W\d_][\w.'’-]*(?: [\w.'’-]+){{0,3}})\s+[\[(]?(?P<at>{TIME})[\])]?:?\s*(?P<text>.*)$")
VOICE_TAG = re.compile(r"<v(?:\.[\w.-]+)?\s+([^>]+)>")
ANY_TAG = re.compile(r"</?[^>]+>")
NOT_SPEAKERS = {"http", "https", "note", "notes", "webvtt", "agenda", "action", "re", "fw", "subject", "to", "from", "date", "time"}


class TranscriptProblem(ValueError):
    """Something a person must fix before the transcript can be used. The message says what."""


@dataclass
class Line:
    n: int
    speaker: str | None
    at: str | None
    text: str


@dataclass
class Parsed:
    kind: str
    lines: list[Line] = field(default_factory=list)

    @property
    def speakers(self):
        """Everyone who speaks, in the order they first do."""
        seen = []
        for line in self.lines:
            if line.speaker and line.speaker not in seen:
                seen.append(line.speaker)
        return seen

    @property
    def words(self):
        return sum(len(line.text.split()) for line in self.lines)

    @property
    def chars(self):
        return sum(len(line.text) for line in self.lines)


# ---------- Bytes to text ----------

def decode(data: bytes) -> str:
    """A file's bytes as text: UTF-8 (with or without the Windows BOM), else Windows-1252."""
    if b"\x00" in data[:4096]:
        raise TranscriptProblem("That file isn't text. Upload a .txt, .vtt, .srt or .docx transcript.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TranscriptProblem("We couldn't read the letters in that file. Save it as UTF-8 text and try again.")


def docx_text(data: bytes) -> str:
    from docx import Document
    try:
        document = Document(io.BytesIO(data))
    except Exception as error:  # python-docx raises several kinds for a broken file
        raise TranscriptProblem("That Word file couldn't be opened. Is it a real .docx?") from error
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def kind_of(filename):
    ending = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ending in ("txt", "vtt", "srt", "docx"):
        return ending
    raise TranscriptProblem("Upload a .txt, .vtt, .srt or .docx file (Zoom, Google Meet and Teams can all save one).")


# ---------- Text to lines ----------

NAME_PARTICLES = {"de", "del", "dela", "della", "da", "dos", "van", "von", "der", "la", "le", "bin", "binti", "al"}


def clean_speaker(name):
    """A speaker's name, or None if it doesn't look like one.

    Each word must start with a capital ("Maria Santos"), be a number ("Speaker 1")
    or be a small name word ("Juan dela Cruz"). That keeps "So here's the thing: ..."
    from being read as somebody called "So here's the thing"."""
    name = " ".join((name or "").split()).strip(" -:")
    if not name or len(name) > SPEAKER_MAX or name.lower() in NOT_SPEAKERS:
        return None
    for word in name.split():
        if not (word[0].isupper() or word.isdigit() or word.lower() in NAME_PARTICLES or word.startswith("(")):
            return None
    return name


def short_time(at):
    """'00:01:23.456' -> '00:01:23'; '1:05' -> '1:05'."""
    return re.split(r"[.,]", at)[0] if at else None


def split_speaker(text):
    """'Maria: Hello' -> ('Maria', 'Hello'); 'Just words' -> (None, 'Just words')."""
    match = SPEAKER_LINE.match(text)
    if match:
        speaker = clean_speaker(match["speaker"])
        if speaker:
            return speaker, match["text"].strip()
    return None, text


def parse_plain(text, kind="paste"):
    """Pasted text, .txt or .docx: one line per speaker turn."""
    lines = []
    pending = None  # a "Maria Santos 00:01:23" line whose words come on the next lines
    for raw in text.splitlines():
        raw = " ".join(raw.split())
        if not raw:
            continue
        at = None
        if timed := LEADING_TIME.match(raw):
            at, raw = short_time(timed["at"]), raw[timed.end():]
        speaker, words = split_speaker(raw)
        if speaker is None and (alone := SPEAKER_WITH_TIME.match(raw)) and clean_speaker(alone["speaker"]):
            speaker, at, words = clean_speaker(alone["speaker"]), short_time(alone["at"]), alone["text"].strip()
            if not words:
                pending = (speaker, at)
                continue
        if speaker is None and pending:
            speaker, at = pending
            pending = None
            _add(lines, speaker, at, words, merge=False)
            continue
        if speaker is None and lines:
            # A line with no name goes on with whoever spoke last (a long turn split in paragraphs).
            _add(lines, lines[-1].speaker, at, words, merge=False)
            continue
        _add(lines, speaker, at, words, merge=False)
    return Parsed(kind, lines)


def cues(text):
    """The cues of a .vtt or .srt file: (start time, text) pairs."""
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        rows = [row.strip() for row in block.strip().split("\n") if row.strip()]
        if not rows or rows[0].upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        for index, row in enumerate(rows):
            if match := CUE_TIME.match(row):
                words = " ".join(rows[index + 1:])
                if words:
                    yield short_time(match[1]), words
                break


def parse_cues(text, kind):
    """A .vtt or .srt file: each cue's speaker from "<v Name>" (Teams) or "Name:" (Zoom)."""
    lines = []
    for at, words in cues(text):
        speaker = None
        if voice := VOICE_TAG.search(words):
            speaker = clean_speaker(voice[1])
        words = " ".join(ANY_TAG.sub(" ", words).split())
        if speaker is None:
            speaker, words = split_speaker(words)
        if words:
            _add(lines, speaker, at, words, merge=True)
    return Parsed(kind, lines)


def _add(lines, speaker, at, words, merge):
    words = " ".join(words.split())
    if not words:
        return
    last = lines[-1] if lines else None
    if merge and last and last.speaker == speaker and len(last.text) + len(words) < MERGE_CHARS:
        last.text = f"{last.text} {words}"
        return
    lines.append(Line(len(lines) + 1, speaker, at, words))


def looks_like_cues(text):
    """Pasted or .txt text that is really a .vtt / .srt (it has "00:00:01.000 --> 00:00:04.000" lines)."""
    return any(CUE_TIME.match(row) for row in (text or "").splitlines()[:50])


def parse(text, kind="paste"):
    if kind in ("vtt", "srt") or (kind in ("paste", "txt") and looks_like_cues(text)):
        found = parse_cues(text, kind)
    else:
        found = parse_plain(text, kind)
    check(found)
    return found


def read_upload(filename, data):
    """An uploaded file's name and bytes -> Parsed (or TranscriptProblem)."""
    kind = kind_of(filename)
    if len(data) > MAX_BYTES:
        raise TranscriptProblem("That file is too big. A transcript can be at most 2 MB.")
    if not data.strip():
        raise TranscriptProblem("That file is empty.")
    text = docx_text(data) if kind == "docx" else decode(data)
    return parse(text, kind)


# ---------- Is it a meeting we can use? ----------

def check(found):
    if not found.lines or found.words < MIN_WORDS:
        raise TranscriptProblem(f"That's too short to summarize. A transcript needs at least {MIN_WORDS} words.")
    if found.chars > MAX_CHARS:
        raise TranscriptProblem(f"That transcript is too long ({found.chars:,} characters). "
                                f"The most is {MAX_CHARS:,}: split the meeting in two.")
    if len(found.lines) > MAX_LINES:
        raise TranscriptProblem(f"That transcript has {len(found.lines):,} lines. The most is {MAX_LINES:,}.")


def estimate_tokens(chars):
    """A rough count before asking the API (about 4 characters a token in English).
    llm.count_tokens() asks Claude for the real number before a summary runs."""
    return chars // 4 + 1


def numbered(lines):
    """The transcript the way Claude reads it: '[12] Maria Santos (00:03:10): We agreed ...'."""
    out = []
    for line in lines:
        who = line.speaker or "Unknown speaker"
        when = f" ({line.at})" if line.at else ""
        out.append(f"[{line.n}] {who}{when}: {line.text}")
    return "\n".join(out)
