"""Step 10: validate a recorded run and ship it as the dashboard demo.

usage: python scripts/pick_demo_run.py recordings/run-<date>.jsonl [--max-gap 4] [--force]

Checks (OK/KO): pr.ready present; an issue rejected then validated; a rollback log; parallel
sub-auditors (subagents). Dead time is compressed: every gap between consecutive events is capped
at --max-gap seconds, order is kept, t is recomputed. Nothing else is changed: events are never
invented or edited. Output: web/recordings/demo-run.jsonl.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "recordings" / "demo-run.jsonl"


def checks(events):
    status_seq: dict[str, list[str]] = {}
    for e in events:
        if e["type"] == "issue.status":
            status_seq.setdefault(e["data"]["id"], []).append(e["data"]["status"])
    reject_then_ok = sorted(i for i, seq in status_seq.items()
                            if "rejected" in seq and "validated" in seq[seq.index("rejected"):])
    return {
        "pr.ready present": any(e["type"] == "pr.ready" for e in events),
        f"rejected then validated ({', '.join(reject_then_ok) or 'none'})": bool(reject_then_ok),
        "rollback logged": any(e["type"] == "log" and e["data"].get("kind") == "rollback" for e in events),
        "parallel sub-auditors": any(e["type"] == "subagents" for e in events),
        "run.finished present": any(e["type"] == "run.finished" for e in events),
    }


def compress(events, max_gap):
    out, prev_src, t = [], None, 0.0
    for e in events:
        src = float(e.get("t", 0))
        if prev_src is not None:
            t += min(max(src - prev_src, 0.0), max_gap)
        prev_src = src
        out.append({**e, "t": round(t, 2)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--max-gap", type=float, default=4.0)
    ap.add_argument("--force", action="store_true", help="ship even if a check is KO")
    a = ap.parse_args()
    events = [json.loads(l) for l in Path(a.run).read_text(encoding="utf-8").splitlines() if l.strip()]
    # a file may hold several runs if it was appended to: keep the last one
    starts = [i for i, e in enumerate(events) if e["type"] == "run.started"]
    if len(starts) > 1:
        events = events[starts[-1]:]
    res = checks(events)
    for name, ok in res.items():
        print(("OK  " if ok else "KO  ") + name)
    if not all(res.values()) and not a.force:
        print("not shipped (use --force to ship anyway)")
        sys.exit(1)
    out = compress(events, a.max_gap)
    OUT.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in out), encoding="utf-8")
    print(f"{len(out)} events, {events[-1]['t']:.0f}s → {out[-1]['t']:.0f}s, written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
