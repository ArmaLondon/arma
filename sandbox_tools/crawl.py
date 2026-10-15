"""usage: python crawl.py <start_url> — breadth-first crawl incl. onclick navigation; writes $ARMA_WORK/pages.json."""
import json
import sys

from common import WORK, crawl, launch, main
from playwright.sync_api import sync_playwright


def run():
    start = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/index.html"
    with sync_playwright() as p:
        b = launch(p)
        pages = crawl(b, start)
        b.close()
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "pages.json").write_text(json.dumps(pages, indent=1))
    return {"pages": pages, "count": len(pages), "saved": str(WORK / "pages.json")}


main(run)
