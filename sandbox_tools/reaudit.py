"""usage: python reaudit.py — re-measure every page after the fixes → $ARMA_WORK/final.json, after/*.png,
and regressions (axe violations absent from the baseline)."""
import json

from common import WORK, launch, main, measure_all, summary, violation_keys
from playwright.sync_api import sync_playwright


def run():
    base_f = WORK / "baseline.json"
    if not base_f.exists():
        raise FileNotFoundError("baseline.json missing: run baseline.py before any fix")
    base = json.loads(base_f.read_text())
    with sync_playwright() as p:
        b = launch(p)
        m = measure_all(b, [x["url"] for x in base["pages"].values()], WORK / "shots" / "after")
        b.close()
    regressions = {}
    for path, x in m.items():
        new = violation_keys(x) - violation_keys(base["pages"].get(path, {"axe": []}))
        if new:
            regressions[path] = sorted(f"{r} {t}" for r, t in new)
    data = {"summary": summary(m), "baseline_summary": base["summary"], "regressions": regressions, "pages": m}
    (WORK / "final.json").write_text(json.dumps(data))
    return {"before": base["summary"], "after": data["summary"], "regressions": regressions,
            "remaining": {k: sorted({v["rule"] for v in x["axe"]}) for k, x in m.items() if x["axe"]},
            "saved": str(WORK / "final.json")}


main(run)
