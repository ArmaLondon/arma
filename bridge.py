"""Arma bridge: runs one Claude Managed Agents session and keeps the compliance ledger (arma-spec.md §13).

usage:
  python bridge.py run [--until audit] [--smoke] [--budget-cents 3000] [--model-override claude-sonnet-5-5]
  python bridge.py resume <session_id>

The hosted team (lead + page auditors, developer, tester, writer) works in the cloud sandbox. Every
finding and status change arrives here as a custom tool call; the bridge answers it (ledger), turns
Managed Agents events into the dashboard event contract, records recordings/run-<date>.jsonl,
then downloads /mnt/session/outputs and emits the documents, the PR and the eval.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from arma.config import load_env  # noqa: E402

load_env()
import anthropic  # noqa: E402

from arma.events import EventBus  # noqa: E402
from arma.state import Store  # noqa: E402
from arma_bridge.custom_tools import Ledger  # noqa: E402

LOCK = json.loads((ROOT / "claude-lock.json").read_text())
OUT = ROOT / "state" / "out"
SITE = "maison-lumiere.fr"
ROLE_OF = {"arma-page-auditor": "auditors", "arma-developer": "developer", "arma-tester": "tester", "arma-writer": "writer", "arma-lead": "lead"}
LABEL_OF = {"arma-page-auditor": "auditor", "arma-developer": "developer", "arma-tester": "tester", "arma-writer": "writer", "arma-lead": "lead"}
SMOKE = """SMOKE TEST ONLY (do not start the full protocol, do not delegate):
1. mkdir -p /workspace/site /workspace/arma/tools; extract /mnt/session/uploads/demo-shop.tgz to /workspace/site and /mnt/session/uploads/tools.tgz to /workspace/arma/tools.
2. Run: which chromium chromium-browser; ls /usr/bin | grep -i chrom; python -c "import playwright; print('playwright ok')".
3. cd /workspace/site && nohup python -m http.server 8765 >/dev/null 2>&1 & sleep 1
4. cd /workspace/arma/tools && python crawl.py http://127.0.0.1:8765/index.html && python audit.py http://127.0.0.1:8765/index.html
5. Write a JSON with the outputs of steps 2 and 4 to /mnt/session/outputs/smoke.json and call emit_progress with a one-line result. Then end your turn."""


def tgz(src: Path, skip=("__pycache__",)) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p in sorted(src.rglob("*")):
            if p.is_file() and not any(s in p.parts for s in skip):
                t.add(p, arcname=str(p.relative_to(src)))
    return buf.getvalue()


def g(obj, *names, default=None):
    for n in names:
        if obj is None:
            return default
        obj = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
    return default if obj is None else obj


def text_of(content) -> str:
    parts = []
    for b in content or []:
        t = g(b, "text")
        if t:
            parts.append(t)
    return " ".join(parts).strip()


class Run:
    def __init__(self, client, session_id: str, bus: EventBus, store: Store, outcome: bool):
        self.client, self.sid, self.bus, self.store = client, session_id, bus, store
        self.ledger = Ledger(store, bus)
        self.seen: set[str] = set()
        self.threads: dict[str, str] = {}       # thread id -> agent name
        self.aud_threads: list[str] = []
        self.thread_state: dict[str, str] = {}
        self.outcome_expected = outcome
        self.outcome_terminal = False
        self.idle_end_since = None
        self.done = False
        self.stop_reason = ""

    # ------------------------------------------------ helpers
    def log(self, agent, text, kind="msg"):
        self.bus.emit("log", {"text": text[:600], "kind": kind}, agent=agent)

    def status(self, role, s, activity=None):
        d = {"agent": role, "status": s}
        if activity is not None:
            d["activity"] = activity[:120]
        self.bus.emit("agent.status", d)

    def subagents(self):
        self.bus.emit("subagents", {"agent": "auditors", "states": [self.thread_state.get(t, "working") for t in self.aud_threads]})

    def label(self, ev) -> str:
        tid = g(ev, "session_thread_id")
        name = self.threads.get(tid, "arma-lead") if tid else "arma-lead"
        return LABEL_OF.get(name, name)

    def reply(self, ev, text, is_error=False):
        evt = {"type": "user.custom_tool_result", "custom_tool_use_id": ev.id, "content": [{"type": "text", "text": text}]}
        if is_error:
            evt["is_error"] = True
        try:
            self.client.beta.sessions.events.send(session_id=self.sid, events=[evt])
        except anthropic.BadRequestError as e:
            self.log("system", f"tool result refused by the server: {e.message[:200]}", "err")

    # ------------------------------------------------ event translation
    def handle(self, ev):
        eid = g(ev, "id")
        if eid in self.seen:
            return
        if eid:
            self.seen.add(eid)
        t = ev.type
        if t == "agent.custom_tool_use":
            text, err = self.ledger.handle(ev.name, dict(ev.input or {}), self.label(ev))
            self.reply(ev, text, err)
            if err:
                self.log(self.label(ev), f"{ev.name} refused by the ledger: {text[:200]}", "err")
        elif t == "agent.message":
            txt = text_of(ev.content)
            if txt:
                self.log(self.label(ev), txt, "msg")
                self.status(ROLE_OF.get(self.threads.get(g(ev, "session_thread_id"), "arma-lead"), "lead"), "working", txt)
        elif t == "agent.tool_use":
            inp = dict(g(ev, "input") or {})
            arg = inp.get("command") or inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
            self.log(self.label(ev), f"→ {ev.name} {str(arg).splitlines()[0][:160] if arg else ''}".strip(), "tool")
        elif t == "agent.tool_result" and g(ev, "is_error"):
            self.log(self.label(ev), f"tool error: {text_of(g(ev, 'content'))[:240]}", "err")
        elif t == "session.thread_created":
            tid, name = g(ev, "session_thread_id"), g(ev, "agent_name", default="")
            self.threads[tid] = name
            role = ROLE_OF.get(name, name)
            if role == "auditors":
                self.aud_threads.append(tid)
                self.thread_state[tid] = "working"
                self.subagents()
                self.status("auditors", "working", f"{len(self.aud_threads)} parallel threads")
            self.log("lead", f"thread started: {name}", "tool")
        elif t in ("session.thread_status_running", "session.thread_status_idle"):
            tid, name = g(ev, "session_thread_id"), g(ev, "agent_name", default="")
            role = ROLE_OF.get(name)
            if not role or role == "lead":
                return
            running = t.endswith("running")
            if role == "auditors" and tid in self.thread_state:
                self.thread_state[tid] = "working" if running else "done"
                self.subagents()
                if all(v == "done" for v in self.thread_state.values()):
                    self.status("auditors", "done", f"{len(self.aud_threads)} pages audited")
            else:
                self.status(role, "working" if running else "idle")
        elif t == "agent.thread_message_sent":
            to = g(ev, "to_agent_name", default="")
            self.log("lead", f"→ {LABEL_OF.get(to, to)}: {text_of(g(ev, 'content'))[:220]}", "msg")
        elif t == "agent.thread_message_received":
            fr = g(ev, "from_agent_name", default="")
            self.log(LABEL_OF.get(fr, fr), f"report to lead: {text_of(g(ev, 'content'))[:300]}", "msg")
        elif t == "span.outcome_evaluation_start":
            self.log("system", f"Independent grader: evaluating the outcome rubric (iteration {g(ev, 'iteration', default=0)})", "phase")
        elif t == "span.outcome_evaluation_end":
            res, it = g(ev, "result", default=""), g(ev, "iteration", default=0)
            expl = g(ev, "explanation", default="")
            self.bus.emit("outcome", {"iteration": it, "result": res, "explanation": expl})
            self.log("system", f"Grader: {res.replace('_', ' ')}. {expl[:300]}", "ok" if res == "satisfied" else "reject")
            if res in ("satisfied", "max_iterations_reached", "failed", "interrupted"):
                self.outcome_terminal = True
        elif t == "session.error":
            err = g(ev, "error")
            self.log("system", f"session error: {g(err, 'message', default=str(err))[:300]} (retry: {g(ev, 'retry_status', 'type', default='none')})", "err")
        elif t == "session.status_idle":
            sr = g(ev, "stop_reason", "type", default="")
            self.stop_reason = sr
            if sr == "requires_action":
                return
            if sr in ("budget_reached", "retries_exhausted"):
                self.log("system", f"session paused: {sr}. Resume with: python bridge.py resume {self.sid}", "err")
                self.done = True
            elif sr == "end_turn":
                if self.outcome_terminal or not self.outcome_expected:
                    self.done = True
                else:
                    self.idle_end_since = self.idle_end_since or time.monotonic()
        elif t == "session.status_running":
            self.idle_end_since = None
        elif t == "session.status_terminated":
            self.done = True

    # ------------------------------------------------ stream with reconnect
    def drain(self):
        while not self.done:
            try:
                with self.client.beta.sessions.events.stream(session_id=self.sid) as stream:
                    self.catch_up()
                    for ev in stream:
                        self.handle(ev)
                        if self.done:
                            break
                        if self.idle_end_since and time.monotonic() - self.idle_end_since > 180:
                            self.log("system", "no grader result after the final turn; finishing.", "err")
                            self.done = True
                            break
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 — any transport failure: the session keeps running server-side
                self.log("system", f"stream dropped ({type(e).__name__}); reconnecting, the session keeps running server-side", "err")
                time.sleep(2)

    def catch_up(self):
        """After a (re)connect, process events we have not seen yet (dedup by event id)."""
        try:
            page = self.client.beta.sessions.events.list(session_id=self.sid)
            for ev in page:
                self.handle(ev)
        except Exception as e:  # noqa: BLE001
            self.log("system", f"history catch-up failed: {e}", "err")


def finish(client, run: Run, branch: str, t0: float):
    OUT.mkdir(parents=True, exist_ok=True)
    files = []
    for attempt in range(5):
        try:
            files = list(client.beta.files.list(scope_id=run.sid, betas=["managed-agents-2026-04-01"]))
        except Exception as e:  # noqa: BLE001
            run.log("system", f"listing outputs failed: {e}", "err")
        if files:
            break
        time.sleep(3)
    got = 0
    for f in files:
        name = g(f, "filename", default=f.id)
        if name in ("demo-shop.tgz", "tools.tgz", "rubric.md"):
            continue  # our own inputs, mounted read-only
        dest = OUT / name.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.beta.files.download(f.id).write_to_file(str(dest))
            got += 1
        except anthropic.BadRequestError:
            pass  # not an output file
    run.log("lead", f"Downloaded {got} output files to state/out/", "ok")
    for name in ("pr-body.md", "accessibility-statement.md"):
        hits = list(OUT.rglob(name))
        if hits:
            run.bus.emit("document.written", {"name": name, "path": f"state/out/{name}", "content": hits[0].read_text()}, agent="writer")
    commits = run.store.data.get("commits") or []
    if commits:
        run.bus.emit("phase.changed", {"phase": "pr"})
    body = next((p.read_text() for p in OUT.rglob("pr-body.md")), "")
    files_changed = sorted({f for c in commits for f in c.get("files", [])})
    if commits:
        run.bus.emit("pr.ready", {"repo": "maison-lumiere/storefront", "branch": branch, "base": "main",
                                  "commits": len(commits), "files": files_changed, "body": body})
        run.log("lead", f"Pull request ready: {len(commits)} commits on {branch}. Waiting for compliance sign-off.", "ok")
    # eval against the ground truth, when available
    ev_script = ROOT / "eval" / "run_eval.py"
    if ev_script.exists():
        try:
            r = subprocess.run([sys.executable, str(ev_script), str(run.store.path), "--json"], capture_output=True, text=True, timeout=120)
            res = json.loads(r.stdout.strip().splitlines()[-1])
            run.bus.emit("eval", res)
            run.log("system", f"Eval against ground truth: {'PASS' if res.get('passed') else 'FAIL'} " +
                    ", ".join(f"{k}={v}" for k, v in res.get("metrics", {}).items()), "ok" if res.get("passed") else "reject")
        except Exception as e:  # noqa: BLE001
            run.log("system", f"eval failed to run: {e}", "err")
    cost = 0.0
    try:
        s = client.beta.sessions.retrieve(session_id=run.sid)
        lc = g(s, "usage", "list_cost")
        amt = g(lc, "amount")
        cost = round(int(amt) / 100, 2) if amt is not None and str(amt).isdigit() else float(g(lc, "value", default=0) or 0)
    except Exception:  # noqa: BLE001
        pass
    for role in ("lead", "auditors", "developer", "tester", "writer"):
        run.status(role, "done")
    run.bus.emit("run.finished", {"cost_usd": cost, "duration_s": round(time.monotonic() - t0)})


def cmd_run(a):
    client = anthropic.Anthropic()
    import shutil
    shutil.rmtree(OUT, ignore_errors=True)  # outputs of this run only
    date = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"a11y/eaa-remediation-{dt.date.today().isoformat()}"
    up = []
    for name, data in (("demo-shop.tgz", tgz(ROOT / "demo-shop")), ("tools.tgz", tgz(ROOT / "sandbox_tools"))):
        f = client.files.upload(file=(name, data, "application/gzip"))
        up.append((name, f.id))
    rubric = client.files.upload(file=("rubric.md", (ROOT / "managed" / "rubric.md").read_bytes(), "text/markdown"))
    lead = LOCK["agents"]["lead"]
    agent = ({"type": "agent_with_overrides", "id": lead["id"], "version": lead["version"], "model": a.model_override}
             if a.model_override else {"type": "agent", "id": lead["id"], "version": lead["version"]})
    session = client.beta.sessions.create(
        agent=agent, environment_id=LOCK["environment"]["id"], title=f"Arma run {date}",
        resources=[{"type": "file", "file_id": fid, "mount_path": "/" + name} for name, fid in up] +
                  [{"type": "file", "file_id": rubric.id, "mount_path": "/rubric.md"}],
        budget={"type": "limit", "max_list_cost": {"amount": str(a.budget_cents), "currency": "USD"}},
    )
    print(f"session {session.id}  https://platform.claude.com/workspaces/default/sessions/{session.id}", flush=True)
    rec = ROOT / "recordings" / f"run-{date}{'-smoke' if a.smoke else ''}.jsonl"
    bus = EventBus(rec)
    store = Store(ROOT / "state" / "state.json", reset=True)
    store.set("session_id", session.id)
    t0 = time.monotonic()
    bus.emit("run.started", {"site": SITE, "repo": "maison-lumiere/storefront", "branch": branch, "session_id": session.id})
    bus.emit("phase.changed", {"phase": "crawl"})
    bus.emit("agent.status", {"agent": "lead", "status": "working", "activity": "starting the hosted session"})
    bus.emit("log", {"text": f"Session started on Claude Managed Agents ({session.id[-8:]}). Store served in the sandbox at http://127.0.0.1:8765/", "kind": "phase"}, agent="lead")
    until = ""
    if a.until:
        until = f"- STOP after the '{a.until}' phase (for audit: after plan_batches). Then end your turn."
    brief = SMOKE if a.smoke else (ROOT / "managed" / "prompts" / "brief.md").read_text().format(site=SITE, branch=branch, until=until)
    events = [{"type": "user.message", "content": [{"type": "text", "text": brief}]}]
    outcome = not a.smoke and not a.until
    if outcome:
        events.append({"type": "user.define_outcome",
                       "description": "Remediate maison-lumiere storefront accessibility to WCAG 2.1 AA and deliver a verified PR package",
                       "rubric": {"type": "file", "file_id": rubric.id}, "max_iterations": 3})
    run = Run(client, session.id, bus, store, outcome)
    # stream first, then send
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(session_id=session.id, events=events)
        try:
            for ev in stream:
                run.handle(ev)
                if run.done:
                    break
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            run.log("system", f"stream dropped ({type(e).__name__}); reconnecting", "err")
    run.drain()
    finish(client, run, branch, t0)
    print(f"recording: {rec}", flush=True)


def cmd_resume(a):
    """Reattach to a running session after the bridge stopped. With --recording, keep appending to the
    same JSONL (clock continued); history already recorded is marked seen, pending custom tool calls are
    answered, and outcome results that arrived meanwhile are translated."""
    client = anthropic.Anthropic()
    if a.recording:
        rec = Path(a.recording)
        last_t = max(json.loads(l)["t"] for l in rec.read_text().splitlines() if l.strip())
        gap = max(0.0, time.time() - rec.stat().st_mtime)
    else:
        rec = ROOT / "recordings" / f"run-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-resume.jsonl"
        last_t, gap = 0.0, 0.0
    bus = EventBus(rec)
    bus._t0 = time.monotonic() - last_t - gap
    store = Store(ROOT / "state" / "state.json")
    run = Run(client, a.session_id, bus, store, outcome=True)
    run.log("system", f"Bridge reattached to session {a.session_id[-8:]}: the session kept running server-side; catching up", "phase")
    history = list(client.beta.sessions.events.list(session_id=a.session_id))
    answered = {g(e, "custom_tool_use_id") for e in history if e.type == "user.custom_tool_result"}
    replay_types = {"span.outcome_evaluation_start", "span.outcome_evaluation_end", "session.status_idle", "session.status_running", "session.status_terminated"}
    started = any(e.type == "span.outcome_evaluation_start" for e in history)
    for e in history:
        if (e.type == "agent.custom_tool_use" and e.id not in answered) or e.type in replay_types:
            if e.type == "span.outcome_evaluation_start" and started and a.recording:
                run.seen.add(e.id)   # already logged before the drop
                continue
            run.handle(e)
        else:
            run.seen.add(g(e, "id"))
    if not run.done:
        run.drain()
    branch = json.loads(rec.read_text().splitlines()[0])["data"].get("branch", "") if a.recording else f"a11y/eaa-remediation-{dt.date.today().isoformat()}"
    finish(client, run, branch, time.monotonic() - last_t - gap)
    print(f"recording: {rec}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--until", choices=["crawl", "baseline", "audit", "fix", "reaudit"], default=None)
    r.add_argument("--smoke", action="store_true")
    r.add_argument("--budget-cents", type=int, default=3000)
    r.add_argument("--model-override", default="")
    s = sub.add_parser("resume")
    s.add_argument("session_id")
    s.add_argument("--recording", default="", help="continue this JSONL instead of starting a new one")
    a = ap.parse_args()
    cmd_run(a) if a.cmd == "run" else cmd_resume(a)


if __name__ == "__main__":
    main()
