"""Step 2 gate: drive the dashboard in replay mode and check rendering, behaviour and accessibility.

usage: python scripts/check_web.py [run=recordings/fixture.jsonl]
Serves web/ on a free port, screenshots go to state/checks/.
"""
import asyncio
import functools
import http.server
import json
import socket
import sys
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
RUN = sys.argv[1] if len(sys.argv) > 1 else "recordings/fixture.jsonl"
SHOTS = ROOT / "state" / "checks"
AXE = (ROOT / "vendor" / "axe.min.js").read_text()
fails: list[str] = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def serve() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(WEB))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port


def expected():
    ev = [json.loads(l) for l in (WEB / RUN).read_text().splitlines() if l.strip()]
    issues = {e["data"]["id"]: e["data"] for e in ev if e["type"] == "issue.detected"}
    status = {k: "detected" for k in issues}
    for e in ev:
        if e["type"] == "issue.status":
            status[e["data"]["id"]] = e["data"]["status"]
    scores = [e["data"]["value"] for e in ev if e["type"] == "score"]
    return {
        "score": str(scores[-1]) if scores else "–",
        "found": str(len(issues)),
        "hidden": str(sum(1 for i in issues.values() if i.get("source") != "axe")),
        "fixed": str(sum(1 for s in status.values() if s == "validated")),
        "human": str(sum(1 for s in status.values() if s == "needs_human")),
        "has_pr": any(e["type"] == "pr.ready" for e in ev),
        "outcome": ([e["data"]["result"] for e in ev if e["type"] == "outcome"] or [None])[-1],
        "eval": ([e["data"]["passed"] for e in ev if e["type"] == "eval"] or [None])[-1],
        "session": any(e["type"] == "run.started" and e["data"].get("session_id") for e in ev),
        "has_stmt": any(e["type"] == "document.written" and e["data"].get("name") == "accessibility-statement.md" for e in ev),
    }


async def axe(page, label):
    await page.add_script_tag(content=AXE)
    res = await page.evaluate("axe.run(document,{runOnly:['wcag2a','wcag2aa','wcag21a','wcag21aa']})")
    for v in res["violations"]:
        print("     ", v["id"], "-", v["help"], [n["target"] for n in v["nodes"]][:3])
    check(not res["violations"], f"axe: no WCAG violation ({label})")


async def main():
    port = serve()
    url = f"http://127.0.0.1:{port}/?run={RUN}"
    exp = expected()
    SHOTS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for width, scheme in [(1400, "light"), (1400, "dark"), (400, "light"), (400, "dark")]:
            label = f"{width}px {scheme}"
            ctx = await browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)
            page = await ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "/api/state" not in (m.location or {}).get("url", "") else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(url)
            await page.wait_for_function("document.getElementById('kFound').textContent !== '–'")
            sw = await page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
            check(sw[0] <= sw[1], f"{label}: no horizontal page scroll {sw}")
            got = {k: await page.text_content(sel) for k, sel in
                   [("score", "#gVal"), ("found", "#kFound"), ("hidden", "#kHidden"), ("fixed", "#kFixed"), ("human", "#kHuman")]}
            check(all(got[k] == exp[k] for k in got), f"{label}: score and counters match the events {got}")
            check(await page.locator("#flow .node").count() >= 7, f"{label}: agent workflow rendered")
            check(await page.locator("#gauge svg path.g-fill").count() == (1 if exp["score"] != "–" else 0), f"{label}: gauge drawn")
            check(await page.locator("#timeline svg .score-line").count() == 1, f"{label}: score timeline drawn")
            if exp["outcome"]:
                got_o = (await page.text_content("#graderBody")).lower()
                check(exp["outcome"].replace("_", " ") in got_o, f"{label}: grader card shows {exp['outcome']}")
            if exp["eval"] is not None:
                got_e = await page.text_content("#evalBody")
                check(("Eval passed" if exp["eval"] else "Eval failed") in got_e, f"{label}: eval card verdict")
            check(await page.locator("#hosted").is_visible() == exp["session"], f"{label}: hosted badge only with a session id")
            await page.screenshot(path=str(SHOTS / f"rest-{width}-{scheme}.png"), full_page=True)
            await axe(page, label)

            if width == 1400 and scheme == "light":
                # keyboard: expand a row with Enter
                await page.focus(".rowbtn")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(100)
                check(await page.locator(".rowbtn").first.get_attribute("aria-expanded") == "true", "Enter expands a finding")
                check(await page.evaluate("document.activeElement.matches('.rowbtn')"), "focus stays on the row control")
                check(await page.locator("tr.detail pre").count() >= 1, "detail shows evidence/diff")
                await axe(page, "row expanded")
                # filters
                await page.click('[data-f="needs_human"]')
                check(await page.locator("tr.row").count() == int(exp["human"]), "filter: needs review")
                await page.click('[data-f="all"]')
                # tabs with arrow keys
                await page.focus("#t-findings")
                await page.keyboard.press("ArrowRight")
                check(await page.locator("#p-pr").is_visible(), "ArrowRight opens the Pull request tab")
                await page.keyboard.press("ArrowRight")
                if exp["has_stmt"]:
                    check(await page.locator("#p-stmt .todo").count() >= 1, "statement shows [TO COMPLETE] fields")
                await axe(page, "statement tab")
                await page.keyboard.press("Home")
                # About dialog
                await page.click("#aboutBtn")
                check(await page.locator("#about").evaluate("d => d.open"), "About dialog opens")
                await axe(page, "about")
                await page.keyboard.press("Escape")
                # replay at 4x
                await page.click('[data-speed="4"]')
                await page.click("#runBtn")
                await page.wait_for_timeout(800)
                check("Stop" in await page.text_content("#runBtn"), "Run audit becomes Stop")
                check(await page.locator("#prBtn").is_disabled(), "Send PR disabled while running")
                await page.screenshot(path=str(SHOTS / "running-1400.png"), full_page=False)
                await page.wait_for_function("document.getElementById('runBtn').textContent.includes('Run audit')", timeout=120000)
                check(await page.text_content("#gVal") == exp["score"], "replay ends on the final score")
                # send PR
                if exp["has_pr"]:
                    await page.click("#prBtn")
                    check(await page.evaluate("document.activeElement.id") == "sendPr", "header button focuses Send pull request")
                    await page.click("#sendPr")
                    await page.wait_for_selector(".sent", timeout=15000)
                    txt = await page.text_content(".sent")
                    check("opened" in txt and "no external system" in txt, "simulated PR confirmation card")
                    await page.screenshot(path=str(SHOTS / "pr-sent-1400.png"), full_page=True)
            check(not errors, f"{label}: no console errors {errors[:3]}")
            await ctx.close()
        await browser.close()
    print("\nFAILED:" if fails else "\nALL OK", *fails, sep="\n  ")
    sys.exit(1 if fails else 0)


asyncio.run(main())
