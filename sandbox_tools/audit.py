"""usage: python audit.py <url> — axe-core violations (WCAG 2.0/2.1 A+AA), criteria normalised (wcag143 → 1.4.3)."""
import sys

from common import axe, launch, main, open_page, path_of
from playwright.sync_api import sync_playwright


def run():
    if len(sys.argv) < 2:
        raise ValueError("pass the page URL, e.g. python audit.py http://127.0.0.1:8765/product.html")
    with sync_playwright() as p:
        b = launch(p)
        page = open_page(b, sys.argv[1])
        vs = axe(page)
        b.close()
    return {"page": path_of(sys.argv[1]), "violations": vs, "total_nodes": sum(v["count"] for v in vs)}


main(run)
