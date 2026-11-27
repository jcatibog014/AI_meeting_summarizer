"""The sticky notes look: every page wears it, dark mode matches itself, and the strict CSP holds."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import text

ROOT = Path(__file__).parent.parent / "stickyminutes"
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def luminance(hex_colour):
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def block(pattern):
    found = re.search(pattern, CSS, re.S).group(1)
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", found))


LIGHT = block(r"\n:root \{(.*?)\n\}")
DARK = block(r":root\[data-theme=\"dark\"\] \{(.*?)\n\}")


def test_dark_mode_is_defined_twice_with_the_same_tokens():
    device = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme=\"light\"\]\) \{(.*?)\n  \}", CSS, re.S).group(1)
    chosen = re.search(r":root\[data-theme=\"dark\"\] \{(.*?)\n\}", CSS, re.S).group(1)
    values = lambda part: sorted(" ".join(part.split()).split(";"))  # noqa: E731
    assert values(device) == values(chosen)


@pytest.mark.parametrize("theme", [LIGHT, DARK], ids=["light", "dark"])
def test_text_is_easy_to_read(theme):
    """4.5:1 for text (WCAG AA), on the page, on cards and on every note colour."""
    for ink, paper in [("--ink", "--board"), ("--ink", "--surface"), ("--muted", "--surface"), ("--muted", "--board"),
                       ("--link", "--surface"), ("--on-accent", "--accent"), ("--danger", "--surface"),
                       ("--ok", "--ok-soft"), ("--warn", "--warn-soft"), ("--danger", "--danger-soft"),
                       ("--link", "--accent-soft")]:
        assert contrast(theme[ink], theme[paper]) >= 4.5, (ink, paper)
    for note in ("green", "blue", "yellow", "pink"):
        assert contrast(theme["--note-ink"], theme[f"--note-{note}"]) >= 4.5, note
        assert contrast(theme["--note-muted"], theme[f"--note-{note}"]) >= 4.5, note


@pytest.mark.parametrize("theme", [LIGHT, DARK], ids=["light", "dark"])
def test_control_edges_can_be_seen(theme):
    """3:1 for the edges of text boxes and outlined buttons."""
    assert contrast(theme["--control-border"], theme["--surface"]) >= 3
    assert contrast(theme["--control-border"], theme["--board"]) >= 3


def test_the_login_shows_the_logo_name_and_demo(client):
    page = text(client.get("/login"))
    assert 'class="logo-mark"' in page and "Sticky Minutes" in page and "Try the demo" in page


def test_signed_in_pages_have_the_menu_and_the_marker_title(owner):
    client, _ = owner
    page = text(client.get("/meetings"))
    assert 'class="sidebar"' in page and 'class="marker"' in page


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_the_scripts_have_no_syntax_errors():
    for script in (ROOT / "static").glob("*.js"):
        result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_no_inline_styles_or_scripts():
    for path in (ROOT / "templates").glob("*.html"):
        source = path.read_text(encoding="utf-8")
        assert 'style="' not in source, path.name
        assert not re.search(r"<script(?![^>]*\bsrc=)", source), path.name
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "style=" not in script  # the strict CSP blocks inline styles


def test_every_page_sends_the_strict_security_headers(client):
    response = client.get("/login")
    policy = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in policy and "style-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert response.headers["X-Content-Type-Options"] == "nosniff"
