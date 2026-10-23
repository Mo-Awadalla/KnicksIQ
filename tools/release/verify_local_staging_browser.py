"""Real Chromium checks for Docker staging; retain screenshots and a browser trace."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from verify_local_staging import local_origin, require


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-origin", default="http://127.0.0.1:18080")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    origin = local_origin(args.web_origin)
    args.output.mkdir(parents=True, exist_ok=False)
    args.output.chmod(0o700)
    receipt = {
        "started_at": datetime.now(UTC).isoformat(),
        "origin": origin,
        "scope": "Real Docker HTTP/browser integration with deterministic answers",
        "status": "failed",
        "checks": [],
        "responses": [],
        "page_errors": [],
        "api_errors": [],
        "blocked_external_urls": [],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)

        def local_only(route):
            url = route.request.url
            if urlsplit(url).netloc == urlsplit(origin).netloc:
                route.continue_()
            else:
                receipt["blocked_external_urls"].append(url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: receipt["page_errors"].append(str(error)))
        page.on(
            "response",
            lambda response: (
                receipt["api_errors"].append({"url": response.url, "status": response.status})
                if "/api/" in response.url and response.status >= 400
                else None
            ),
        )
        try:
            for route in ("games", "reports"):
                page.goto(origin + "/" + route, wait_until="networkidle")
                link = page.locator(f'main a[href^="/{route}/"]').first
                expect(link).to_be_visible()
                href = link.get_attribute("href")
                link.click()
                page.wait_for_url(origin + href)
                page.wait_for_load_state("networkidle")
                expect(page.get_by_role("heading", level=1)).to_be_visible()
                page.screenshot(path=str(args.output / f"{route}-detail.png"), full_page=True)
                receipt["checks"].append({"navigation": route, "detail": href})

            page.goto(origin + "/analyst", wait_until="networkidle")
            questions = [
                "What was the Knicks score against Cleveland on 2025-10-22?",
                "How did JB play in that game?",
            ]
            for revision, question in enumerate(questions, start=1):
                box = page.get_by_role("textbox", name="Ask a season question")
                expect(box).to_be_enabled()
                box.fill(question)
                with page.expect_response(
                    lambda response: (
                        response.url.endswith("/api/analysis/query")
                        and response.request.method == "POST"
                    )
                ) as event:
                    box.press("Enter")
                response = event.value
                require(response.status == 200, "Browser analysis request failed")
                body = response.json()
                receipt["responses"].append(body)
                require(body.get("state_committed") is True, "Browser turn did not commit")
                require(body.get("revision") == revision, "Browser session revision changed")
                require(bool(body.get("citations")), "Browser answer has no citations")
                require(body.get("llm_validated") is False, "Unexpected model validation")
                if revision == 1:
                    require("119" in body["answer"] and "111" in body["answer"], "Wrong score")
                else:
                    require("Brunson" in body["answer"], "Follow-up lost player/game context")
                expect(page.get_by_text(body["answer"], exact=True).first).to_be_visible()
            page.reload(wait_until="networkidle")
            for question in questions:
                expect(page.get_by_text(question, exact=True)).to_be_visible()
            for body in receipt["responses"]:
                expect(page.get_by_text(body["answer"], exact=True).first).to_be_visible()
            receipt["checks"].append("Two committed turns and conversation retained after reload")
            page.screenshot(path=str(args.output / "analyst-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.output / "analyst-mobile.png"), full_page=True)
            require(not receipt["page_errors"], "Browser emitted a JavaScript error")
            require(not receipt["api_errors"], "Browser API request returned an error")
            receipt["status"] = "passed"
        except Exception as error:
            receipt["error"] = f"{type(error).__name__}: {error}"
            page.screenshot(path=str(args.output / "failure.png"), full_page=True)
        finally:
            context.tracing.stop(path=str(args.output / "trace.zip"))
            browser.close()
            receipt["finished_at"] = datetime.now(UTC).isoformat()
            path = args.output / "verification.json"
            with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                json.dump(receipt, output, indent=2)
                output.write("\n")
    print(json.dumps({"status": receipt["status"], "artifact": str(path.resolve())}))
    if receipt["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
