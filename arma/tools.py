"""In-process MCP tools (spec §8). The only way agents read or change the shared state.

Every tool that changes state emits the matching event. Errors never raise: they return an
actionable message with is_error=True so the agent can recover.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import browser
from .events import EventBus
from .state import (FIXED_PENDING, FIXING, NEEDS_HUMAN, REJECTED, SEVERITIES, SOURCES, VALIDATED, Store)


@dataclass
class Ctx:
    store: Store | None = None
    bus: EventBus | None = None
    base_url: str = ""
    site_dir: Path | None = None
    work_dir: Path | None = None            # state/ (shots/, out/)
    chaos: bool = False
    chaos_fired: bool = False
    batch_verdict: dict | None = None
    current_agent: str = "orchestrator"
    attempt: int = 0
    baseline: dict = field(default_factory=dict)    # url -> {"keys": [[rule, target]], "shot": path}
    ref_shots: dict = field(default_factory=dict)   # url -> screenshot of the committed code at batch start
    compare_n: int = 0
    last_score: dict | None = None


CTX = Ctx()


# ------------------------------------------------------------------ helpers

def _ok(payload: Any) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def emit(type_: str, data: dict, agent: str | None = None) -> None:
    if CTX.bus:
        CTX.bus.emit(type_, data, agent)


def log(text: str, kind: str = "msg", agent: str | None = None) -> None:
    emit("log", {"text": text, "kind": kind}, agent or CTX.current_agent)


def path_of(url_or_page: str) -> str:
    """Any page reference (full URL, path, template label) → site path like "/product.html"."""
    ref = (url_or_page or "").strip()
    if CTX.store:
        for p in CTX.store.pages():
            if ref in (p["url"], p["label"], p["template"]):
                ref = p["url"]
                break
    path = urlparse(urljoin(CTX.base_url, ref)).path or "/"
    return "/" if path.endswith("/index.html") else path


def url_of(url_or_page: str) -> str:
    return urljoin(CTX.base_url, path_of(url_or_page).lstrip("/"))


def label_of(url_or_page: str) -> str:
    path = path_of(url_or_page)
    if CTX.store:
        for p in CTX.store.pages():
            if path_of(p["url"]) == path and p["label"]:
                return p["label"]
    return "home" if path == "/" else Path(path).stem


def auditor_name(url_or_page: str) -> str:
    """Tools called by page-auditors are attributed to auditor·<page>."""
    if CTX.current_agent in ("lead-auditor", "auditors"):
        return f"auditor·{label_of(url_or_page)}"
    return CTX.current_agent


def emit_score(force: bool = False) -> None:
    """Emit the backend-computed score (once the audit froze the total), only when it changes."""
    st = CTX.store
    if st and st.get("frozen_total"):
        sc = st.score()
        data = {"value": sc["value"], "baseline": st.get("meta").get("baseline_score", sc["value"]),
                "by_principle": sc["by_principle"], "eaa": sc["eaa"]}
        if force or data != CTX.last_score:
            CTX.last_score = data
            emit("score", data)


def set_status(issue_id: str, status: str, by: str, note: str = "", **fields: Any) -> dict:
    """Store + issue.status event + score: used by tools and by the orchestrator alike."""
    attempt = fields.get("attempt", CTX.attempt or None)
    if attempt is not None:
        fields["attempt"] = attempt
    issue = CTX.store.set_status(issue_id, status, by, note, **fields)
    data = {"id": issue_id, "status": status, "by": by, "note": note}
    if attempt is not None:
        data["attempt"] = attempt
    emit("issue.status", data, by)
    emit_score()
    return issue


def _compact_issue(i: dict) -> dict:
    keys = ("id", "wcag", "criterion_name", "title", "severity", "source", "selector", "rule", "pages",
            "status", "evidence", "impact", "files", "fix_note", "human_action")
    out = {k: i[k] for k in keys if i.get(k)}
    rejections = [h["note"] for h in i["history"] if h["status"] == REJECTED]
    if rejections:
        out["rejections"] = rejections
    return out


def shots_dir() -> Path:
    d = (CTX.work_dir or Path("state")) / "shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ cartographer

@tool("crawl_site", "Breadth-first crawl of the store's internal pages (follows links and onclick navigation).",
      {"type": "object", "properties": {"max_pages": {"type": "integer", "default": 30}}})
async def crawl_site(args):
    try:
        pages = await browser.crawl(CTX.base_url, int(args.get("max_pages") or 30))
    except Exception as e:
        return _err(f"crawl failed ({e}); retry once, the local server may still be starting")
    out = [{"path": path_of(p["url"]), "title": p["title"],
            **({"reached_only_via_onclick": [path_of(h) for h in p["hidden_links"]]} if p.get("hidden_links") else {})}
           for p in pages]
    return _ok({"base_url": CTX.base_url, "pages": out})


@tool("register_page", "Register a page to audit, with its template (home, category, product, cart, checkout...).",
      {"url": str, "title": str, "template": str})
async def register_page(args):
    path = path_of(args.get("url", ""))
    template = (args.get("template") or "").strip().lower() or label_of(path)
    page, added = CTX.store.add_page(path, args.get("title", ""), template, template)
    if added:
        log(f"Registered {path} as {template} template", "ok")
    return _ok({"registered": added, "page": page})


@tool("list_pages", "List registered pages.", {"type": "object", "properties": {}})
async def list_pages(args):
    return _ok(CTX.store.pages())


# ------------------------------------------------------------------ auditors

@tool("audit_page", "Run the axe-core scanner (WCAG 2.1 A/AA rules) on one page.", {"url": str})
async def audit_page(args):
    url = url_of(args.get("url", ""))
    if CTX.chaos and not CTX.chaos_fired:
        CTX.chaos_fired = True
        log(f"Injected fault: audit_page({path_of(url)}) will fail once (--chaos)", "err", "orchestrator")
        return _err("Chromium crashed during analysis (Target closed). This is transient and may be retried.")
    try:
        res = await browser.axe_audit(url)
    except Exception as e:
        return _err(f"axe audit failed on {url}: {e}. Retry once.")
    res["url"] = path_of(url)
    return _ok(res)


@tool("keyboard_walk", "Tab through a page: focus order, accessible names, visible focus, unreachable controls.",
      {"url": str})
async def keyboard_walk(args):
    url = url_of(args.get("url", ""))
    try:
        res = await browser.keyboard_walk(url)
    except Exception as e:
        return _err(f"keyboard walk failed on {url}: {e}. Retry once.")
    res["url"] = path_of(url)
    return _ok(res)


@tool("get_page_html", "Rendered HTML of a page (truncated).", {"url": str})
async def get_page_html(args):
    try:
        return _ok(await browser.page_html(url_of(args.get("url", ""))))
    except Exception as e:
        return _err(f"could not load page: {e}")


ISSUE_SCHEMA = {
    "type": "object",
    "properties": {
        "page": {"type": "string", "description": "page path, e.g. /product.html"},
        "wcag": {"type": "string", "description": "success criterion, e.g. 2.1.1"},
        "title": {"type": "string", "description": "short, plain-English, compliance-readable"},
        "impact": {"type": "string", "description": "concrete impact on a disabled user"},
        "evidence": {"type": "string", "description": "offending HTML/CSS snippet"},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "source": {"type": "string", "enum": list(SOURCES),
                   "description": "axe = reported by audit_page; keyboard = found by keyboard_walk; agent = your judgment"},
        "selector": {"type": "string", "description": "CSS selector of the shared component"},
        "rule": {"type": "string", "description": "axe rule id if source is axe, else empty"},
    },
    "required": ["page", "wcag", "title", "impact", "evidence", "severity", "source", "selector"],
}


@tool("add_issue", "Record an accessibility issue. Same component on another page is merged automatically.",
      ISSUE_SCHEMA)
async def add_issue(args):
    if not args.get("wcag") or not args.get("title"):
        return _err("wcag and title are required")
    page = path_of(args.get("page", ""))
    by = auditor_name(page)
    issue, merged = CTX.store.add_issue(**{**args, "pages": [page], "by": by,
                                           "note": "Detected during page audit"})
    if merged:
        emit("issue.merged", {"id": issue["id"], "page": page}, by)
        return _ok({"id": issue["id"], "merged": True, "pages": issue["pages"]})
    emit("issue.detected", {k: v for k, v in issue.items()}, by)
    return _ok({"id": issue["id"], "merged": False})


@tool("list_issues", "List recorded issues, optionally filtered by status.",
      {"type": "object", "properties": {"status": {"type": "string"}}})
async def list_issues(args):
    return _ok([_compact_issue(i) for i in CTX.store.issues(args.get("status") or None)])


# ------------------------------------------------------------------ developer

@tool("mark_fixed", "Declare an issue fixed in the source, with the files changed and what you did.",
      {"issue_id": str, "files": list, "explanation": str})
async def mark_fixed(args):
    iid = args.get("issue_id", "")
    try:
        issue = CTX.store.issue(iid)
    except KeyError:
        return _err(f"unknown issue {iid}; call list_issues")
    if issue["status"] != FIXING:
        return _err(f"{iid} is {issue['status']}, not assigned to you in this batch")
    files = [str(f).lstrip("./") for f in (args.get("files") or [])]
    set_status(iid, FIXED_PENDING, "developer", args.get("explanation", ""),
               files=files, fix_note=args.get("explanation", ""))
    log(f"{iid} fixed in {', '.join(files) or '?'}: {args.get('explanation', '')}", "msg", "developer")
    return _ok({"id": iid, "status": FIXED_PENDING})


@tool("cannot_fix", "Escalate an issue to a human (missing content, third-party code...). Say who must do what.",
      {"issue_id": str, "reason": str})
async def cannot_fix(args):
    iid = args.get("issue_id", "")
    try:
        CTX.store.issue(iid)
    except KeyError:
        return _err(f"unknown issue {iid}")
    reason = args.get("reason", "")
    set_status(iid, NEEDS_HUMAN, CTX.current_agent, reason, human_action=reason)
    log(f"Escalated {iid} to a human: {reason}", "msg", CTX.current_agent)
    return _ok({"id": iid, "status": NEEDS_HUMAN})


# ------------------------------------------------------------------ tester

@tool("compare_with_baseline", "Re-scan a page and compare with the baseline: resolved / still failing / new "
      "violations, plus the share of changed pixels and screenshot paths (before, after, diff).", {"url": str})
async def compare_with_baseline(args):
    url = url_of(args.get("url", ""))
    label = label_of(url)
    CTX.compare_n += 1
    d = shots_dir()
    after = d / f"after-{label}-{CTX.compare_n}.png"
    try:
        res = await browser.axe_audit(url, screenshot_path=after)
    except Exception as e:
        return _err(f"re-scan failed: {e}. Retry once.")
    base = CTX.baseline.get(path_of(url), {})
    before_keys = {tuple(k) for k in base.get("keys", [])}
    now = {(v["rule"], n["target"]) for v in res["violations"] for n in v["nodes"]}
    out = {
        "url": path_of(url),
        "resolved": sorted(map(list, before_keys - now)),
        "still_failing": sorted(map(list, before_keys & now)),
        "new_violations_regressions": sorted(map(list, now - before_keys)),
    }
    before = CTX.ref_shots.get(path_of(url)) or base.get("shot")
    if before and Path(before).exists():
        diff = d / f"diff-{label}-{CTX.compare_n}.png"
        out["changed_pixels_ratio"] = await browser.visual_diff(before, after, diff)
        out.update(before_png=str(before), after_png=str(after), diff_png=str(diff))
        if out["changed_pixels_ratio"] > 0.02:
            out["note"] = "More than 2% of pixels changed: open diff_png with Read and check the change is intended."
    return _ok(out)


@tool("verdict", "Accept or reject one fixed issue. Reasons must be actionable for the developer.",
      {"issue_id": str, "accepted": bool, "reason": str})
async def verdict(args):
    iid = args.get("issue_id", "")
    try:
        issue = CTX.store.issue(iid)
    except KeyError:
        return _err(f"unknown issue {iid}")
    if issue["status"] != FIXED_PENDING:
        return _err(f"{iid} is {issue['status']}; only fixed_pending issues get a verdict")
    accepted = bool(args.get("accepted"))
    reason = args.get("reason", "")
    set_status(iid, VALIDATED if accepted else REJECTED, "tester", reason)
    log(f"{'VALIDATED' if accepted else 'REJECTED'} {iid}: {reason}", "ok" if accepted else "reject", "tester")
    return _ok({"id": iid, "status": VALIDATED if accepted else REJECTED})


@tool("batch_verdict", "Verdict on the whole batch. Reject ONLY for a regression (the batch is rolled back).",
      {"accepted": bool, "reason": str})
async def batch_verdict(args):
    CTX.batch_verdict = {"accepted": bool(args.get("accepted")), "reason": args.get("reason", "")}
    return _ok({"recorded": CTX.batch_verdict})


ALL_TOOLS = [crawl_site, register_page, list_pages, audit_page, keyboard_walk, get_page_html, add_issue,
             list_issues, mark_fixed, cannot_fix, compare_with_baseline, verdict, batch_verdict]
TOOL_NAMES = [t.name for t in ALL_TOOLS]


def server():
    return create_sdk_mcp_server("a11y", tools=ALL_TOOLS)


def t(*names: str) -> list[str]:
    """MCP names as seen by the agents: mcp__a11y__<tool>."""
    for n in names:
        assert n in TOOL_NAMES, n
    return [f"mcp__a11y__{n}" for n in names]
