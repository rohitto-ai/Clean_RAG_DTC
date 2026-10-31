"""
Phase 13.2 — screenshots of both UIs, desktop and tablet.

    ./run.sh demo                                  # server must be up
    PYTHONPATH=src .venv/bin/python scripts/capture_ui_v2.py

Dev-only: Playwright is NOT in requirements.txt (same as scripts/capture_screens.py
from Phase 10.4). Writes docs/report/img/ui_v2/.
"""
from __future__ import annotations

import os
import sys

BASE = os.environ.get("DEMO_BASE", "http://127.0.0.1:8000")
OUT = "docs/report/img/ui_v2"
DESKTOP = {"width": 1280, "height": 800}
TABLET = {"width": 834, "height": 1112}


def shots(page, prefix, v2):
    def snap(name):
        page.wait_for_timeout(900)
        page.screenshot(path=f"{OUT}/{prefix}_{name}.png", full_page=False)
        print(f"  wrote {OUT}/{prefix}_{name}.png")

    page.goto(f"{BASE}/v2/" if v2 else f"{BASE}/", wait_until="networkidle")
    page.wait_for_timeout(1500)
    snap("fleet")

    page.click("button[data-view='symptom']" if v2 else "#tab-symptom")
    page.wait_for_timeout(500)
    page.fill("#s-q", "coolant gauge stuck at the bottom")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    snap("symptom")

    page.fill("#s-q", "no issue, the vehicle is running fine")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)
    snap("conversational")

    page.fill("#s-q", "P-10")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)
    snap("incomplete_code")

    if v2:
        page.click("button[data-view='vehicle']")
        page.wait_for_timeout(400)
        page.fill("#v-id", "DEMO-MAT-0001")
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        snap("vehicle")


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for label, size in (("desktop", DESKTOP), ("tablet", TABLET)):
            for ui, v2 in (("v2", True), ("classic", False)):
                ctx = b.new_context(viewport=size, device_scale_factor=1)
                page = ctx.new_page()
                print(f"[{ui} {label}]")
                try:
                    shots(page, f"{ui}_{label}", v2)
                except Exception as e:                       # a missing view is not fatal
                    print(f"  skipped some shots: {e.__class__.__name__}: {e}")
                ctx.close()
        # dark mode, v2 only
        ctx = b.new_context(viewport=DESKTOP, color_scheme="dark")
        page = ctx.new_page()
        page.goto(f"{BASE}/v2/", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{OUT}/v2_desktop_fleet_dark.png")
        print(f"  wrote {OUT}/v2_desktop_fleet_dark.png")
        ctx.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
