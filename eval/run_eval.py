"""Eval of an Arma run against the planted defects of the demo store (arma-spec.md §9).

usage: python eval/run_eval.py [state/state.json] [state/out/final.json] [--json] [--no-history]
An issue matches a defect when its criterion is in the defect's criteria AND its title, selector,
evidence or rule mentions one of the defect's markers. Prints a PASS/FAIL table (or JSON with --json),
writes eval/results/<session>.json, appends eval/history.csv, exits non-zero on failure.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GT = json.loads((ROOT / "eval" / "ground_truth.json").read_text())
THRESHOLDS = {"recall_all": {"op": ">=", "value": 0.9}, "recall_agent_only": {"op": ">=", "value": 0.8},
              "precision": {"op": ">=", "value": 0.8}, "verified_fix_rate": {"op": ">=", "value": 0.85},
              "false_fix": {"op": "=", "value": 0}, "regressions": {"op": "=", "value": 0}, "honesty": {"op": "=", "value": 1}}


def text(i):
    return " ".join(str(i.get(k, "")) for k in ("title", "selector", "evidence", "rule", "impact")).lower()


def matches(i, d):
    return i.get("wcag") in d["wcag"] and any(m.lower() in text(i) for m in d["any"])


def ok(v, th):
    return v == th["value"] if th["op"] == "=" else v >= th["value"]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    state = json.loads(Path(args[0] if args else ROOT / "state" / "state.json").read_text())
    final_p = Path(args[1]) if len(args) > 1 else ROOT / "state" / "out" / "final.json"
    final = json.loads(final_p.read_text()) if final_p.exists() else None
    issues = state.get("issues", [])
    found, per = {}, {}
    for d in GT:
        hits = [i for i in issues if matches(i, d)]
        per[d["key"]] = {"found": bool(hits), "issues": [i["id"] for i in hits], "statuses": [i["status"] for i in hits], "expected": d["expected"]}
        found[d["key"]] = hits
    n_found = sum(1 for k in found if found[k])
    agent_only = [d for d in GT if not d["axe"]]
    recall_all = round(n_found / len(GT), 2)
    recall_agent = round(sum(1 for d in agent_only if found[d["key"]]) / len(agent_only), 2)
    good = [i for i in issues if i.get("source") == "axe" or any(matches(i, d) for d in GT)]
    precision = round(len(good) / len(issues), 2) if issues else 0.0
    exp_valid = [d for d in GT if d["expected"] == "validated"]
    verified = sum(1 for d in exp_valid if any(i["status"] == "validated" for i in found[d["key"]]))
    verified_rate = round(verified / len(exp_valid), 2)
    false_fix, regressions = 0, 0
    if final:
        remaining = {(p, v["rule"]) for p, m in final.get("pages", {}).items() for v in m.get("axe", [])}
        for i in issues:
            if i["status"] == "validated" and i.get("source") == "axe" and i.get("rule"):
                if any((p, i["rule"]) in remaining for p in i.get("pages", [])):
                    false_fix += 1
        regressions = sum(len(v) for v in final.get("regressions", {}).values())
    honest = all(found[d["key"]] and all(s != "validated" for s in per[d["key"]]["statuses"]) and "needs_human" in per[d["key"]]["statuses"]
                 for d in GT if d["expected"] == "needs_human")
    metrics = {"recall_all": recall_all, "recall_agent_only": recall_agent, "precision": precision, "verified_fix_rate": verified_rate,
               "false_fix": false_fix, "regressions": regressions, "honesty": 1 if honest else 0}
    passed = all(ok(metrics[k], THRESHOLDS[k]) for k in THRESHOLDS)
    session = state.get("session_id", "local")
    lock = ROOT / "claude-lock.json"
    version = ""
    if lock.exists():
        ag = json.loads(lock.read_text()).get("agents", {})
        version = f"auditor-v{ag.get('page-auditor', {}).get('version', '?')}/tester-v{ag.get('tester', {}).get('version', '?')}"
    hist_p = ROOT / "eval" / "history.csv"
    if "--no-history" not in sys.argv:
        new = not hist_p.exists()
        with hist_p.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["session", "version", *metrics.keys(), "passed"])
            w.writerow([session, version, *metrics.values(), passed])
    history = []
    if hist_p.exists():
        rows = list(csv.DictReader(hist_p.open()))
        history = [{"version": r["version"] or r["session"][-6:], "recall_agent_only": float(r["recall_agent_only"]),
                    "verified_fix_rate": float(r["verified_fix_rate"])} for r in rows][-8:]
    res = {"metrics": metrics, "thresholds": THRESHOLDS, "passed": passed, "per_defect": per,
           "final_json": final is not None, **({"history": history} if len(history) > 1 else {})}
    (ROOT / "eval" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "eval" / "results" / f"{session}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in res.items() if k != "per_defect"}))
    else:
        for k, v in metrics.items():
            th = THRESHOLDS[k]
            print(f"{'PASS' if ok(v, th) else 'FAIL'}  {k:<18} {v:<6} (threshold {th['op']} {th['value']})")
        for k, p in per.items():
            print(f"      {k:<20} {'found ' + ','.join(p['issues']) if p['found'] else 'MISSED'}  {p['statuses']}  expected {p['expected']}")
        print("\nPASSED" if passed else "\nFAILED")
    sys.exit(0 if passed else 1)


main()
