"""Serves the app on the demo dataset, or takes one screenshot of it, for the README.

The app reads the fake GLPI API fed by ``tests/demo_glpi.py``, with its clock stopped at the dataset's date, so
nothing real is shown and shots taken months apart show the same data. Run from the repo root::

    .venv\\Scripts\\python.exe scripts/demo.py                  # browse it at http://127.0.0.1:8001, Ctrl+C stops
    .venv\\Scripts\\python.exe scripts/demo.py shot docs/screenshots/risks.png --tab "Risk analysis"
    .venv\\Scripts\\python.exe scripts/demo.py shot docs/screenshots/list.png --link "#list=high-priority" --element "#list"

Take a new shot only when a change has altered that screen: each one is a binary file in git for good, and a
retake of an unchanged screen can still differ by a few pixels.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tests")]

import httpx  # noqa: E402 - after the path set-up, like the app's own imports
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from demo_glpi import NOW, demo_dataset  # noqa: E402
from fake_glpi import FakeGlpi  # noqa: E402
from live_app import serve  # noqa: E402

PORT = 8001


def shoot(browser, base_url, out, tab=None, link=None, element=None, theme="light", width=1280, height=800):
    """Takes one screenshot of the page.

    Args:
        browser: A Playwright ``Browser``.
        base_url: The app, already refreshed.
        out: The PNG to write; its folder is created if need be.
        tab: The tab to show first, by its name, e.g. ``"Risk analysis"``.
        link: A link to open after that, e.g. ``"#list=high-priority"``, ``"#search=vpn"`` or ``"#explore=..."``.
        element: A CSS selector to crop to, e.g. ``"#list"`` for the drill-down dialog; else the whole page.
        theme: ``"light"`` or ``"dark"``; the browser reports it as the system's colour scheme.
        width: The window's width in pixels.
        height: The window's height; the whole page is shot unless ``element`` crops it.
    """
    context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                  reduced_motion="reduce")
    page = context.new_page()
    page.goto(base_url + "/")
    expect(page.locator("#updated")).to_contain_text("Updated")
    if tab:
        page.get_by_role("tab", name=tab).click()
    if link:
        page.goto(base_url + "/" + link)
        expect(page.locator("#updated")).to_contain_text("Updated")
    page.wait_for_load_state("networkidle")          # the explorer and search fetch their data after the snapshot
    if link and link.startswith(("#list=", "#search=")):
        expect(page.locator("#list-rows tr").first).to_be_visible()
    # No hover tooltip, highlight or focus ring left over from a click or the dialog opening.
    page.mouse.move(0, 0)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    out.parent.mkdir(parents=True, exist_ok=True)
    if element:
        page.locator(element).screenshot(path=out, animations="disabled", caret="hide")
    else:
        page.screenshot(path=out, full_page=True, animations="disabled", caret="hide")
    context.close()


def main():
    """Serves the demo until Ctrl+C, or takes the one screenshot asked for."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    shot = sub.add_parser("shot", help="take one screenshot")
    shot.add_argument("out", type=Path, help="the PNG to write, e.g. docs/screenshots/risks.png")
    shot.add_argument("--tab", help='the tab to show, e.g. "Record explorer"')
    shot.add_argument("--link", help='a link to open, e.g. "#list=high-priority" or "#search=vpn&closed=1"')
    shot.add_argument("--element", help='crop to this CSS selector, e.g. "#list" for the list dialog')
    shot.add_argument("--theme", choices=("light", "dark"), default="light")
    shot.add_argument("--width", type=int, default=1280)
    shot.add_argument("--height", type=int, default=800)
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)     # not a line per fake GLPI request

    with serve(FakeGlpi(demo_dataset()), port=0 if args.command else PORT, now=NOW) as base_url:
        r = httpx.post(base_url + "/api/refresh", timeout=30)
        r.raise_for_status()
        if r.json()["error"]:
            sys.exit(f"refresh failed: {r.json()['error']}")
        if not args.command:
            print(f"Demo GLPI dashboard at {base_url} - Ctrl+C to stop")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                return
        with sync_playwright() as p:
            browser = p.chromium.launch()
            shoot(browser, base_url, args.out, args.tab, args.link, args.element, args.theme, args.width,
                  args.height)
            browser.close()
        print(args.out)


if __name__ == "__main__":
    main()
