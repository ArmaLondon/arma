# Arma

**Arma gives compliance teams an AI agent team that audits, fixes and verifies their store's
accessibility, then hands engineering a ready-to-merge pull request.**

- Live dashboard (replay): https://web-rosy-xi-65.vercel.app
- Pitch / About: https://web-rosy-xi-65.vercel.app/#about

A team of Claude agents (Claude Agent SDK) maps a storefront, audits every page against WCAG 2.1 AA
(the standard behind the European Accessibility Act) with parallel sub-auditors, fixes the source
code batch by batch, has every fix checked by an independent tester agent (reject → retry,
rollback on regression, human escalation after three attempts), then writes the pull request and
the accessibility statement. The dashboard is a pure function of the recorded event stream.

See `arma-spec.md` (spec), `arma-build-plan.md` (plan) and `CLAUDE.md` (commands).
