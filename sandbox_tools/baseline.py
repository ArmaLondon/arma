"""usage: python baseline.py [start_url] — axe + keyboard + screenshots for every page (pages.json, or crawl) →
$ARMA_WORK/baseline.json and before/*.png. Run once, before any fix."""
import json
import sys

from common import WORK, crawl, launch, main, measure_all, pages_list, summary
from playwright.sync_api import sync_playwright


def run():
    with sync_playwright() as p:
        b = launch(p)
        pages = pages_list() or crawl(b, sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/index.html")
        m = measure_all(b, pages, WORK / "shots" / "before")
        b.close()
    data = {"summary": summary(m), "pages": m}
    (WORK / "baseline.json").write_text(json.dumps(data))
    return {"summary": data["summary"], "per_page": {k: {"axe_rules": sorted({v["rule"] for v in x["axe"]}),
            "unreachable": len(x["keyboard"]["unreachable"]), "focus_visible": x["keyboard"]["focus_visible"]} for k, x in m.items()},
            "saved": str(WORK / "baseline.json")}


main(run)
