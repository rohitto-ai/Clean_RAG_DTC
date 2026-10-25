"""
Phase 10.5b - the action behind the Run and Debug green play button.

    PYTHONPATH=src .venv/bin/python scripts/open_demo.py [--port 8000] [--wait 240]

The "Demo: start" task (preLaunchTask) brings the service up in its own terminal.
This script then confirms it is serving and prints where to go, so the play button
ends with a URL rather than with a process that may or may not be ready. It never
starts or stops anything itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request


def health(base, timeout=3):
    with urllib.request.urlopen(base + "/health", timeout=timeout) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--wait", type=float, default=240.0,
                    help="seconds to wait for the service to become healthy")
    a = ap.parse_args()

    base = f"http://127.0.0.1:{a.port}"
    deadline = time.time() + a.wait
    h = None
    while time.time() < deadline:
        try:
            h = health(base)
            if h.get("status") == "ok":
                break
        except Exception:
            pass
        time.sleep(1)
        h = None

    if not h:
        print(f"The demo did not become healthy on {base} within {a.wait:.0f}s.")
        print("Look at the 'Demo: start' terminal, or run:  ./run.sh demo --check")
        return 1

    cs = os.environ.get("CODESPACE_NAME")
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    print("=" * 60)
    print("  DEMO READY")
    print(f"     local      {base}/")
    if cs:
        print(f"     codespace  https://{cs}-{a.port}.{domain}/")
        print(f"                Ports panel -> {a.port} -> Visibility: Public for the")
        print("                demo, back to Private afterwards")
    print(f"     records {h['counts']['records']} | vectors {h['counts']['vectors']} | "
          f"rows {h['counts']['log_rows_in_scope']}")
    print(f"     startup {h['startup_seconds']}s | determinism hash {h['determinism_hash']}")
    print("     stop       ./run.sh demo --stop   (or the 'Demo: stop' task)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
