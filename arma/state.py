"""Persistent run state (spec §6): one JSON file, atomic writes, issue de-duplication.

Agents never touch this directly: they go through the typed MCP tools, which call the Store.
"""

import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import scoring, wcag
from .config import ROOT

DETECTED = "detected"
FIXING = "fixing"
FIXED_PENDING = "fixed_pending"
REJECTED = "rejected"
VALIDATED = "validated"
NEEDS_HUMAN = "needs_human"
STATUSES = (DETECTED, FIXING, FIXED_PENDING, REJECTED, VALIDATED, NEEDS_HUMAN)
TODO_STATUSES = (DETECTED, REJECTED, FIXING, FIXED_PENDING)   # still to work on in a batch

SEVERITIES = ("critical", "major", "minor")
SOURCES = ("axe", "keyboard", "agent")

BATCH_TODO, BATCH_IN_PROGRESS, BATCH_DONE, BATCH_ESCALATED = "todo", "in_progress", "done", "escalated"

DEFAULT_PATH = ROOT / "state" / "state.json"


def _empty() -> dict[str, Any]:
    return {"phases_done": [], "current_phase": None, "pages": [], "issues": [], "batches": [],
            "baseline": {}, "final": {}, "frozen_total": None, "cost_usd": 0.0, "meta": {}}


def _key(text: str) -> str:
    return " ".join((text or "").lower().split())


class Store:
    def __init__(self, path: Path | str = DEFAULT_PATH, reset: bool = False,
                 clock: Callable[[], float] | None = None):
        self.path = Path(path)
        self._lock = threading.RLock()
        t0 = time.monotonic()
        self.clock = clock or (lambda: round(time.monotonic() - t0, 2))
        if self.path.exists() and not reset:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in _empty().items():
                self.data.setdefault(k, v)
        else:
            self.data = _empty()
            self._save()

    # ------------------------------------------------------------ persistence
    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, key: str) -> Any:
        with self._lock:
            return copy.deepcopy(self.data[key])

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self.data[key] = value
            self._save()

    def add_cost(self, usd: float) -> float:
        with self._lock:
            self.data["cost_usd"] = round(self.data["cost_usd"] + (usd or 0.0), 6)
            self._save()
            return self.data["cost_usd"]

    # ------------------------------------------------------------ phases
    def phase_done(self, phase: str) -> bool:
        return phase in self.data["phases_done"]

    def start_phase(self, phase: str) -> None:
        self.set("current_phase", phase)

    def finish_phase(self, phase: str) -> None:
        with self._lock:
            if phase not in self.data["phases_done"]:
                self.data["phases_done"].append(phase)
            self.data["current_phase"] = None
            self._save()

    # ------------------------------------------------------------ pages
    def add_page(self, url: str, title: str = "", template: str = "", label: str = "") -> tuple[dict, bool]:
        with self._lock:
            for p in self.data["pages"]:
                if p["url"] == url:
                    return copy.deepcopy(p), False
            page = {"url": url, "title": title, "template": template, "label": label or template or url}
            self.data["pages"].append(page)
            self._save()
            return copy.deepcopy(page), True

    def pages(self) -> list[dict]:
        return self.get("pages")

    # ------------------------------------------------------------ issues
    def _find_duplicate(self, wcag_: str, selector: str, rule: str, title: str) -> dict | None:
        for i in self.data["issues"]:
            if i["wcag"] != wcag_ or _key(i["selector"]) != _key(selector):
                continue
            if (rule and i["rule"] == rule) or _key(i["title"]) == _key(title):
                return i
        return None

    def add_issue(self, **f: Any) -> tuple[dict, bool]:
        """Create an issue, or merge it into the same component (same wcag + selector + rule/title).

        Returns (issue, merged). On merge only the new pages are added.
        """
        wcag_ = str(f.get("wcag", "")).strip()
        selector, rule, title = f.get("selector", "") or "", f.get("rule", "") or "", f.get("title", "")
        pages = f.get("pages") or ([f["page"]] if f.get("page") else [])
        with self._lock:
            dup = self._find_duplicate(wcag_, selector, rule, title)
            if dup:
                for p in pages:
                    if p not in dup["pages"]:
                        dup["pages"].append(p)
                self._save()
                return copy.deepcopy(dup), True
            n = len(self.data["issues"]) + 1
            severity = f.get("severity") if f.get("severity") in SEVERITIES else "major"
            source = f.get("source") if f.get("source") in SOURCES else "agent"
            by = f.get("by", "auditor")
            issue = {
                "id": f"A{n:02d}", "wcag": wcag_,
                "criterion_name": f.get("criterion_name") or wcag.name(wcag_),
                "level": f.get("level") or wcag.level(wcag_),
                "principle": scoring.principle(wcag_), "en301549": "9." + wcag_,
                "title": title, "impact": f.get("impact", ""), "evidence": (f.get("evidence") or "")[:600],
                "severity": severity, "source": source, "selector": selector, "rule": rule,
                "pages": list(dict.fromkeys(pages)), "status": DETECTED, "attempts": 0,
                "files": [], "fix_diff": "", "fix_note": "", "human_action": "",
                "history": [{"t": self.clock(), "status": DETECTED, "by": by,
                             "note": f.get("note") or "Detected"}],
            }
            self.data["issues"].append(issue)
            self._save()
            return copy.deepcopy(issue), False

    def _issue(self, issue_id: str) -> dict:
        for i in self.data["issues"]:
            if i["id"] == issue_id:
                return i
        raise KeyError(f"unknown issue id {issue_id!r}")

    def issue(self, issue_id: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._issue(issue_id))

    def issues(self, status: str | tuple[str, ...] | None = None) -> list[dict]:
        with self._lock:
            its = self.data["issues"]
            if status:
                wanted = (status,) if isinstance(status, str) else status
                its = [i for i in its if i["status"] in wanted]
            return copy.deepcopy(its)

    def set_status(self, issue_id: str, status: str, by: str, note: str = "", **fields: Any) -> dict:
        if status not in STATUSES:
            raise ValueError(f"invalid status {status!r}")
        attempt = fields.pop("attempt", None)
        with self._lock:
            i = self._issue(issue_id)
            i.update(fields)
            i["status"] = status
            entry = {"t": self.clock(), "status": status, "by": by, "note": note}
            if attempt is not None:
                entry["attempt"] = attempt
            i["history"].append(entry)
            self._save()
            return copy.deepcopy(i)

    def update_issue(self, issue_id: str, **fields: Any) -> dict:
        with self._lock:
            i = self._issue(issue_id)
            i.update(fields)
            self._save()
            return copy.deepcopy(i)

    # ------------------------------------------------------------ score
    def freeze_score(self) -> float:
        with self._lock:
            self.data["frozen_total"] = scoring.frozen_total(self.data["issues"])
            self._save()
            return self.data["frozen_total"]

    def score(self) -> dict:
        with self._lock:
            return scoring.compute(self.data["issues"], self.data["frozen_total"])
