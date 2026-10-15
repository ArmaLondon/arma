"""Step 11: export a recorded run as human-readable agent logs.

usage: python scripts/export_logs.py [web/recordings/demo-run.jsonl] [-o deliverables/agent-logs.txt]
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASE_NAMES = {"crawl": "MAP SITE", "baseline": "BASELINE", "audit": "AUDIT", "plan": "PLAN",
               "fix": "FIX & VERIFY", "reaudit": "RE-AUDIT", "report": "REPORT", "pr": "PULL REQUEST"}


def mmss(t):
    s = int(t or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?", default=str(ROOT / "web" / "recordings" / "demo-run.jsonl"))
    ap.add_argument("-o", "--out", default=str(ROOT / "deliverables" / "agent-logs.txt"))
    ap.add_argument("--model", default="", help="model used for the run, for the header")
    a = ap.parse_args()
    events = [json.loads(l) for l in Path(a.run).read_text(encoding="utf-8").splitlines() if l.strip()]
    start = next((e["data"] for e in events if e["type"] == "run.started"), {})
    fin = next((e["data"] for e in events if e["type"] == "run.finished"), {})
    issues = {e["data"]["id"]: e["data"] for e in events if e["type"] == "issue.detected"}
    status = {k: "detected" for k in issues}
    for e in events:
        if e["type"] == "issue.status":
            status[e["data"]["id"]] = e["data"]["status"]
    scores = [e["data"] for e in events if e["type"] == "score"]
    commits = [e for e in events if e["type"] == "commit.created"]
    outcomes = [e["data"] for e in events if e["type"] == "outcome"]
    ev_res = next((e["data"] for e in reversed(events) if e["type"] == "eval"), None)
    grader_txt = " -> ".join("%s (iteration %s)" % (o.get("result"), o.get("iteration")) for o in outcomes) or "not run"
    if ev_res:
        failed = [k for k, v in ev_res.get("metrics", {}).items() if k in ev_res.get("thresholds", {}) and not (
            v == ev_res["thresholds"][k]["value"] if ev_res["thresholds"][k]["op"] == "=" else v >= ev_res["thresholds"][k]["value"])]
        eval_txt = ("PASS" if ev_res.get("passed") else "FAIL") + "  " + ", ".join(f"{k}={v}" for k, v in ev_res.get("metrics", {}).items()) + (f"  (failing: {', '.join(failed)})" if failed else "")
    else:
        eval_txt = "not run"
    rejects = sum(1 for e in events if e["type"] == "issue.status" and e["data"]["status"] == "rejected"
                  and str(e["data"].get("by", "")).startswith("tester"))
    rollbacks = sum(1 for e in events if e["type"] == "log" and e["data"].get("kind") == "rollback")
    lines = [
        "ARMA: agent run log",
        "=" * 72,
        "Project : Arma, EAA / WCAG 2.1 AA compliance by a Claude agent team",
        f"Runtime : {'Claude Managed Agents, session ' + start['session_id'] if start.get('session_id') else 'local Claude Agent SDK run (no hosted session)'}",
        f"Site    : {start.get('site', '')}   repo: {start.get('repo', '')}   branch: {start.get('branch', '')}",
        f"Model   : {a.model or 'see recording'}",
        f"Cost    : ${fin.get('cost_usd', 0):.2f}   Duration: {mmss(fin.get('duration_s', events[-1]['t'] if events else 0))} (agent time, recorded)",
        f"Issues  : {len(issues)} found, {sum(1 for i in issues.values() if i.get('source') != 'axe')} missed by automated scanners, "
        f"{sum(1 for s in status.values() if s == 'validated')} fixed and verified, {sum(1 for s in status.values() if s == 'needs_human')} need human review",
        f"Score   : {scores[0]['baseline'] if scores else '–'} → {scores[-1]['value'] if scores else '–'}   "
        f"Commits: {len(commits)}   Tester rejections: {rejects}   Rollbacks: {rollbacks}",
        f"Grader  : {grader_txt}",
        f"Eval    : {eval_txt}",
        f"Source  : {Path(a.run).name} (timestamps mm:ss since run start; idle gaps may be compressed)",
        "=" * 72,
    ]
    for e in events:
        if e["type"] == "phase.changed":
            lines += ["", f"---- {PHASE_NAMES.get(e['data']['phase'], e['data']['phase'].upper())} " + "-" * 40]
        elif e["type"] == "log":
            lines.append(f"{mmss(e['t'])} [{e.get('agent', 'orchestrator')}] {e['data'].get('text', '')}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{sum(1 for e in events if e['type'] == 'log')} log lines written to {out}")


if __name__ == "__main__":
    main()
