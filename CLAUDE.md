# Arma

Arma is a compliance dashboard for European e-commerce teams. A team of agents hosted on Claude
Managed Agents audits a store against WCAG 2.1 AA (the standard behind the European Accessibility
Act), fixes the source code, has every fix verified by an independent tester agent (reject → retry,
rollback, human escalation), then prepares a pull request plus an accessibility statement. The
dashboard is a pure function of a JSONL event stream, rendered identically live (SSE) or in replay (Vercel).

- Spec (source of truth): `arma-spec.md`
- Build plan (follow in order, commit per step): `arma-build-plan.md`
- Progress: `TASKS.md`
- Visual reference + test data: `reference/arma-dashboard-prototype.html`

## Layout
- `bridge.py`: runs one Managed Agents session, answers the custom tools (ledger), records
  `recordings/run-<date>.jsonl`, downloads `/mnt/session/outputs`
- `arma_bridge/custom_tools.py`: the compliance ledger tools; `arma/`: event bus, state store, scoring, WCAG table
- `managed/`: agent system prompts, brief, grader rubric; `claude-lock.json`: hosted agent/environment ids
- `sandbox_tools/`: browser/axe scripts uploaded as `tools.tgz` and run inside the sandbox
- `demo-shop/`: trapped demo store (uploaded as `demo-shop.tgz`); `eval/`: ground truth + eval
- `web/`: static dashboard (Vercel)

## Commands
```bash
uv sync && uv run playwright install chromium
cp .env.example .env                                   # ANTHROPIC_API_KEY (CLAUDE_API_KEY also accepted)
uv run python scripts/setup_managed.py [--recreate | --agents-only] [--model-all claude-sonnet-5-5]
uv run python bridge.py run --smoke                    # cheap end-to-end check of the sandbox
uv run python bridge.py run [--until audit] [--budget-cents 3000] [--model-override claude-sonnet-5-5]
uv run python bridge.py resume <session_id> [--recording recordings/run-<date>.jsonl]
uv run python eval/run_eval.py state/state.json state/out/final.json
uv run python scripts/pick_demo_run.py recordings/run-<date>.jsonl
uv run python scripts/check_web.py recordings/demo-run.jsonl   # path relative to web/
uv run python scripts/export_logs.py web/recordings/demo-run.jsonl
cd web && npx vercel --prod                            # static deploy (replay)
uv run pytest -q
```

## Rules
- Execute the plan steps in order; each ends with its verification, then a commit.
- Priority: a demo that works visually every time. Real is a bonus, reliable is mandatory.
- Never hand-craft events to simulate a real run. Test data comes only from `scripts/make_fixture.py`.
- No front-end framework (vanilla HTML/CSS/JS), no database (JSON on disk).
- UI text and agent-produced content in English; the demo shop stays in French.
- Rehearsals use a Sonnet model and a `--budget-cents` cap; watch `cost_usd` in `state/state.json`.
- The dashboard must itself be accessible (keyboard, visible focus, AA contrast, ARIA tabs,
  reduced motion, no horizontal page scroll at 400 px).
- After editing `managed/agents/*.md` or the custom tool definitions, re-run
  `scripts/setup_managed.py --agents-only` so `claude-lock.json` points at the new versions.
