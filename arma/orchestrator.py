"""Persisted state machine (spec §9): crawl → baseline → audit → plan → fix → reaudit → report → pr.

Python owns the control flow; each agent role is one claude_agent_sdk.query() session restricted to
its own tools. Every visible step is emitted on the EventBus.
"""

import asyncio
import os
import re
import subprocess
from datetime import date
from pathlib import Path

from claude_agent_sdk import (TERMINAL_TASK_STATUSES, AgentDefinition, AssistantMessage, ClaudeAgentOptions,
                              HookMatcher, ResultMessage, TaskNotificationMessage, TaskStartedMessage,
                              TaskUpdatedMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage, query)

from . import agents, browser, tools
from .events import PHASES, EventBus
from .state import Store
from .tools import CTX, emit, label_of, log, path_of, url_of

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
RESUME_PREFIX = "RESUMING after an interruption: check state via tools, finish only what is missing.\n\n"
AGENT_STATUS_NAME = {"lead-auditor": "auditors"}


class BudgetExceeded(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, *, store: Store, bus: EventBus, site_dir: Path, base_url: str, work_dir: Path,
                 model: str | None = None, chaos: bool = False, budget: float | None = None,
                 until: str | None = None, site_name: str = "maison-lumiere.fr",
                 repo: str = "maison-lumiere/storefront"):
        self.store, self.bus = store, bus
        self.site_dir, self.base_url, self.work_dir = Path(site_dir).resolve(), base_url, Path(work_dir).resolve()
        self.model, self.budget, self.until = model, budget, until
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
            await getattr(self, f"phase_{phase}")()
            self.store.finish_phase(phase)
            if phase == self.until:
                log(f"Stopped after phase {phase} (--until)", "phase", "orchestrator")
                break
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
        for attempt in range(retries + 1):
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
            if attempt < retries:
                log(f"Relaunching {role} once (resume from shared state)", "msg", "orchestrator")
                attempt_prompt = RESUME_PREFIX + prompt
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
        except BudgetExceeded:
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
        tools.emit_score()
        issues = self.store.issues()
        missed = sum(1 for i in issues if i["source"] != "axe")
        funnel = {p["url"] for p in pages if p["template"] in ("product", "cart", "checkout")}
        blockers = [i["id"] for i in issues if i["severity"] == "critical" and set(i["pages"]) & funnel]
        log(f"Audit complete: {len(issues)} issues, {missed} missed by automated scanners, "
            f"{len(blockers)} purchase blockers ({', '.join(blockers) or 'none'}). Baseline score {sc['value']}.",
            "ok", "orchestrator")


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
