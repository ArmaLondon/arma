# Arma

**Arma gives compliance teams a hosted AI agent team that audits, fixes and verifies their store's
accessibility, proves it against a rubric, and hands engineering a ready-to-merge pull request.**

- Live dashboard (replay): https://web-rosy-xi-65.vercel.app
- Pitch / About: https://web-rosy-xi-65.vercel.app/#about

A team of Claude agents hosted on Claude Managed Agents maps a storefront, audits every page against WCAG 2.1 AA
(the standard behind the European Accessibility Act) with parallel sub-auditors, fixes the source
code batch by batch, has every fix checked by an independent tester agent (reject → retry,
rollback on regression, human escalation after three attempts), then writes the pull request and
the accessibility statement. The dashboard is a pure function of the recorded event stream.

Spec and plan: `arma-spec.md`, `arma-build-plan.md`. Commands: `CLAUDE.md`.

The live dashboard replays a real Claude Managed Agents run (session sesn_016a2N5e3DNZHej9MrL4QxSo):
22 issues (19 missed by scanners), 1 tester rejection + git rollback, 13 commits, score 38 → 98,
independent grader satisfied, eval recall 1.0 (honesty metric failed on one escalation, see
deliverables/agent-design.txt).
