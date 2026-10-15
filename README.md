# Arma

**Arma gives compliance teams a hosted AI agent team that audits, fixes and verifies their store's
accessibility, proves it against a rubric, and hands engineering a ready-to-merge pull request.**

- Live dashboard (replay of a real run): https://web-rosy-xi-65.vercel.app
- Pitch / About: https://web-rosy-xi-65.vercel.app/#about

From June 2025 the European Accessibility Act requires e-commerce sites to meet WCAG 2.1 AA.
Scanners catch only part of the problem and fix nothing. Arma runs a team of Claude agents on
Claude Managed Agents that maps a storefront, audits every page, fixes the source code, has every
fix checked by an independent tester, and writes the pull request and the accessibility statement.
The dashboard is a pure function of the recorded event stream, so a live run and its replay look
the same.

## Results of the recorded run

Claude Managed Agents session `sesn_016a2N5e3DNZHej9MrL4QxSo` on the demo store Maison Lumière
(4 pages, 16 planted defects): 61 min of agent time, $5.49 list cost.

| | Before | After |
|---|---|---|
| Score | 38 | 98 |
| axe violations | 34 | 0 |
| Controls unreachable by keyboard | 8 | 0 |
| Tab stops with visible focus | 0/56 | 64/64 |
| EAA status | non-compliant | partially compliant |

- **Audit:** 4 page auditors in parallel found 22 issues, 19 of which automated scanners miss.
- **Fix loop:** 13 batches and 13 commits (one per WCAG criterion). The tester rejected one fix (the
  cart quantity buttons showed `NaN`), the batch was rolled back with git, and the same developer
  thread fixed it on the second attempt. 21 issues fixed and verified, 1 escalated to a human
  (a third-party payment widget).
- **Grader:** an independent grader, scoring against `managed/rubric.md`, returned *satisfied*.
- **Eval vs ground truth:** recall 1.0, precision 0.86, verified fix rate 1.0, 0 false fixes,
  0 regressions. The honesty check failed: one product's alt text was rewritten from the visible
  name when it should have been escalated to merchandising.

## How it works

```
             Claude Managed Agents session (cloud sandbox: Chromium, Playwright, git)
  ┌───────────────────────────────────────────────────────────────────────────────┐
  │ arma-lead ──┬─ arma-page-auditor × N   (one thread per page, in parallel)     │
  │             ├─ arma-developer          (persistent thread, keeps its context) │
  │             ├─ arma-tester             (isolated: cannot edit, sees no diff)  │
  │             └─ arma-writer             (PR body + accessibility statement)    │
  └──────────────────────────────┬────────────────────────────────────────────────┘
               custom tool calls │ report_issue, verdict, rollback_batch, …
                                 ▼
          bridge.py: compliance ledger ──► recordings/run-<date>.jsonl ──► web/ dashboard
```

1. **Audit.** axe-core, a keyboard walk and the agents' own judgement (vague links, useless alt
   text, placeholder-as-label, colour-only errors, clickable divs, removed focus, …).
2. **Plan.** One batch per WCAG criterion, blockers in the purchase funnel first.
3. **Fix and verify.** The developer fixes, and the tester re-measures (axe, keyboard, pixel diff)
   and accepts or rejects each fix with a reason. A regression triggers a git rollback. After three
   failed attempts the issue goes to a human with a concrete action.
4. **Deliver.** The writer produces the PR body and an accessibility statement. Arma never claims
   full compliance: items that need a human stay open in the statement.

The agents never talk to each other directly. Every finding and status change is a custom tool
call that the local bridge answers: it de-duplicates issues, enforces the status state machine
(`detected → fixing → fixed_pending → validated | rejected | needs_human`), recomputes the score
and emits the dashboard events. Full design: [`deliverables/agent-design.txt`](deliverables/agent-design.txt).

## Run it

Requires Python 3.14, [uv](https://docs.astral.sh/uv/) and an Anthropic API key with Managed Agents access.

```bash
uv sync && uv run playwright install chromium
cp .env.example .env                       # set ANTHROPIC_API_KEY

uv run python scripts/setup_managed.py     # create the environment and agents → claude-lock.json
uv run python bridge.py run --smoke        # cheap check of the sandbox
uv run python bridge.py run --budget-cents 3000
uv run python bridge.py resume <session_id>   # reattach if the bridge stopped

uv run python eval/run_eval.py state/state.json state/out/final.json
```

View the dashboard locally (it falls back to replaying `web/recordings/demo-run.jsonl`):

```bash
cd web && python -m http.server 8000       # http://localhost:8000
```

To ship a new run: `scripts/pick_demo_run.py recordings/run-<date>.jsonl`, check it with
`scripts/check_web.py recordings/demo-run.jsonl`, then `cd web && npx vercel --prod`.
All commands: [`CLAUDE.md`](CLAUDE.md).

## Repository

| Path | Contents |
|---|---|
| `bridge.py`, `arma_bridge/` | Session runner and the compliance ledger (custom tools) |
| `arma/` | Event bus, state store, scoring, WCAG criteria table |
| `managed/` | Agent system prompts, run brief, grader rubric |
| `sandbox_tools/` | Crawl, audit, keyboard, baseline and compare scripts run inside the sandbox |
| `demo-shop/` | Maison Lumière, the demo store with planted defects (in French) |
| `eval/` | Ground truth, eval script and history |
| `web/` | Static dashboard (vanilla JS + D3), deployed on Vercel |
| `scripts/` | Setup, fixture, run picking, dashboard check, log export |
| `deliverables/` | Agent design, agent logs, submission links |
| `arma-spec.md`, `arma-build-plan.md` | Spec and build plan (in French) |

## Tests

```bash
uv run pytest -q
```
