"""Persisted state machine (spec §9): crawl → baseline → audit → plan → fix → reaudit → report → pr.

Python owns the control flow; each agent role is one claude_agent_sdk.query() session restricted to
its own tools. Every visible step is emitted on the EventBus.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from claude_agent_sdk import (TERMINAL_TASK_STATUSES, AgentDefinition, AssistantMessage, ClaudeAgentOptions,
                              HookMatcher, ResultMessage, TaskNotificationMessage, TaskStartedMessage,
                              TaskUpdatedMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage, query)

from . import agents, browser, tools, wcag
from .templates import TEMPLATES
from .events import PHASES, EventBus
from .state import (BATCH_DONE, BATCH_ESCALATED, BATCH_IN_PROGRESS, BATCH_TODO, FIXED_PENDING, FIXING,
                    NEEDS_HUMAN, REJECTED, SEVERITIES, TODO_STATUSES, VALIDATED, Store)
from .tools import CTX, emit, label_of, log, path_of, set_status, url_of

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
RESUME_PREFIX = "RESUMING after an interruption: check state via tools, finish only what is missing.\n\n"
AGENT_STATUS_NAME = {"lead-auditor": "auditors"}


class BudgetExceeded(RuntimeError):
    pass


class InfraError(RuntimeError):
    """API unreachable: stop the run (resumable) rather than blame the agents or escalate issues."""


TRANSIENT = ("unable to connect", "ssl", "certificate", "overloaded", "529", "rate limit", "rate_limit",
             "econnreset", "timed out", "timeout", "502", "503", "504", "500 ", "connection")
BACKOFF = (5, 15, 30, 60)


class Orchestrator:
    def __init__(self, *, store: Store, bus: EventBus, site_dir: Path, base_url: str, work_dir: Path,
                 model: str | None = None, chaos: bool = False, budget: float | None = None,
                 until: str | None = None, only_batch: str | None = None, site_name: str = "maison-lumiere.fr",
                 repo: str = "maison-lumiere/storefront"):
        self.store, self.bus = store, bus
        self.site_dir, self.base_url, self.work_dir = Path(site_dir).resolve(), base_url, Path(work_dir).resolve()
        self.model, self.budget, self.until, self.only_batch = model, budget, until, only_batch
        self.site_name, self.repo = site_name, repo
        self.cost = store.get("cost_usd")
        self.env = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            self.env["ANTHROPIC_CUSTOM_HEADERS"] = f"anthropic-workspace-id: {os.environ['ANTHROPIC_WORKSPACE_ID']}"
        CTX.store, CTX.bus, CTX.base_url = store, bus, base_url
        CTX.site_dir, CTX.work_dir, CTX.chaos = self.site_dir, self.work_dir, chaos
        CTX.baseline = store.get("baseline").get("pages", {})

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        meta = self.store.get("meta")
        branch = meta.get("branch") or f"a11y/eaa-remediation-{date.today().isoformat()}"
        if not self.store.get("phases_done"):
            emit("run.started", {"site": self.site_name, "repo": self.repo, "branch": branch})
        self._status("orchestrator", "working", "coordinating run")
        log(f"Run started on {self.base_url} · model {self.model or 'default'}", "phase", "orchestrator")
        for phase in PHASES:
            if self.store.phase_done(phase):
                continue
            if not hasattr(self, f"phase_{phase}"):
                log(f"Phase {phase} not implemented yet, stopping", "err", "orchestrator")
                break
            self.store.start_phase(phase)
            emit("phase.changed", {"phase": phase})
            if await getattr(self, f"phase_{phase}")() is False:     # partial phase (--only-batch)
                log(f"Phase {phase} left open; continue with --resume", "phase", "orchestrator")
                break
            self.store.finish_phase(phase)
            if phase == self.until:
                log(f"Stopped after phase {phase} (--until)", "phase", "orchestrator")
                break
        if not self.store.phase_done("pr"):         # phase_pr already closed the run with run.finished
            self._status("orchestrator", "done", f"cost ${self.cost:.2f}")

    def _status(self, agent: str, status: str, activity: str = "") -> None:
        emit("agent.status", {"agent": AGENT_STATUS_NAME.get(agent, agent), "status": status,
                              "activity": activity})

    # ------------------------------------------------------------------ agent sessions
    async def run_agent(self, role: str, system: str, prompt: str, *, cwd: Path | None = None,
                        write_root: Path | None = None, subagents: dict[str, AgentDefinition] | None = None,
                        max_turns: int = 30, retries: int = 1, activity: str = "") -> None:
        builtin = agents.BUILTIN_TOOLS[role]
        mcp = list(agents.ROLE_TOOLS[role])
        for sub in (subagents or {}).values():
            mcp += [n for n in sub.tools or [] if n not in mcp]
        allowed = builtin + mcp
        disallowed = [n for n in tools.t(*tools.TOOL_NAMES) if n not in allowed]
        sub_labels: dict[str, str] = {}     # Agent tool_use id -> auditor·<page>
        sub_state: dict[str, str] = {}
        task_of: dict[str, str] = {}        # SDK task id -> Agent tool_use id

        async def guard(input_data, tool_use_id, context):
            name, ti = input_data.get("tool_name", ""), input_data.get("tool_input") or {}
            agent_type = input_data.get("agent_type") or role
            if name not in ("Agent", "Task"):
                who = (tools.auditor_name(ti.get("url") or ti.get("page") or "")
                       if agent_type == "page-auditor" else role)
                log(_describe(name, ti), "tool", who)
            if name in WRITE_TOOLS:
                target = Path(ti.get("file_path") or ti.get("notebook_path") or "")
                target = (Path(cwd or ".") / target).resolve() if not target.is_absolute() else target.resolve()
                if write_root is None or not target.is_relative_to(write_root):
                    log(f"Blocked write outside scope: {target}", "err", "orchestrator")
                    return {"hookSpecificOutput": {
                        "hookEventName": "PreToolUse", "permissionDecision": "deny",
                        "permissionDecisionReason": f"{role} may only write inside {write_root or 'nothing'}"}}
            return {}

        def emit_subagents():
            emit("subagents", {"agent": "auditors", "states": list(sub_state.values())})

        def finish_sub(tid: str, failed: bool):
            sub_state[tid] = "done"         # contract states are working|done; failures go to the log
            log(f"{sub_labels[tid]} {'failed' if failed else 'finished'}", "err" if failed else "ok", role)
            emit_subagents()

        attempt_prompt = prompt
        CTX.current_agent = role
        self._status(role, "working", activity or role)
        attempt, infra_waits = 0, 0
        while True:
            opts = ClaudeAgentOptions(
                system_prompt=system, mcp_servers={"a11y": tools.server()},
                tools=builtin, allowed_tools=allowed, disallowed_tools=disallowed,
                permission_mode="dontAsk", cwd=str(cwd or self.work_dir), agents=subagents,
                model=self.model, max_turns=max_turns, setting_sources=[], env=self.env,
                forward_subagent_text=True,
                hooks={"PreToolUse": [HookMatcher(hooks=[guard])]},
            )
            error: str | None = None
            over_budget = False
            try:
                async for msg in query(prompt=attempt_prompt, options=opts):
                    if isinstance(msg, AssistantMessage):
                        who = sub_labels.get(msg.parent_tool_use_id, role) if msg.parent_tool_use_id else role
                        for b in msg.content:
                            if isinstance(b, TextBlock) and b.text.strip():
                                log(_short(b.text), "msg", who)
                            elif isinstance(b, ToolUseBlock) and b.name in ("Agent", "Task"):
                                page = self._page_in(" ".join(str(v) for v in b.input.values()))
                                sub_labels[b.id] = f"auditor·{label_of(page)}"
                                sub_state[b.id] = "working"
                                log(f"Dispatching page-auditor for {path_of(page)}", "msg", role)
                                emit_subagents()
                    elif isinstance(msg, TaskStartedMessage) and msg.tool_use_id in sub_state:
                        task_of[msg.task_id] = msg.tool_use_id
                    elif isinstance(msg, (TaskNotificationMessage, TaskUpdatedMessage)):
                        # sub-agents may run asynchronously: the Agent tool result only means "launched"
                        status = msg.status or (msg.patch.get("status") if isinstance(msg, TaskUpdatedMessage) else None)
                        tid = task_of.get(msg.task_id) or getattr(msg, "tool_use_id", None)
                        if status in TERMINAL_TASK_STATUSES and sub_state.get(tid) == "working":
                            finish_sub(tid, status not in ("completed",))
                    elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                        for b in msg.content:
                            if isinstance(b, ToolResultBlock) and b.is_error and sub_state.get(b.tool_use_id) == "working":
                                finish_sub(b.tool_use_id, True)
                    elif isinstance(msg, ResultMessage):
                        self.cost = self.store.add_cost(msg.total_cost_usd or 0.0)
                        if msg.is_error:
                            error = f"{msg.subtype}: {msg.result or msg.errors or ''}"[:300]
                        if self.budget and self.cost > self.budget:
                            over_budget = True
            except Exception as e:      # CLI crash, API error...
                error = f"{type(e).__name__}: {e}"[:300]
            for tid, st in sub_state.items():     # session over: nothing can still be running
                if st == "working":
                    finish_sub(tid, bool(error))
            if over_budget:
                raise BudgetExceeded(f"cost ${self.cost:.2f} exceeds budget ${self.budget:.2f}")
            if not error:
                self._status(role, "done", activity or role)
                return
            log(f"{role} session failed: {error}", "err", "orchestrator")
            attempt_prompt = RESUME_PREFIX + prompt
            if any(k in error.lower() for k in TRANSIENT):
                if infra_waits >= len(BACKOFF):
                    self._status(role, "done", "API unreachable")
                    raise InfraError(f"API unreachable for {role}: {error}")
                wait = BACKOFF[infra_waits]
                infra_waits += 1
                log(f"API unreachable, retrying {role} in {wait}s (does not count as an attempt)", "msg",
                    "orchestrator")
                await asyncio.sleep(wait)
                continue
            if attempt >= retries:
                break
            attempt += 1
            log(f"Relaunching {role} once (resume from shared state)", "msg", "orchestrator")
        self._status(role, "done", "failed")
        raise RuntimeError(f"{role} failed after {retries + 1} attempts: {error}")

    def _page_in(self, text: str) -> str:
        pages = sorted(self.store.pages(), key=lambda p: -len(p["url"]))
        for p in pages:
            if p["url"] != "/" and p["url"] in text:
                return p["url"]
        for p in pages:
            if re.search(rf"\b{re.escape(p['label'])}\b", text):
                return p["url"]
        return "/"

    # ------------------------------------------------------------------ git
    def git(self, *args: str, check: bool = True) -> str:
        # never let git discover a parent repository (e.g. Arma's own) above the site
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(self.site_dir.parent)}
        r = subprocess.run(["git", "-c", "user.name=arma-agent", "-c", "user.email=arma@localhost", *args],
                           cwd=self.site_dir, capture_output=True, text=True, env=env)
        if check and r.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout.strip()

    def _prepare_repo(self) -> dict:
        if not (self.site_dir / ".git").exists():
            self.git("init", "-q", "-b", "main")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "Initial storefront")
        if self.git("status", "--porcelain"):
            raise RuntimeError(f"{self.site_dir} has uncommitted changes; refusing to work on a dirty repo")
        base = self.git("rev-parse", "--abbrev-ref", "HEAD")
        branch = f"a11y/eaa-remediation-{date.today().isoformat()}"
        if base == branch:
            base = "main"
        elif self.git("rev-parse", "--verify", "-q", branch, check=False):
            self.git("checkout", "-q", branch)
        else:
            self.git("checkout", "-q", "-b", branch)
        info = {"branch": branch, "base": base, "base_sha": self.git("rev-parse", base)}
        self.store.set("meta", {**self.store.get("meta"), **info})
        log(f"Working on branch {branch} (from {base})", "ok", "orchestrator")
        return info

    # ------------------------------------------------------------------ measurements
    async def measure(self, shot_prefix: str) -> dict:
        """axe + keyboard + full-page screenshot on every registered page, in parallel."""
        shots = tools.shots_dir()

        async def one(page):
            url = url_of(page["url"])
            shot = shots / f"{shot_prefix}-{page['label']}.png"
            axe, kb = await asyncio.gather(browser.axe_audit(url, screenshot_path=shot), browser.keyboard_walk(url))
            return path_of(url), {
                "keys": [[v["rule"], n["target"]] for v in axe["violations"] for n in v["nodes"]],
                "axe_violations": axe["total_nodes"], "unreachable": len(kb["unreachable"]),
                "focus_visible": kb["focus_visible"], "shot": str(shot),
            }

        per_page = dict(await asyncio.gather(*(one(p) for p in self.store.pages())))
        totals = {
            "axe_violations": sum(p["axe_violations"] for p in per_page.values()),
            "unreachable": sum(p["unreachable"] for p in per_page.values()),
            "focus_visible": [sum(p["focus_visible"][0] for p in per_page.values()),
                              sum(p["focus_visible"][1] for p in per_page.values())],
        }
        return {"pages": per_page, "totals": totals}

    # ------------------------------------------------------------------ phases
    async def phase_crawl(self) -> None:
        log("Mapping the store and its purchase funnel", "phase", "orchestrator")
        try:
            await self.run_agent("cartographer", agents.CARTOGRAPHER,
                                 f"Map the store at {self.base_url}. Register the pages to audit.",
                                 max_turns=20, activity="crawl_site")
        except (BudgetExceeded, InfraError):
            raise
        except Exception as e:
            log(f"Cartographer unavailable ({e}); falling back to a plain crawl", "err", "orchestrator")
        if not self.store.pages():
            for p in await browser.crawl(self.base_url):
                path = path_of(p["url"])
                label = "home" if path == "/" else Path(path).stem
                self.store.add_page(path, p["title"], label, label)
            log(f"Fallback crawl registered {len(self.store.pages())} pages", "ok", "orchestrator")
        log(f"{len(self.store.pages())} pages to audit: "
            + ", ".join(p["url"] for p in self.store.pages()), "ok", "cartographer")

    async def phase_baseline(self) -> None:
        log("Baseline measurements: scanner, keyboard, screenshots", "phase", "orchestrator")
        self._status("orchestrator", "working", "baseline measurements")
        self._prepare_repo()
        m = await self.measure("before")
        self.store.set("baseline", m)
        CTX.baseline = m["pages"]
        emit("baseline", m["totals"])
        t = m["totals"]
        log(f"Baseline: {t['axe_violations']} scanner violations, {t['unreachable']} controls unreachable by "
            f"keyboard, visible focus on {t['focus_visible'][0]}/{t['focus_visible'][1]} tab stops",
            "ok", "orchestrator")

    async def phase_audit(self) -> None:
        log("Parallel audit: one page-auditor per page", "phase", "orchestrator")
        pages = self.store.pages()
        await self.run_agent(
            "lead-auditor", agents.LEAD_AUDITOR,
            f"Audit the {len(pages)} registered pages of the store at {self.base_url}: "
            + ", ".join(f"{p['url']} (template: {p['template']})" for p in pages),
            subagents=agents.audit_subagents(self.model), max_turns=30, activity="dispatching page auditors")
        self.store.freeze_score()
        sc = self.store.score()
        self.store.set("meta", {**self.store.get("meta"), "baseline_score": sc["value"]})
        tools.emit_score(force=True)
        issues = self.store.issues()
        missed = sum(1 for i in issues if i["source"] != "axe")
        funnel = {p["url"] for p in pages if p["template"] in ("product", "cart", "checkout")}
        blockers = [i["id"] for i in issues if i["severity"] == "critical" and set(i["pages"]) & funnel]
        log(f"Audit complete: {len(issues)} issues, {missed} missed by automated scanners, "
            f"{len(blockers)} purchase blockers ({', '.join(blockers) or 'none'}). Baseline score {sc['value']}.",
            "ok", "orchestrator")

    # ------------------------------------------------------------------ plan / fix
    async def phase_plan(self) -> None:
        log("Planning: one batch per WCAG criterion, purchase blockers first", "phase", "orchestrator")
        groups: dict[str, list[dict]] = {}
        for i in self.store.issues():
            groups.setdefault(i["wcag"], []).append(i)

        def rank(crit: str):
            sev = min(SEVERITIES.index(i["severity"]) for i in groups[crit])
            return sev, [int(x) for x in crit.split(".")]

        batches = []
        for n, crit in enumerate(sorted(groups, key=rank), 1):
            ids = [i["id"] for i in groups[crit]]
            batches.append({"id": f"B{n:02d}", "criterion": crit, "issue_ids": ids, "status": BATCH_TODO,
                            "attempt": 0, "commits": []})
            log(f"Batch B{n:02d} · WCAG {crit} {wcag.name(crit)}: {', '.join(ids)}", "msg", "orchestrator")
        self.store.set("batches", batches)
        log(f"{len(batches)} batches planned for {sum(len(b['issue_ids']) for b in batches)} issues", "ok",
            "orchestrator")

    async def phase_fix(self) -> bool:
        log("Fix and verify: developer ⇄ independent tester, one batch at a time", "phase", "orchestrator")
        if self.git("status", "--porcelain"):          # interrupted mid-batch: replay it from committed code
            self._discard("Discarded uncommitted changes from an interrupted batch")
        for b in self.store.get("batches"):
            if b["status"] in (BATCH_DONE, BATCH_ESCALATED):
                continue
            if self.only_batch and b["criterion"] != self.only_batch and b["id"] != self.only_batch:
                continue
            await self._fix_batch(b["id"])
        if self.only_batch:
            return False
        self._status("developer", "done", "all batches done")
        self._status("tester", "done", "all batches verified")
        return True

    def _batch(self, bid: str) -> dict:
        return next(b for b in self.store.get("batches") if b["id"] == bid)

    def _save_batch(self, batch: dict) -> None:
        self.store.set("batches", [batch if b["id"] == batch["id"] else b for b in self.store.get("batches")])

    def _discard(self, why: str, kind: str = "msg") -> None:
        self.git("checkout", "--", ".")
        self.git("clean", "-fdq")
        log(why, kind, "orchestrator")

    async def _fix_batch(self, bid: str) -> None:
        b = self._batch(bid)
        crit = b["criterion"]
        b["status"] = BATCH_IN_PROGRESS
        self._save_batch(b)
        while b["attempt"] < 3:
            todo = [i["id"] for i in self.store.issues() if i["id"] in b["issue_ids"] and i["status"] in TODO_STATUSES]
            if not todo:
                break
            b["attempt"] += 1
            CTX.attempt = b["attempt"]
            self._save_batch(b)
            emit("batch.started", {"id": bid, "criterion": crit, "issue_ids": todo, "attempt": b["attempt"]})
            log(f"Batch {bid} · WCAG {crit} {wcag.name(crit)} · attempt {b['attempt']}: {', '.join(todo)}",
                "phase", "orchestrator")
            self._status("tester", "idle", "waiting")
            for iid in todo:
                set_status(iid, FIXING, "orchestrator", "Assigned to developer", attempts=b["attempt"])

            # reference screenshots of the committed code, so the tester sees only this batch's changes
            issues = [self.store.issue(i) for i in todo]
            pages = sorted({p for i in issues for p in i["pages"]})
            shots = tools.shots_dir()
            refs = await asyncio.gather(*(browser.screenshot(
                url_of(p), shots / f"ref-{label_of(p)}-{bid}-{b['attempt']}.png") for p in pages))
            CTX.ref_shots = dict(zip(pages, refs))

            # developer
            try:
                await self.run_agent("developer", agents.DEVELOPER, self._developer_prompt(b, issues),
                                     cwd=self.site_dir, write_root=self.site_dir, max_turns=40,
                                     activity=f"WCAG {crit}")
            except (BudgetExceeded, InfraError):
                b["attempt"] -= 1           # interrupted attempt is replayed on --resume
                self._save_batch(b)
                raise
            except Exception as e:
                log(f"Developer session lost: {e}", "err", "orchestrator")
            for iid in todo:
                if self.store.issue(iid)["status"] == FIXING:
                    set_status(iid, REJECTED, "orchestrator", "Not handled by the developer")
            pending = [i for i in todo if self.store.issue(i)["status"] == FIXED_PENDING]
            for iid in pending:
                files = self.store.issue(iid)["files"]
                diff = self.git("diff", "--", *files, check=False) if files else ""
                self.store.update_issue(iid, fix_diff=(diff or self.git("diff", check=False))[:6000])

            # independent tester
            if pending:
                CTX.batch_verdict = None
                try:
                    await self.run_agent("tester", agents.TESTER, self._tester_prompt(b, pending),
                                         cwd=self.site_dir, write_root=None, max_turns=40,
                                         activity=f"verifying WCAG {crit}")
                except (BudgetExceeded, InfraError):
                    b["attempt"] -= 1           # interrupted attempt is replayed on --resume
                    self._save_batch(b)
                    raise
                except Exception as e:
                    log(f"Tester session lost: {e}", "err", "orchestrator")
                for iid in pending:
                    if self.store.issue(iid)["status"] == FIXED_PENDING:
                        set_status(iid, REJECTED, "orchestrator", "No verdict from the tester")
                bv = CTX.batch_verdict or {"accepted": True, "reason": ""}
                if not bv["accepted"]:
                    self._discard(f"Rollback of batch {bid} (WCAG {crit}): {bv['reason']}", "rollback")
                    for iid in todo:
                        if self.store.issue(iid)["status"] in (VALIDATED, FIXED_PENDING):
                            set_status(iid, REJECTED, "orchestrator", f"Batch rolled back: {bv['reason']}")
                    continue

            validated = [i for i in todo if self.store.issue(i)["status"] == VALIDATED]
            if validated and self.git("status", "--porcelain"):
                self._commit(b, validated)
            elif self.git("status", "--porcelain") and not validated:
                self._discard(f"No fix verified in batch {bid}; unverified changes discarded")

        remaining = [i["id"] for i in self.store.issues() if i["id"] in b["issue_ids"] and i["status"] in TODO_STATUSES]
        for iid in remaining:
            last = next((h["note"] for h in reversed(self.store.issue(iid)["history"]) if h["status"] == REJECTED), "")
            note = f"Not verified after {b['attempt']} attempts. Last tester feedback: {last}"
            set_status(iid, NEEDS_HUMAN, "orchestrator", note, human_action="Front-end developer: " + note)
        if self.git("status", "--porcelain"):
            self._discard("Discarded unverified changes left by the batch")
        b["status"] = BATCH_ESCALATED if remaining else BATCH_DONE
        self._save_batch(b)
        CTX.attempt = 0
        log(f"Batch {bid} {'escalated to a human' if remaining else 'done'}", "err" if remaining else "ok",
            "orchestrator")

    def _commit(self, b: dict, validated: list[str]) -> None:
        titles = "; ".join(self.store.issue(i)["title"] for i in validated)
        message = f"fix(a11y): WCAG {b['criterion']} — {titles}"
        if len(message) > 120:
            message = message[:119] + "…"
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        sha = self.git("rev-parse", "--short=7", "HEAD")
        files = self.git("show", "--name-only", "--format=", "HEAD").splitlines()
        b["commits"].append(sha)
        self._save_batch(b)
        emit("commit.created", {"sha": sha, "criterion": b["criterion"], "message": message, "files": files})
        log(f"Committed {sha} {message}", "commit", "orchestrator")

    def _developer_prompt(self, b: dict, issues: list[dict]) -> str:
        brief = [{k: i[k] for k in ("id", "title", "impact", "evidence", "selector", "pages", "severity")}
                 for i in issues]
        rejections = []
        for i in issues:
            for h in i["history"]:
                if h["status"] == REJECTED:
                    rejections.append(f"- {i['id']} (attempt {h.get('attempt', '?')}, {h['by']}): {h['note']}")
        out = (f"Batch {b['id']} · WCAG {b['criterion']} {wcag.name(b['criterion'])} · attempt {b['attempt']}.\n"
               f"The store is served from your working directory at {self.base_url} "
               f"(page \"/\" is index.html).\n\nIssues:\n{json.dumps(brief, ensure_ascii=False, indent=1)}\n")
        if rejections:
            out += "\nPREVIOUS TESTER REJECTIONS (fix exactly these):\n" + "\n".join(rejections) + "\n"
        return out

    def _tester_prompt(self, b: dict, pending: list[str]) -> str:
        items = []
        for iid in pending:
            i = self.store.issue(iid)
            items.append({k: i[k] for k in ("id", "title", "wcag", "selector", "pages", "evidence", "fix_note", "files")})
        pages = sorted({p for it in items for p in it["pages"]})
        return (f"Verify batch {b['id']} · WCAG {b['criterion']} {wcag.name(b['criterion'])} · attempt {b['attempt']}.\n"
                f"Store: {self.base_url}. Pages to check: {', '.join(pages)}.\n"
                f"Issues declared fixed (original evidence = the code before the fix):\n"
                f"{json.dumps(items, ensure_ascii=False, indent=1)}\n"
                "Give a verdict for every issue, then a batch_verdict.")

    # ------------------------------------------------------------------ reaudit / report / pr
    async def phase_reaudit(self) -> None:
        log("Re-audit: same measurements on the remediated store", "phase", "orchestrator")
        self._status("orchestrator", "working", "final measurements")
        m = await self.measure("after")
        self.store.set("final", m)
        emit("reaudit", m["totals"])
        b, a = self.store.get("baseline")["totals"], m["totals"]
        log(f"Scanner violations {b['axe_violations']} → {a['axe_violations']}, unreachable controls "
            f"{b['unreachable']} → {a['unreachable']}, visible focus {b['focus_visible'][0]}/{b['focus_visible'][1]} → "
            f"{a['focus_visible'][0]}/{a['focus_visible'][1]}", "ok", "orchestrator")

    def _summary(self) -> dict:
        meta, sc = self.store.get("meta"), self.store.score()
        commits = [{"sha": c.split(" ", 1)[0], "message": c.split(" ", 1)[1]}
                   for c in self.git("log", "--format=%h %s", f"{meta['base']}..HEAD").splitlines()][::-1]
        return {
            "site": self.site_name, "repo": self.repo, "branch": meta.get("branch"), "base": meta.get("base"),
            "date": date.today().isoformat(), "pages": [p["url"] for p in self.store.pages()],
            "score": {"before": meta.get("baseline_score"), "after": sc["value"], "eaa_status": sc["eaa"]},
            "metrics": {"before": self.store.get("baseline").get("totals"),
                        "after": self.store.get("final").get("totals")},
            "issues": [{k: i[k] for k in ("id", "wcag", "criterion_name", "level", "en301549", "title", "severity",
                                          "source", "pages", "status", "fix_note", "human_action", "attempts")}
                       for i in self.store.issues()],
            "commits": commits,
        }

    async def phase_report(self) -> None:
        log("Writing the pull request and the accessibility statement", "phase", "orchestrator")
        out = self.work_dir / "out"
        out.mkdir(parents=True, exist_ok=True)
        summary = self._summary()
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        names = ("pr-body.md", "accessibility-statement.md")
        for n in names:
            (out / n).unlink(missing_ok=True)
        try:
            await self.run_agent(
                "writer", agents.WRITER,
                f"Output directory: {out}\nWrite pr-body.md and accessibility-statement.md there.\n\n"
                f"Run summary:\n{json.dumps(summary, ensure_ascii=False, indent=1)}",
                cwd=out, write_root=out, max_turns=12, activity="writing")
        except (BudgetExceeded, InfraError):
            raise
        except Exception as e:
            log(f"Writer unavailable ({e})", "err", "orchestrator")
        for n in names:
            f = out / n
            if not f.exists() or len(f.read_text(encoding="utf-8").strip()) < 200:
                f.write_text(TEMPLATES[n](summary), encoding="utf-8")
                log(f"{n} generated from the deterministic template (writer fallback)", "msg", "orchestrator")
            emit("document.written", {"name": n, "path": f"state/out/{n}", "content": f.read_text(encoding="utf-8")},
                 "writer")
        log("Documents ready: pr-body.md, accessibility-statement.md", "ok", "writer")

    async def phase_pr(self) -> None:
        log("Preparing the pull request", "phase", "orchestrator")
        meta, out = self.store.get("meta"), self.work_dir / "out"
        rng = f"{meta['base']}..HEAD"
        (out / "changes.diff").write_text(self.git("diff", rng) + "\n", encoding="utf-8")
        patches = out / "patches"
        shutil.rmtree(patches, ignore_errors=True)
        self.git("format-patch", "-q", rng, "-o", str(patches))
        commits = int(self.git("rev-list", "--count", rng))
        files = self.git("diff", "--name-only", rng).splitlines()
        body = (out / "pr-body.md").read_text(encoding="utf-8")
        ev = self.bus.emit("pr.ready", {"repo": self.repo, "branch": meta["branch"], "base": meta["base"],
                                        "commits": commits, "files": files, "body": body})
        log(f"Pull request ready: {commits} commits on {meta['branch']}, {len(files)} files. "
            "Waiting for compliance sign-off.", "ok", "orchestrator")
        self._status("orchestrator", "done", "PR ready")
        emit("run.finished", {"cost_usd": round(self.cost, 4), "duration_s": ev["t"]})


# ---------------------------------------------------------------------- log helpers

def _short(text: str, n: int = 280) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _describe(name: str, ti: dict) -> str:
    short = name.removeprefix("mcp__a11y__")
    arg = ti.get("url") or ti.get("page") or ti.get("issue_id") or ti.get("pattern") or ""
    if ti.get("file_path"):
        arg = Path(ti["file_path"]).name
    if short == "add_issue":
        arg = f"{ti.get('wcag', '')} {ti.get('title', '')}"
    if short in ("verdict", "batch_verdict"):
        arg = f"{ti.get('issue_id', 'batch')} accepted={ti.get('accepted')}"
    return _short(f"{short}({arg})", 160)
