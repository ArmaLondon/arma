"""usage: python compare.py <url> — compare the page now with the baseline: resolved / still failing axe
violations, new violations (regressions), keyboard reachability, and the share of changed pixels with a
diff image (open it with read when changed_pixels_ratio > 0.02)."""
import json
import sys

from common import WORK, axe, keyboard, launch, main, open_page, path_of, slug, violation_keys, visual_diff
from playwright.sync_api import sync_playwright


def run():
    if len(sys.argv) < 2:
        raise ValueError("pass the page URL, e.g. python compare.py http://127.0.0.1:8765/index.html")
    url = sys.argv[1]
    base = json.loads((WORK / "baseline.json").read_text())
    b0 = base["pages"].get(path_of(url))
    if not b0:
        raise KeyError(f"{path_of(url)} is not in baseline.json (pages: {sorted(base['pages'])})")
    after = WORK / "shots" / "after" / f"{slug(url)}.png"
    after.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = launch(p)
        page = open_page(b, url)
        page.screenshot(path=str(after), full_page=True)
        now = axe(page)
        page.close()
        kb = keyboard(open_page(b, url))
        b.close()
    k0, k1 = violation_keys(b0), violation_keys({"axe": now})
    diff = WORK / "shots" / "diff" / f"{slug(url)}.png"
    ratio = visual_diff(b0["screenshot"], after, diff)
    return {"page": path_of(url), "resolved": sorted(f"{r} {t}" for r, t in k0 - k1),
            "still_failing": sorted(f"{r} {t}" for r, t in k0 & k1),
            "new_violations_regressions": sorted(f"{r} {t}" for r, t in k1 - k0),
            "keyboard": {"focus_visible": kb["focus_visible"], "unreachable": kb["unreachable"],
                         "baseline_focus_visible": b0["keyboard"]["focus_visible"], "baseline_unreachable": len(b0["keyboard"]["unreachable"])},
            "changed_pixels_ratio": ratio, "screenshots": {"before": b0["screenshot"], "after": str(after), "diff": str(diff)}}


main(run)
