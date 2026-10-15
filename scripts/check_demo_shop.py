"""Step 4 gate: serve demo-shop/, run axe on the 4 pages.

axe must find the scanner defects (color-contrast, html-has-lang, image-alt) and must NOT find the
"agent" defects (emoji buttons, placeholder labels, div buttons...): those are for the judgment layer.
"""
import asyncio
import functools
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOP = ROOT / "demo-shop"
AXE = (ROOT / "vendor" / "axe.min.js").read_text()
PAGES = ["index.html", "product.html", "cart.html", "checkout.html"]
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
MUST = {"color-contrast", "html-has-lang", "image-alt"}
MUST_NOT = {"button-name", "label", "frame-title", "link-name", "heading-order", "page-has-heading-one"}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SHOP)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


async def main() -> int:
    srv, base = serve()
    found: dict[str, set[str]] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for name in PAGES:
            page = await browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"{base}/{name}")
            await page.add_script_tag(content=AXE)
            res = await page.evaluate("t => axe.run({runOnly: {type: 'tag', values: t}})", TAGS)
            rules = {v["id"]: len(v["nodes"]) for v in res["violations"]}
            print(f"{name:14} {rules}  incomplete={[v['id'] for v in res['incomplete']]}")
            if errors:
                print("  JS errors:", errors)
                return 1
            for r in rules:
                found.setdefault(r, set()).add(name)
            await page.close()
        await browser.close()
    srv.shutdown()

    ok = True
    for r in sorted(MUST):
        hit = r in found
        ok &= hit
        print(f"{'OK' if hit else 'KO'}  axe finds {r}: {sorted(found.get(r, []))}")
    for r in sorted(MUST_NOT):
        hit = r in found
        ok &= not hit
        print(f"{'KO' if hit else 'OK'}  axe misses {r}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
