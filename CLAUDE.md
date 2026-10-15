# Arma

Arma is a compliance dashboard for European e-commerce teams. A team of `claude-agent-sdk` agents
audits a store against WCAG 2.1 AA (the standard behind the European Accessibility Act), fixes
the source code, has every fix verified by an independent tester agent (reject → retry, rollback,
human escalation), then prepares a pull request plus an accessibility statement. The dashboard is
a pure function of a JSONL event stream, rendered identically live (SSE) or in replay (Vercel).

- Spec (source of truth): `new-guidelines/arma-spec 2.md` (Managed Agents version; supersedes `arma-spec.md`)
- Build plan (follow in order, commit per step): `new-guidelines/arma-build-plan 2.md`
- Two sessions: "web" owns `web/`, the fixture, check/pick/export scripts and deliverables; "agents" owns the rest
- Progress: `TASKS.md`
- Visual reference + test data: `reference/arma-dashboard-prototype.html`

## Commands
```bash
uv sync && uv run playwright install chromium     # (or: pip install -r requirements.txt)
cp .env.example .env                               # ANTHROPIC_API_KEY (CLAUDE_API_KEY also accepted)
uv run python run.py --demo --model sonnet --chaos # real run on the demo shop
uv run uvicorn server:app --port 8000              # http://localhost:8000/?mode=live
uv run python scripts/pick_demo_run.py recordings/run-<date>.jsonl
uv run python scripts/export_logs.py web/recordings/demo-run.jsonl
cd web && npx vercel --prod                        # static deploy (replay)
uv run pytest -q
```

## Rules
- Execute the plan steps in order; each ends with its verification, then a commit.
- Priority: a demo that works visually every time. Real is a bonus, reliable is mandatory.
- Never hand-craft events to simulate a real run. Test data comes only from `scripts/make_fixture.py`.
- No front-end framework (vanilla HTML/CSS/JS), no database (JSON on disk).
- UI text and agent-produced content in English; the demo shop stays in French.
- Rehearsals use `--model sonnet`; watch `cost_usd` in `state/state.json`.
- The dashboard must itself be accessible (keyboard, visible focus, AA contrast, ARIA tabs,
  reduced motion, no horizontal page scroll at 400 px).

## SDK pitfalls
- `AgentDefinition` fields are camelCase (`maxTurns`, `disallowedTools`); `background=False` on
  the page-auditor.
- `allowed_tools` auto-approves but does not restrict: restrict with `tools=`,
  `disallowed_tools=` and `permission_mode="dontAsk"`. Always `setting_sources=[]`.
- MCP tools used by subagents must also be in the parent session's `allowed_tools`.
- Tools return `{"content": [...], "is_error": True}` instead of raising.
- Never `break` inside `async for msg in query(...)`.
- Developer `cwd` = site repo; the `guard` hook denies writes outside the role's write root.
