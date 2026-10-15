from pathlib import Path

from arma.events import EVENT_TYPES, LOG_KINDS, PHASES, load_events

FIXTURE = Path(__file__).resolve().parent.parent / "web" / "recordings" / "fixture.jsonl"


def test_fixture_parses_and_is_monotonic():
    events = load_events(FIXTURE)
    ts = [e["t"] for e in events]
    assert ts == sorted(ts)
    assert events[0]["type"] == "run.started"
    assert any(e["type"] == "run.finished" for e in events)


def test_fixture_covers_every_event_type():
    seen = {e["type"] for e in load_events(FIXTURE)}
    assert seen == set(EVENT_TYPES), set(EVENT_TYPES) ^ seen


def test_fixture_values_are_valid():
    events = load_events(FIXTURE)
    for e in events:
        if e["type"] == "log":
            assert e["data"]["kind"] in LOG_KINDS
        if e["type"] == "phase.changed":
            assert e["data"]["phase"] in PHASES
    statuses = {e["data"]["status"] for e in events if e["type"] == "issue.status"}
    assert {"rejected", "validated", "needs_human"} <= statuses
    assert any(e["type"] == "log" and e["data"]["kind"] == "rollback" for e in events)
