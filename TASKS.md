# Arma: tasks (arma-build-plan.md)

## Done: claude-agent-sdk version (git tag `sdk-version`, superseded)
- [x] Repo skeleton, event contract + EventBus + fixture, replay dashboard, first Vercel deploy
- [x] Trapped demo shop (Maison Lumière), browser tools, store + scoring + tests

## Done: Managed Agents version
- [x] W0 Event contract sent to the agents session (outcome, eval, session_id, labels)
- [x] W1 Contract v2 + fixture (outcome needs_revision→satisfied, eval PASS)
- [x] W2 Minimalist D3 dashboard: live agent workflow, gauge, timeline, POUR, grader + eval cards
- [x] W3 Interim replay of the real claude-agent-sdk run deployed (honest: no hosted badge)
- [x] W4 Deliverables tooling for the hosted architecture
- [x] W5 Real Managed Agents run shipped: grader satisfied, eval recall 1.0 (honesty FAIL on 1 escalation), deliverables updated

## Open
- [ ] Live mode (SSE): `web/app.js` expects `/api/events`, no server provides it yet
- [ ] Real GitHub PR
