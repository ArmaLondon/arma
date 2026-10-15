"""Custom tools = Arma's compliance ledger (arma-spec 2 §6).

Claude does not run these: the hosted agents call them, the bridge answers each call. Every handler
validates its input and the caller, enforces the status state machine, records the audit trail and
emits the dashboard events. Handlers return a short actionable text; errors are (text, True).
"""
from __future__ import annotations

from typing import Any

from arma import state as st
from arma.events import EventBus
from arma.state import Store

S = lambda d: {"type": "string", "description": d}  # noqa: E731
AGENT = S("Your role label: lead, auditor·<page>, developer, tester or writer.")

SCHEMAS: dict[str, dict[str, Any]] = {
    "register_page": {
        "description": "Record a page of the store in the compliance ledger, with its template (home, product, cart, checkout...). Call once per page found by the crawl.",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "url": S("Page URL or path, e.g. /product.html"),
                         "template": S("Page template: home, category, product, cart, checkout...")}, "required": ["agent", "url", "template"]},
    },
    "report_issue": {
        "description": "Record one WCAG 2.1 AA failure in the compliance ledger. Same criterion + same selector + same rule (or title) on another page is merged into the existing issue, so use stable selectors for shared components. Returns the issue id. Findings that are not recorded with this tool are lost.",
        "input_schema": {"type": "object", "properties": {
            "agent": AGENT, "page": S("Page path, e.g. /product.html"), "wcag": S("Success criterion, e.g. 2.1.1"),
            "title": S("One line: what a shopper experiences"), "impact": S("Who is blocked and how, concretely"),
            "evidence": S("The offending code (short)"), "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
            "selector": S("Stable CSS selector of the component"), "source": {"type": "string", "enum": ["axe", "keyboard", "agent"]},
            "rule": S("axe rule id, or empty")},
            "required": ["agent", "page", "wcag", "title", "impact", "evidence", "severity", "selector", "source"]},
    },
    "list_issues": {
        "description": "List the issues in the compliance ledger (id, wcag, title, severity, source, pages, selector, status, files, history notes). Optionally filter by status.",
        "input_schema": {"type": "object", "properties": {"status": {"type": "string", "enum": list(st.STATUSES)}}},
    },
    "plan_batches": {
        "description": "Record the remediation plan: one batch per WCAG criterion, purchase blockers first. Every issue must be in exactly one batch. Returns the batch ids (B01, B02...). Freezes the baseline score.",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "batches": {"type": "array", "items": {"type": "object", "properties": {
            "criterion": S("WCAG criterion, e.g. 2.4.7"), "issue_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["criterion", "issue_ids"]}}},
            "required": ["agent", "batches"]},
    },
    "start_batch": {
        "description": "Start an attempt on a batch: its open issues (detected, rejected) move to 'fixing'. Call before sending the batch to the developer.",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "batch_id": S("e.g. B01"), "attempt": {"type": "integer", "minimum": 1, "maximum": 3}},
                         "required": ["agent", "batch_id", "attempt"]},
    },
    "mark_fixed": {
        "description": "Developer only: declare an issue fixed in the source, with the files changed, a one-line explanation and the git diff of those files. The issue must be in 'fixing'. It then waits for the tester.",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "issue_id": S("e.g. A07"), "files": {"type": "array", "items": {"type": "string"}},
                         "explanation": S("One line"), "diff": S("git diff -- <files>, truncated to ~60 lines")}, "required": ["agent", "issue_id", "files", "explanation", "diff"]},
    },
    "cannot_fix": {
        "description": "Developer only: escalate an issue that cannot be fixed truthfully in this repository (missing product facts, third-party vendor content...). Give the reason and the concrete human action (who must do what).",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "issue_id": S("e.g. A04"), "reason": S("Why no truthful code fix is possible"),
                         "human_action": S("Who must do what")}, "required": ["agent", "issue_id", "reason", "human_action"]},
    },
    "verdict": {
        "description": "Tester only: accept or reject one fix after measuring it. The issue must be 'fixed_pending'. Give an actionable reason (what is still wrong and how to fix it).",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "issue_id": S("e.g. A07"), "accepted": {"type": "boolean"},
                         "reason": S("Actionable reason")}, "required": ["agent", "issue_id", "accepted", "reason"]},
    },
    "batch_verdict": {
        "description": "Tester only: verdict on the whole batch. accepted=false only for a regression or a broken design: the lead will roll the batch back.",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "batch_id": S("e.g. B01"), "accepted": {"type": "boolean"}, "reason": S("Short reason")},
                         "required": ["agent", "batch_id", "accepted", "reason"]},
    },
    "rollback_batch": {
        "description": "Lead only: record that the batch's uncommitted changes were reverted (after git checkout -- . && git clean -fd). Its unfinished issues go back to 'rejected' for the next attempt.",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "batch_id": S("e.g. B01"), "reason": S("Why")}, "required": ["agent", "batch_id", "reason"]},
    },
    "record_commit": {
        "description": "Lead only: record a git commit of validated fixes for a batch (sha from git rev-parse --short HEAD).",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "batch_id": S("e.g. B01"), "sha": S("Short sha"), "message": S("Commit message"),
                         "files": {"type": "array", "items": {"type": "string"}}}, "required": ["agent", "batch_id", "sha", "message", "files"]},
    },
    "emit_progress": {
        "description": "Show one short progress sentence in the live dashboard log. Use kind 'phase' with the phase field when a protocol phase starts; pass metrics (axe_violations, unreachable, focus_visible) with phase baseline or reaudit.",
        "input_schema": {"type": "object", "properties": {"agent": AGENT, "text": S("One short sentence"),
                         "kind": {"type": "string", "enum": ["msg", "tool", "ok", "reject", "phase"]},
                         "phase": {"type": "string", "enum": ["crawl", "baseline", "audit", "plan", "fix", "reaudit", "report", "pr"]},
                         "metrics": {"type": "object", "properties": {"axe_violations": {"type": "integer"}, "unreachable": {"type": "integer"},
                                     "focus_visible": {"type": "array", "items": {"type": "integer"}}}}},
                         "required": ["agent", "text", "kind"]},
    },
}

