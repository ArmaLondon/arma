"""Event contract (spec §5): the only interface between the backend and the dashboard.

Every event is one JSON line: {"t": seconds-since-start, "type": ..., "agent"?: ..., "data": {...}}.
The recording is append-only; SSE subscribers get the same events live.
"""

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

RUN_STARTED = "run.started"
PHASE_CHANGED = "phase.changed"
AGENT_STATUS = "agent.status"
SUBAGENTS = "subagents"
LOG = "log"
BASELINE = "baseline"
ISSUE_DETECTED = "issue.detected"
ISSUE_MERGED = "issue.merged"
ISSUE_STATUS = "issue.status"
SCORE = "score"
BATCH_STARTED = "batch.started"
COMMIT_CREATED = "commit.created"
REAUDIT = "reaudit"
DOCUMENT_WRITTEN = "document.written"
PR_READY = "pr.ready"
PR_SENT = "pr.sent"
RUN_FINISHED = "run.finished"

EVENT_TYPES = (
    RUN_STARTED, PHASE_CHANGED, AGENT_STATUS, SUBAGENTS, LOG, BASELINE, ISSUE_DETECTED,
    ISSUE_MERGED, ISSUE_STATUS, SCORE, BATCH_STARTED, COMMIT_CREATED, REAUDIT,
    DOCUMENT_WRITTEN, PR_READY, PR_SENT, RUN_FINISHED,
)

PHASES = ("crawl", "baseline", "audit", "plan", "fix", "reaudit", "report", "pr")
LOG_KINDS = ("msg", "tool", "ok", "err", "reject", "rollback", "commit", "phase")


class EventBus:
    """Appends events to a JSONL file and fans them out to SSE subscribers."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self.history: list[dict[str, Any]] = []
        self._subscribers: list[asyncio.Queue] = []
        self._t0 = time.monotonic()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None  # tools may emit from parallel sessions
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, type: str, data: dict[str, Any] | None = None, agent: str | None = None) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {type}")
        with self._lock:
            event: dict[str, Any] = {"t": round(time.monotonic() - self._t0, 2), "type": type}
            if agent:
                event["agent"] = agent
            event["data"] = data or {}
            self.history.append(event)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            for q in list(self._subscribers):
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(q.put_nowait, event)
                else:
                    q.put_nowait(event)
            return event

    def subscribe(self, replay: bool = True) -> asyncio.Queue:
        """New subscriber queue, pre-filled with past events so late joiners see the whole run."""
        self._loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        if replay:
            for e in self.history:
                q.put_nowait(e)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)


def load_events(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
