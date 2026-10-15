"""Create (or re-create) Arma's Managed Agents resources and store their ids in claude-lock.json.

usage: python scripts/setup_managed.py [--recreate] [--model-all claude-sonnet-5-5]
Sub-agents are created first, then the lead, so the lead's roster pins their versions.
(Control-plane setup; the spec suggests `ant apply` — this script does the same through the SDK.)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from arma.config import load_env  # noqa: E402

load_env()
import anthropic  # noqa: E402

from arma_bridge.custom_tools import tool_defs  # noqa: E402

LOCK = ROOT / "claude-lock.json"
AGENTS_DIR = ROOT / "managed" / "agents"
MODELS = {"lead": "claude-opus-5-5", "page-auditor": "claude-sonnet-5-5", "developer": "claude-sonnet-5-5",
          "tester": "claude-opus-5-5", "writer": "claude-sonnet-5-5"}
BUILTINS = {"lead": ["bash", "read", "glob", "grep"], "page-auditor": ["bash", "read", "glob", "grep"],
            "developer": ["bash", "read", "edit", "write", "glob", "grep"], "tester": ["bash", "read", "glob", "grep"],
            "writer": ["read", "write", "glob"]}
DESCRIPTIONS = {
    "page-auditor": "Audits ONE store page against WCAG 2.1 AA (axe + keyboard walk + expert judgement) and records every finding with report_issue. Give it the page URL and its label auditor·<page>. Spawn one per page, all at once.",
    "developer": "Fixes the store's shared source in /workspace/site for one WCAG batch at a time and marks each issue fixed (or cannot_fix). Reuse the same developer thread for every batch and retry; forward tester rejections verbatim.",
    "tester": "Independent, read-only verifier. Give it the issue ids, pages and criterion (not the diff); it measures with compare.py/keyboard.py and gives a verdict per issue plus a batch verdict.",
    "writer": "Writes pr-body.md and accessibility-statement.md to /mnt/session/outputs from /workspace/arma/report.json.",
}
NAMES = {"lead": "arma-lead", "page-auditor": "arma-page-auditor", "developer": "arma-developer", "tester": "arma-tester", "writer": "arma-writer"}


def toolset(role):
    return {"type": "agent_toolset_20260401",
            "default_config": {"enabled": False, "permission_policy": {"type": "always_allow"}},
            "configs": [{"name": n, "enabled": True} for n in BUILTINS[role]]}


def system(role):
    return (AGENTS_DIR / "_preamble.md").read_text() + "\n" + (AGENTS_DIR / f"{role}.md").read_text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recreate", action="store_true")
    ap.add_argument("--model-all", default="")
    ap.add_argument("--agents-only", action="store_true", help="re-create the agents, keep the environment")
    a = ap.parse_args()
    client = anthropic.Anthropic()
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    if "environment" not in lock or (a.recreate and not a.agents_only):
        env = client.beta.environments.create(
            name="arma-env",
            config={"type": "cloud",
                    "networking": {"type": "limited", "allow_package_managers": True},
                    "packages": {"type": "packages", "apt": ["chromium", "git", "fonts-dejavu-core"], "pip": ["playwright", "pillow"]}},
        )
        lock["environment"] = {"id": env.id, "name": env.name}
        print("environment", env.id)
    agents = lock.get("agents", {}) if not (a.recreate or a.agents_only) else {}
    for role in ["page-auditor", "developer", "tester", "writer", "lead"]:
        if role in agents and not a.recreate:
            continue
        kw = dict(name=NAMES[role], model=a.model_all or MODELS[role], system=system(role),
                  tools=[toolset(role), *tool_defs(role)])
        if role in DESCRIPTIONS:
            kw["description"] = DESCRIPTIONS[role]
        if role == "lead":
            kw["description"] = "Coordinates an Arma accessibility remediation run."
            kw["multiagent"] = {"type": "coordinator", "agents": [
                {"type": "agent", "id": agents[r]["id"], "version": agents[r]["version"]} for r in ["page-auditor", "developer", "tester", "writer"]]}
        ag = client.beta.agents.create(**kw)
        agents[role] = {"id": ag.id, "version": ag.version, "name": ag.name, "model": kw["model"]}
        print(role, ag.id, "v", ag.version, kw["model"])
    lock["agents"] = agents
    LOCK.write_text(json.dumps(lock, indent=2))
    print("saved", LOCK)


main()
