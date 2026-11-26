"""Reading transcripts: pasted text, Zoom / Teams / Google Meet exports, .srt and .docx."""
import io

import pytest

from stickyminutes import transcripts
from stickyminutes.transcripts import TranscriptProblem

ZOOM_VTT = """WEBVTT

1
00:00:01.120 --> 00:00:04.500
Maria Santos: Good morning, everyone. Let's start with the launch.

2
00:00:04.500 --> 00:00:07.900
Maria Santos: We said the 15th last week.

3
00:00:08.000 --> 00:00:12.300
Ben Cruz: I think we can still make the 15th if design is done by Friday.

4
00:00:12.400 --> 00:00:15.000
Ana Reyes: Design will be done Thursday.
"""

TEAMS_VTT = """WEBVTT

0f8b1e2a-1/12-0
00:00:02.140 --> 00:00:05.380
<v Maria Santos>Okay, so the budget for the trade fair.</v>

0f8b1e2a-1/18-0
00:00:05.900 --> 00:00:09.210
<v Ben Cruz>We have thirty thousand pesos left, enough for the booth.</v>
"""

SRT = """1
00:00:01,000 --> 00:00:03,000
Maria: Who is calling the supplier?

2
00:00:03,500 --> 00:00:06,000
Ben: I will call them tomorrow morning about the cups.
"""

PASTED = """[00:00:05] Maria Santos: Good morning. First, the newsletter.
[00:00:20] Ben Cruz: It goes out on Monday. I still need the photos from Ana.
Ana Reyes: I'll send them today.
And the captions too.
So here's the thing: we need a final headline.
"""

GOOGLE_MEET_TEXT = """Maria Santos 00:00:03
Good morning, team, let's look at the sales numbers.
Ben Cruz 00:01:10
Sales were up ten percent in October, mostly from the new blend.
"""


def test_zoom_vtt_joins_a_speakers_cues_and_keeps_the_time():
    found = transcripts.parse(ZOOM_VTT, "vtt")
    assert [(line.n, line.speaker, line.at) for line in found.lines] == [
        (1, "Maria Santos", "00:00:01"), (2, "Ben Cruz", "00:00:08"), (3, "Ana Reyes", "00:00:12")]
    assert found.lines[0].text == "Good morning, everyone. Let's start with the launch. We said the 15th last week."
    assert found.speakers == ["Maria Santos", "Ben Cruz", "Ana Reyes"]


def test_teams_vtt_reads_the_voice_tags():
    found = transcripts.parse(TEAMS_VTT, "vtt")
    assert [line.speaker for line in found.lines] == ["Maria Santos", "Ben Cruz"]
    assert "<" not in found.lines[0].text and found.lines[1].text.startswith("We have thirty thousand")


def test_srt_subtitles():
    found = transcripts.parse(SRT, "srt")
    assert [(line.speaker, line.at) for line in found.lines] == [("Maria", "00:00:01"), ("Ben", "00:00:03")]


def test_pasted_text_with_times_and_lines_without_a_name():
    found = transcripts.parse(PASTED)
    assert [(line.speaker, line.at) for line in found.lines] == [
        ("Maria Santos", "00:00:05"), ("Ben Cruz", "00:00:20"), ("Ana Reyes", None), ("Ana Reyes", None), ("Ana Reyes", None)]
    # "So here's the thing" is not a person.
    assert found.lines[4].text == "So here's the thing: we need a final headline."


def test_google_meet_text_with_the_name_and_time_on_their_own_line():
    found = transcripts.parse(GOOGLE_MEET_TEXT, "txt")
    assert [(line.speaker, line.at) for line in found.lines] == [("Maria Santos", "00:00:03"), ("Ben Cruz", "00:01:10")]
    assert found.lines[1].text.startswith("Sales were up ten percent")


def test_pasted_vtt_is_read_as_vtt():
    found = transcripts.parse(ZOOM_VTT, "paste")
    assert found.lines[1].speaker == "Ben Cruz"


def test_a_docx_upload():
    from docx import Document
    document = Document()
    for paragraph in ("Maria Santos: Let's agree on the new opening hours for the shop.",
                      "Ben Cruz: Seven in the morning to eight at night, every day except Sunday."):
        document.add_paragraph(paragraph)
    data = io.BytesIO()
    document.save(data)
    found = transcripts.read_upload("Planning.docx", data.getvalue())
    assert found.kind == "docx" and [line.speaker for line in found.lines] == ["Maria Santos", "Ben Cruz"]


def test_windows_text_files_are_read():
    data = "Maria: Café meeting about the new menu and the prices for next month.\r\nBen: Okay, fine with me.".encode("cp1252")
    found = transcripts.read_upload("notes.txt", data)
    assert found.lines[0].text.startswith("Café meeting")


def test_a_utf8_bom_is_dropped():
    data = "﻿Maria: Good morning, everyone, let's look at the plan for the week ahead together.".encode("utf-8")
    assert transcripts.read_upload("notes.txt", data).lines[0].speaker == "Maria"


@pytest.mark.parametrize("filename, data, words", [
    ("audio.mp3", b"ID3...", "Upload a .txt, .vtt, .srt or .docx"),
    ("notes.txt", b"", "empty"),
    ("notes.txt", b"\x00\x01\x02binary", "isn't text"),
    ("broken.docx", b"not really a zip", "couldn't be opened"),
    ("notes.txt", b"Maria: Hi.", "too short"),
])
def test_files_we_cant_use_say_why(filename, data, words):
    with pytest.raises(TranscriptProblem, match=words):
        transcripts.read_upload(filename, data)


def test_a_transcript_too_long_is_refused():
    huge = "\n".join(f"Maria: {'word ' * 60}" for _ in range(1500))
    with pytest.raises(TranscriptProblem, match="too long"):
        transcripts.parse(huge)


def test_the_numbered_text_claude_reads():
    found = transcripts.parse(SRT, "srt")
    assert transcripts.numbered(found.lines).splitlines()[1] == "[2] Ben (00:00:03): I will call them tomorrow morning about the cups."
