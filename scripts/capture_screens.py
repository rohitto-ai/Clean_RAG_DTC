"""
Phase 10.4 — capture the demo screenshots for the report.

    PYTHONPATH=src .venv/bin/python scripts/capture_screens.py

Starts uvicorn on a free port, drives the real UI in headless Chromium at
1280x720 (the projector size the UI is designed for) and writes
docs/report/img/phase10_4_*.png.

Playwright is a DEV-ONLY dependency for this script - it is deliberately NOT in
requirements.txt, because the service and the pipeline never need a browser:

    .venv/bin/pip install playwright && .venv/bin/playwright install chromium
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request

OUT_DIR = "docs/report/img"
VIEWPORT = {"width": 1280, "height": 720}
SHOTS = []


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(base, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def shoot(page, name, note):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = f"{OUT_DIR}/phase10_4_{name}.png"
    page.screenshot(path=path)
    SHOTS.append((path, note))
    print(f"  wrote {path}  — {note}")


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PYTHONPATH": "src", "ANONYMIZED_TELEMETRY": "False"}
    proc = subprocess.Popen(
        [".venv/bin/uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_up(base):
            print("server did not come up", file=sys.stderr)
            return 1
        print(f"server up on {base}")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_selector("#fleet-body table", timeout=60_000)

            # 1. fleet with a replay running
            page.fill("#r-rows", "60")
            page.fill("#r-tick", "1")
            page.click("#r-start")
            page.wait_for_timeout(2500)
            page.wait_for_selector("#replay-live:not([hidden])", timeout=20_000)
            shoot(page, "fleet_replay", "Fleet tab with the replay running (LIVE, partial rows)")

            # severity-filtered fleet
            page.select_option("#f-sev", "CRITICAL")
            page.wait_for_timeout(1200)
            shoot(page, "fleet_critical", "Fleet filtered to CRITICAL severity")
            page.click("#r-reset")
            page.wait_for_timeout(1200)
            page.select_option("#f-sev", "")
            page.wait_for_timeout(1200)

            # 2. an ADVISORY vehicle
            page.click("#tab-vehicle")
            page.fill("#v-id", "DEMO-MAT-0001")
            page.click("#v-go")
            page.wait_for_selector(".fix", timeout=60_000)
            shoot(page, "vehicle_advisory", "Vehicle tab: ADVISORY with fix block and cost panel")

            # 3. an AMBIGUOUS vehicle
            page.fill("#v-id", "DEMO-MAT-0004")
            page.click("#v-go")
            page.wait_for_selector(".notice.info", timeout=60_000)
            shoot(page, "vehicle_ambiguous", "Vehicle tab: AMBIGUOUS key, not auto-advised")

            # refusal: a mapped code the manual does not contain
            page.fill("#v-id", "DEMO-MAT-0008")
            page.click("#v-go")
            page.wait_for_selector(".notice.bad", timeout=60_000)
            shoot(page, "vehicle_refused", "Vehicle tab: mapped code absent from the manual, refused")

            # 4. the transposition MISMATCH
            page.fill("#v-id", "DEMO-MAT-0011")
            page.click("#v-go")
            page.wait_for_selector("#v-code", timeout=60_000)
            page.fill("#v-code", "P0100-00")
            page.click("text=Verify code")
            page.wait_for_selector("#verify-out .notice.bad", timeout=60_000)
            page.eval_on_selector("#verify-out", "d => d.scrollIntoView()")
            page.wait_for_timeout(500)
            shoot(page, "verify_mismatch", "Technician typed P0100-00; telemetry says P1000-00")

            # 5. a symptom answer
            page.click("#tab-symptom")
            page.fill("#s-q", "coolant gauge stuck at the bottom")
            page.click("#s-go")
            page.wait_for_selector("#symptom-body .fix", timeout=120_000)
            shoot(page, "symptom_answer", "Service query: top-3 DTCs with fix blocks")

            # the Why panel, expanded. Run once WITH the AI summary so the panel shows
            # both badge kinds: RULE for every deterministic step, AI for the phrasing.
            page.check("#s-sum")
            page.click("#s-go")
            page.wait_for_selector("#symptom-body .tag.AI", timeout=300_000)
            why = page.locator("details.why").last
            why.evaluate("d => { d.open = true; }")
            page.wait_for_timeout(300)
            # centre the step list of THAT panel, so both badge kinds (RULE, and the
            # single AI step) sit inside the 720px frame
            why.locator(".steps").evaluate("n => n.scrollIntoView({block: 'center'})")
            page.wait_for_timeout(700)
            shoot(page, "why_panel", "Why this answer? — retrieval ranks, gate, RULE/AI steps")
            page.uncheck("#s-sum")

            # 6. a refusal
            page.fill("#s-q", "what is the warranty period on this engine")
            page.click("#s-go")
            page.wait_for_selector("#symptom-body .notice.bad", timeout=60_000)
            shoot(page, "symptom_refusal", "Service query refused as out of scope, with the reason")

            # 7. the audit view
            page.click("#tab-audit")
            page.wait_for_selector("#audit-body table", timeout=60_000)
            shoot(page, "audit", "Audit tab: endpoint, decision, codes, latency per request")

            # 8. the presets menu
            page.click("#tab-fleet")
            page.click("#presets-btn")
            page.wait_for_timeout(500)
            shoot(page, "presets", "Demo presets menu built from /scenarios")

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\n{len(SHOTS)} screenshots written to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
