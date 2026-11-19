"""Browser test of the web app and the virtual board panel (headless Edge or Chrome).

Logs in, opens every page, checks each one renders its data, switches a relay from the
Control page, and fails on any JavaScript error or failed request. Saves a screenshot
per page.

    python scripts/ui_check.py --user NAME --password PASS [--server URL] [--board URL] [--shots DIR]

Needs: pip install playwright (uses the installed Edge/Chrome; no browser download).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = {
    # route: (selector, text it must eventually contain)
    "dashboard": ("#t-p", "kW"),
    "monitor": ("#t-month", "kWh"),
    "analysis": ("#a-e", "kWh"),
    "quality": ("#outages", ""),
    "control": ('[data-phase="R"] [data-state]', "O"),  # ON / OFF
    "insights": ("#bill", "units"),
    "account": ("#pw", ""),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--board", default="http://127.0.0.1:9000")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--shots", type=Path, default=Path("ui-shots"))
    ap.add_argument("--channel", default="msedge", help="msedge or chrome")
    args = ap.parse_args()
    args.shots.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252

    problems: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
        # Chromium logs every 4xx as "Failed to load resource"; expected refusals (409) aren't bugs.
        # Server errors are caught by the response handler below.
        page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                and problems.append(f"console error: {m.text}"))
        page.on("response", lambda r: r.status >= 500 and problems.append(f"HTTP {r.status} {r.url}"))
        page.on("dialog", lambda d: d.accept())  # confirm() before switching OFF

        def check(name: str, ok: bool, detail: str = "") -> None:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}")
            if not ok:
                problems.append(f"{name} {detail}")

        page.goto(f"{args.server}/app/#/login")
        page.fill("input[name=username]", args.user)
        page.fill("input[name=password]", args.password)
        page.click("button.primary")
        page.wait_for_url("**/#/dashboard", timeout=10_000)
        check("login lands on the dashboard", True)

        for route, (selector, must_contain) in PAGES.items():
            page.goto(f"{args.server}/app/#/{route}")
            try:
                page.wait_for_function(
                    "([sel, txt]) => { const el = document.querySelector(sel); return el && el.textContent.trim() "
                    "&& el.textContent.trim() !== '–' && !el.textContent.includes('Loading') && el.textContent.includes(txt); }",
                    arg=[selector, must_contain], timeout=15_000)
                text = page.text_content(selector).strip().replace("\n", " ")[:70]
                check(f"page {route} renders", True, text)
            except Exception:
                check(f"page {route} renders", False, f"{selector} never showed '{must_contain}'")
            if page.locator("text=Charts need Chart.js").count():
                check(f"charts load on {route}", False, "Chart.js missing")
            page.wait_for_timeout(1500)
            page.screenshot(path=args.shots / f"app-{route}.png", full_page=True)

        # Live push: the dashboard should say "live" (WebSocket), not "polling".
        page.goto(f"{args.server}/app/#/dashboard")
        page.wait_for_timeout(4000)
        check("dashboard receives live push", "live" in (page.text_content("#t-mode") or ""), page.text_content("#t-mode"))

        # Relay round trip through the UI: B off, state follows.
        page.goto(f"{args.server}/app/#/control")
        state_js = "document.querySelector('[data-phase=\"B\"] [data-state]').textContent.trim()"
        page.wait_for_function(f"['ON', 'OFF'].includes({state_js})", timeout=15_000)
        if page.evaluate(state_js) == "OFF":  # left off by an earlier run: wait out the lockout, switch on
            page.wait_for_function("!document.querySelector('[data-phase=\"B\"] [data-cmd=\"on\"]').disabled",
                                   timeout=200_000)
            page.click('[data-phase="B"] [data-cmd="on"]')
            page.wait_for_function(f"{state_js} === 'ON'", timeout=15_000)
        page.click('[data-phase="B"] [data-cmd="off"]')
        try:
            page.wait_for_function(f"{state_js} === 'OFF'", timeout=15_000)
            check("Control: switching B off updates the card", True,
                  page.text_content('[data-phase="B"] [data-reason]'))
        except Exception:
            check("Control: switching B off updates the card", False, page.text_content('[data-phase="B"]'))
        check("Control: ON is disabled during the minimum off-time",
              page.locator('[data-phase="B"] [data-cmd="on"]').is_disabled())
        page.screenshot(path=args.shots / "app-control-after.png", full_page=True)

        # The virtual board panel
        page.goto(args.board)
        page.wait_for_function("document.querySelector('#chip-fw').textContent.includes('reading SPI')", timeout=10_000)
        check("virtual board panel shows the firmware reading SPI", True)
        page.screenshot(path=args.shots / "board-panel.png", full_page=True)
        browser.close()

    unique = list(dict.fromkeys(problems))
    print("\n" + ("UI CHECK PASSED" if not unique else "UI CHECK FAILED:\n  " + "\n  ".join(unique)))
    return 1 if unique else 0


if __name__ == "__main__":
    sys.exit(main())
