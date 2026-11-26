"""Draw the app's PNG icons from stickyminutes/static/icons/logo.svg (the two sticky notes).

Playwright isn't in this project's .venv; borrow the one in expense_tracker:

    ..\\expense_tracker\\.venv\\Scripts\\python docs\\make_icons.py

- icon-32.png, icon-192.png, icon-512.png: the notes on a see-through background (browser tabs, Android)
- apple-touch-icon.png (180): the notes on the warm board colour, because an iPhone fills
  a see-through background with black
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ICONS = Path(__file__).resolve().parent.parent / "stickyminutes" / "static" / "icons"
SVG = (ICONS / "logo.svg").read_text(encoding="utf-8")
BOARD = "#f7f3ea"

PAGE = """<!doctype html><html><head><style>
html, body {{ margin: 0; background: {background}; }}
div {{ width: {size}px; height: {size}px; display: grid; place-items: center; }}
svg {{ width: {inner}px; height: {inner}px; display: block; }}
</style></head><body><div>{svg}</div></body></html>"""


def draw(page, name, size, inner, background="transparent"):
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(PAGE.format(background=background, size=size, inner=inner, svg=SVG))
    page.screenshot(path=str(ICONS / name), omit_background=background == "transparent",
                    clip={"x": 0, "y": 0, "width": size, "height": size})
    print("drew", name)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    page = browser.new_page(device_scale_factor=1)
    draw(page, "icon-32.png", 32, 32)
    draw(page, "icon-192.png", 192, 184)
    draw(page, "icon-512.png", 512, 490)
    draw(page, "apple-touch-icon.png", 180, 140, BOARD)
    browser.close()
