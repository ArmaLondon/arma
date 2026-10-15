"""The scripted fixture covers the whole dashboard contract (web/events-contract.md)."""
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "web" / "recordings" / "fixture.jsonl"
TYPES = {"run.started", "phase.changed", "agent.status", "subagents", "log", "baseline", "issue.detected",
         "issue.merged", "issue.status", "score", "batch.started", "commit.created", "reaudit",
         "document.written", "outcome", "pr.ready", "pr.sent", "eval", "run.finished"}
PHASES = {"crawl", "baseline", "audit", "plan", "fix", "reaudit", "report", "pr"}
KINDS = {"msg", "tool", "ok", "err", "reject", "rollback", "commit", "phase"}


def events():
    return [json.loads(l) for l in FIXTURE.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_every_type_present_and_time_monotonic():
    ev = events()
    assert {e["type"] for e in ev} == TYPES
    ts = [e["t"] for e in ev]
    assert ts == sorted(ts)
    assert ev[0]["type"] == "run.started" and ev[0]["data"]["session_id"]


def test_values_are_valid():
    for e in events():
        if e["type"] == "log":
            assert e["data"]["kind"] in KINDS
        if e["type"] == "phase.changed":
            assert e["data"]["phase"] in PHASES


def test_story_beats():
    ev = events()
    statuses = [e["data"]["status"] for e in ev if e["type"] == "issue.status"]
    assert statuses.count("rejected") >= 2
    assert any(e["type"] == "log" and e["data"]["kind"] == "rollback" for e in ev)
    outcomes = [e["data"]["result"] for e in ev if e["type"] == "outcome"]
    assert outcomes[-1] == "satisfied"
    assert [e for e in ev if e["type"] == "eval"][-1]["data"]["passed"] is True