ROLE_TOOLS = {
    "lead": ["register_page", "list_issues", "plan_batches", "start_batch", "record_commit", "rollback_batch", "emit_progress"],
    "page-auditor": ["report_issue", "list_issues", "emit_progress"],
    "developer": ["mark_fixed", "cannot_fix", "list_issues", "emit_progress"],
    "tester": ["verdict", "batch_verdict", "list_issues", "emit_progress"],
    "writer": ["list_issues", "emit_progress"],
}


def tool_defs(role: str) -> list[dict]:
    return [{"type": "custom", "name": n, **SCHEMAS[n]} for n in ROLE_TOOLS[role]]


class Ledger:
    """Handlers for the custom tools, backed by arma.state.Store and the dashboard EventBus."""

    def __init__(self, store: Store, bus: EventBus):
        self.store, self.bus = store, bus
        self.batches: dict[str, dict] = {}
        self.committed: set[str] = set()
        self.frozen = False
        self.phase = None

    # -------------------------------------------------- helpers
    def log(self, agent, text, kind="msg"):
        self.bus.emit("log", {"text": text, "kind": kind}, agent=agent)

    def status_event(self, i: dict, by: str, note: str, attempt: int = 0, **extra):
        self.bus.emit("issue.status", {"id": i["id"], "status": i["status"], "by": by, "note": note, "attempt": attempt, **extra}, agent=by)
        if self.frozen:
            sc = self.store.score()
            self.bus.emit("score", {"value": sc["value"], "baseline": self.store.data.get("baseline_score"),
                                    "by_principle": sc["by_principle"], "eaa": sc["eaa"]})

    def set_phase(self, phase: str):
        if phase and phase != self.phase:
            self.phase = phase
            self.bus.emit("phase.changed", {"phase": phase})

    def handle(self, name: str, inp: dict, label: str) -> tuple[str, bool]:
        fn = getattr(self, "t_" + name, None)
        if not fn:
            return f"unknown tool {name}", True
        try:
            return fn(inp, inp.get("agent") or label)
        except KeyError as e:
            return f"{name} refused: {e.args[0]}. Call list_issues to see valid ids and statuses.", True
        except Exception as e:  # noqa: BLE001 — never crash the run on a bad call
            return f"{name} failed: {type(e).__name__}: {e}. Fix the input and retry.", True

    # -------------------------------------------------- tools
    def t_register_page(self, d, who):
        page, new = self.store.add_page(d["url"], template=d.get("template", ""), label=d.get("template", ""))
        if new:
            self.log(who, f"register_page {d['url']} ({d.get('template', '')})", "tool")
        return f"page registered: {d['url']}", False

    def t_report_issue(self, d, who):
        issue, merged = self.store.add_issue(page=d.get("page"), wcag=d["wcag"], title=d["title"], impact=d.get("impact", ""),
                                             evidence=d.get("evidence", ""), severity=d.get("severity"), selector=d.get("selector", ""),
                                             source=d.get("source"), rule=d.get("rule", ""), by=who, note="Detected during page audit")
        if merged:
            self.bus.emit("issue.merged", {"id": issue["id"], "page": d.get("page")}, agent=who)
            self.log(who, f"{issue['id']} also on {d.get('page')} (same component, merged)")
            return f"merged into existing issue {issue['id']} (now on {len(issue['pages'])} pages)", False
        self.bus.emit("issue.detected", issue, agent=who)
        self.log(who, f"report_issue {issue['id']} [{issue['wcag']}] {issue['title']}")
        return f"recorded as {issue['id']}", False

    def t_list_issues(self, d, who):
        import json
        its = self.store.issues(d.get("status") or None)
        slim = [{k: i[k] for k in ("id", "wcag", "title", "severity", "source", "pages", "selector", "status", "files", "human_action")}
                | {"notes": [h["note"] for h in i["history"][-3:]], "evidence": i["evidence"][:200]} for i in its]
        return json.dumps({"count": len(slim), "issues": slim, "batches": self.batches}, ensure_ascii=False), False

    def t_plan_batches(self, d, who):
        ids = [x for b in d["batches"] for x in b["issue_ids"]]
        dup = {x for x in ids if ids.count(x) > 1}
        if dup:
            return f"plan refused: issues in more than one batch: {sorted(dup)}", True
        known = {i["id"] for i in self.store.issues()}
        unknown = set(ids) - known
        if unknown:
            return f"plan refused: unknown issue ids {sorted(unknown)}", True
        missing = known - set(ids)
        self.batches = {f"B{n:02d}": {"criterion": b["criterion"], "issue_ids": b["issue_ids"], "attempt": 0}
                        for n, b in enumerate(d["batches"], 1)}
        if not self.frozen:
            self.store.freeze_score()
            sc = self.store.score()
            self.store.set("baseline_score", sc["value"])
            self.frozen = True
            self.bus.emit("score", {"value": sc["value"], "baseline": sc["value"], "by_principle": sc["by_principle"], "eaa": sc["eaa"]})
        self.set_phase("plan")
        self.log(who, f"Plan: {len(self.batches)} batches by WCAG criterion, purchase blockers first.", "phase")
        for bid, b in self.batches.items():
            self.log(who, f"Batch {bid} WCAG {b['criterion']}: {', '.join(b['issue_ids'])}", "tool")
        note = f" Warning: not planned yet: {sorted(missing)}." if missing else ""
        return "batches: " + ", ".join(f"{k}={v['criterion']}" for k, v in self.batches.items()) + note, False

    def t_start_batch(self, d, who):
        b = self.batches.get(d["batch_id"])
        if not b:
            return f"unknown batch {d['batch_id']}; known: {sorted(self.batches)}", True
        att = int(d.get("attempt", 1))
        b["attempt"] = att
        self.set_phase("fix")
        self.bus.emit("batch.started", {"id": d["batch_id"], "criterion": b["criterion"], "issue_ids": b["issue_ids"], "attempt": att}, agent=who)
        self.log(who, f"Batch {d['batch_id']} · WCAG {b['criterion']} · attempt {att}/3", "phase")
        moved = []
        for iid in b["issue_ids"]:
            i = self.store.issue(iid)
            if i["status"] in (st.DETECTED, st.REJECTED, st.FIXING, st.FIXED_PENDING):
                i = self.store.set_status(iid, st.FIXING, who, "Assigned to developer", attempt=att, attempts=att)
                self.status_event(i, who, "Assigned to developer", att)
                moved.append(iid)
        return f"batch {d['batch_id']} attempt {att}: fixing {moved or 'nothing (all done)'}", False

    def _attempt(self, iid):
        for b in self.batches.values():
            if iid in b["issue_ids"]:
                return b["attempt"]
        return 1

    def t_mark_fixed(self, d, who):
        i = self.store.issue(d["issue_id"])
        if i["status"] != st.FIXING:
            return f"mark_fixed refused: issue {i['id']} is {i['status']}, not fixing (the lead must start_batch first)", True
        diff = (d.get("diff") or "")[:4000]
        i = self.store.set_status(i["id"], st.FIXED_PENDING, who, d["explanation"], attempt=self._attempt(i["id"]),
                                  files=d.get("files", []), fix_diff=diff, fix_note=d["explanation"])
        self.status_event(i, who, d["explanation"], self._attempt(i["id"]), fix_diff=diff, files=d.get("files", []))
        self.log(who, f"mark_fixed {i['id']}: {d['explanation']}")
        return f"{i['id']} is now fixed_pending, waiting for the tester", False

    def t_cannot_fix(self, d, who):
        i = self.store.issue(d["issue_id"])
        if i["status"] in (st.VALIDATED, st.NEEDS_HUMAN):
            return f"cannot_fix refused: issue {i['id']} is already {i['status']}", True
        i = self.store.set_status(i["id"], st.NEEDS_HUMAN, who, d["reason"], attempt=self._attempt(i["id"]), human_action=d["human_action"])
        self.status_event(i, who, d["reason"], self._attempt(i["id"]), human_action=d["human_action"])
        self.log(who, f"cannot_fix {i['id']}: {d['reason']} → escalated to a human", "reject")
        return f"{i['id']} escalated (needs_human)", False

    def t_verdict(self, d, who):
        if not who.startswith("tester"):
            return f"verdict refused: only the tester can give verdicts (caller: {who})", True
        i = self.store.issue(d["issue_id"])
        if i["status"] != st.FIXED_PENDING:
            return f"verdict refused: issue {i['id']} is {i['status']}, not fixed_pending", True
        new = st.VALIDATED if d["accepted"] else st.REJECTED
        i = self.store.set_status(i["id"], new, who, d["reason"], attempt=self._attempt(i["id"]))
        self.status_event(i, who, d["reason"], self._attempt(i["id"]))
        if d["accepted"]:
            self.log(who, f"{i['id']} validated: {d['reason']}", "ok")
        else:
            self.log(who, f"REJECTED {i['id']}: {d['reason']}", "reject")
        return f"{i['id']} → {new}", False

    def t_batch_verdict(self, d, who):
        if not who.startswith("tester"):
            return f"batch_verdict refused: only the tester can give verdicts (caller: {who})", True
        if d["accepted"]:
            self.log(who, f"Batch {d['batch_id']} verdict: no regression. {d['reason']}", "ok")
        else:
            self.log(who, f"Batch {d['batch_id']} verdict: REGRESSION, roll back. {d['reason']}", "reject")
        return "batch verdict recorded" + ("" if d["accepted"] else ": the lead must roll back"), False

    def t_rollback_batch(self, d, who):
        b = self.batches.get(d["batch_id"])
        if not b:
            return f"unknown batch {d['batch_id']}", True
        for iid in b["issue_ids"]:
            i = self.store.issue(iid)
            if iid in self.committed or i["status"] == st.NEEDS_HUMAN:
                continue
            if i["status"] in (st.FIXING, st.FIXED_PENDING, st.VALIDATED):
                i = self.store.set_status(iid, st.REJECTED, who, f"Rolled back: {d['reason']}", attempt=b["attempt"])
                self.status_event(i, who, f"Rolled back: {d['reason']}", b["attempt"])
        self.log(who, f"Rollback batch {d['batch_id']}: git checkout -- . && git clean -fd. {d['reason']}", "rollback")
        return f"batch {d['batch_id']} rolled back; unfinished issues are rejected for the next attempt", False

    def t_record_commit(self, d, who):
        b = self.batches.get(d["batch_id"], {"criterion": "", "issue_ids": []})
        for iid in b["issue_ids"]:
            if self.store.issue(iid)["status"] == st.VALIDATED:
                self.committed.add(iid)
        commits = self.store.data.get("commits") or []
        commits.append({"sha": d["sha"], "criterion": b["criterion"], "message": d["message"], "files": d.get("files", [])})
        self.store.set("commits", commits)
        self.bus.emit("commit.created", {"sha": d["sha"], "criterion": b["criterion"], "message": d["message"], "files": d.get("files", [])}, agent=who)
        self.log(who, f"Commit {d['sha']} · {d['message']}", "commit")
        return f"commit {d['sha']} recorded", False

    def t_emit_progress(self, d, who):
        kind = d.get("kind", "msg")
        if kind == "phase" and d.get("phase"):
            self.set_phase(d["phase"])
        m = d.get("metrics")
        if m and d.get("phase") in ("baseline", "reaudit"):
            self.bus.emit("baseline" if d["phase"] == "baseline" else "reaudit",
                          {"axe_violations": m.get("axe_violations", 0), "unreachable": m.get("unreachable", 0),
                           "focus_visible": m.get("focus_visible", [0, 0])})
        self.log(who, d["text"], kind)
        return "ok", False
