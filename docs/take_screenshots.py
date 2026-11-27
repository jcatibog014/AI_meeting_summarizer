r"""Take the README's pictures (docs/screenshots/), all from Try the demo.

Start the app first, in its own window (--debug: the demo limit is off, and templates are
read fresh), and let it run:

    cd C:\Users\USER\Documents\Workspace\AI_meeting_summarizer
    .venv\Scripts\flask --app stickyminutes run --debug --port 5016

Then, in a second window (Playwright isn't in requirements.txt: borrow another project's):

    cd C:\Users\USER\Documents\Workspace\AI_meeting_summarizer
    ..\expense_tracker\.venv\Scripts\python docs\take_screenshots.py

Every picture is the demo's sample data. tests/test_readme.py checks that the README shows each
picture in docs/screenshots/, and nothing else.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5016"
OUT = Path(__file__).parent / "screenshots"
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


def shot(page, name, full=False):
    time.sleep(0.4)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("saved", name)


def start_demo(page):
    page.goto(BASE + "/login")
    page.click("text=Try the demo")
    page.wait_for_load_state("networkidle")
    close_toasts(page)


def close_toasts(page):
    for close in page.locator("[data-toast-close]").all():
        if close.is_visible():
            close.click()


def open_meeting(page, title):
    page.goto(BASE + "/meetings")
    page.click(f".meeting-card >> text={title}")
    page.wait_for_load_state("networkidle")
    close_toasts(page)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")

        page = browser.new_page(viewport=DESKTOP, color_scheme="light")
        page.goto(BASE + "/login")
        shot(page, "login")
        start_demo(page)
        shot(page, "meetings")

        open_meeting(page, "Monday Stand-up")
        shot(page, "meeting")
        # Proof: open a decision's proof and light up its transcript line.
        note = page.locator(".column-blue .note").first
        note.locator("summary").click()
        note.locator("[data-line-link]").first.click()
        time.sleep(0.6)
        note.scroll_into_view_if_needed()
        page.evaluate("window.scrollTo(0, 0)")
        shot(page, "proof")
        page.locator("#transcript").scroll_into_view_if_needed()
        page.locator(".lines li.is-lit").scroll_into_view_if_needed()
        shot(page, "transcript-line")

        open_meeting(page, "Sprint Planning: Loyalty Points")
        shot(page, "needs-review")
        page.locator(".note.is-flagged a[aria-label='Edit']").click()
        page.wait_for_load_state("networkidle")
        shot(page, "edit-note")

        open_meeting(page, "Wholesale Call with Café Rosa")
        page.locator("#export").scroll_into_view_if_needed()
        shot(page, "export")
        share = page.input_value("#share-url")
        page.goto(page.url.split("#")[0] + "/email")
        shot(page, "email")

        page.goto(BASE + "/meetings/new")
        shot(page, "new-meeting")
        page.goto(BASE + "/actions")
        shot(page, "actions")
        page.goto(BASE + "/actions?tab=overdue")
        shot(page, "actions-overdue")

        page.goto(BASE + "/lab")
        shot(page, "lab")
        page.click("table a >> text=Wholesale Call with Café Rosa")
        page.wait_for_load_state("networkidle")
        shot(page, "lab-run")
        page.goto(BASE + "/lab/problems")
        shot(page, "lab-problems")
        page.goto(BASE + "/lab/tests")
        shot(page, "lab-tests")
        page.locator(".compare-card table a").last.click()
        page.wait_for_load_state("networkidle")
        shot(page, "lab-test-run")
        page.goto(BASE + "/settings")
        shot(page, "settings")

        visitor = browser.new_page(viewport=DESKTOP)
        visitor.goto(share)
        shot(visitor, "shared", full=True)
        visitor.close()

        dark = browser.new_page(viewport=DESKTOP, color_scheme="dark")
        start_demo(dark)
        open_meeting(dark, "October Retro")
        shot(dark, "dark-meeting")
        dark.close()

        phone = browser.new_page(viewport=PHONE, color_scheme="light", has_touch=True, is_mobile=True)
        start_demo(phone)
        shot(phone, "phone-meetings")
        open_meeting(phone, "Monday Stand-up")
        shot(phone, "phone-meeting")
        phone.goto(BASE + "/actions")
        shot(phone, "phone-actions")
        phone.close()
        browser.close()


if __name__ == "__main__":
    main()
