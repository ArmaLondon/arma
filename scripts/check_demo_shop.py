"""Steps 4–5 gate: serve demo-shop/ and run the deterministic browser tools on it.

- crawl finds the 4 pages, checkout included (only reachable through an onclick)
- axe finds the scanner defects (color-contrast, html-has-lang, image-alt) and NOT the "agent"
  defects (emoji buttons, placeholder labels, div buttons...): those are for the judgment layer
- keyboard_walk(product) sees no visible focus and unreachable div.size / div.btn
- visual_diff of two identical screenshots is 0.0
"""
import asyncio
import functools
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arma import browser  # noqa: E402

SHOP = Path(__file__).resolve().parent.parent / "demo-shop"
MUST = {"color-contrast", "html-has-lang", "image-alt"}
MUST_NOT = {"button-name", "label", "frame-title", "link-name", "heading-order", "page-has-heading-one"}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(SHOP)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


async def main() -> int:
    srv, base = serve()
    checks: list[tuple[bool, str]] = []

    pages = await browser.crawl(base)
    urls = [p["url"] for p in pages]
    print("crawl:", [u.removeprefix(base) or "/" for u in urls])
    checks.append((len(pages) == 4 and any(u.endswith("checkout.html") for u in urls),
                   "crawl finds 4 pages incl. checkout"))

    audits = await asyncio.gather(*(browser.axe_audit(u) for u in urls))
    found: set[str] = set()
    for a in audits:
        rules = {v["rule"]: (v["wcag"], v["count"]) for v in a["violations"]}
        print(f"axe {a['url'].removeprefix(base) or '/':14} {rules}")
        found |= set(rules)
    index = next(a for a in audits if a["url"] == base)
    checks.append((MUST <= {v["rule"] for v in index["violations"]}, f"axe on index finds {sorted(MUST)}"))
    checks.append((not (found & MUST_NOT), f"axe misses agent defects ({sorted(found & MUST_NOT) or 'none found'})"))

    kb = await browser.keyboard_walk(base + "product.html")
    print("keyboard product: focus_visible", kb["focus_visible"], "cycle", kb["cycle_complete"])
    for s in kb["stops"]:
        print(f"   stop {s['selector']:40} name={s['name']!r} ({s['name_source']})")
    for u in kb["unreachable"]:
        print(f"   unreachable {u['selector']:34} {u['text']!r}")
    checks.append((kb["focus_visible"][0] == 0 and kb["stops"], "no visible focus on product"))
    checks.append((all(any(c in u["selector"] for u in kb["unreachable"]) for c in ("div.size", "div.btn")), "div.size and div.btn unreachable"))

    with tempfile.TemporaryDirectory() as tmp:
        a = await browser.screenshot(base, Path(tmp) / "a.png")
        b = await browser.screenshot(base, Path(tmp) / "b.png")
        ratio = await browser.visual_diff(a, b, Path(tmp) / "diff.png")
    print("visual_diff identical:", ratio)
    checks.append((ratio == 0.0, "visual_diff of identical shots is 0.0"))

    html = await browser.page_html(base + "checkout.html", max_chars=500)
    checks.append(("truncated" in html, "page_html truncates"))
    srv.shutdown()

    for ok, label in checks:
        print(f"{'OK' if ok else 'KO'}  {label}")
    ok = all(c[0] for c in checks)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
