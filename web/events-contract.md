# Event contract (arma-spec.md §5)

One JSON object per line: `{"t": seconds since run start, "type": ..., "agent"?: who, "data": {...}}`.
The UI is a pure function of the sequence: `state = events.reduce(apply)`. Append-only.

| `type` | `data` | UI effect |
|---|---|---|
| `run.started` | `{site, repo, branch}` | Reset state, clock to zero |
| `phase.changed` | `{phase}` in `crawl, baseline, audit, plan, fix, reaudit, report, pr` | Phase rail |
| `agent.status` | `{agent, status: idle\|working\|done, activity}` | Agent team panel |
| `subagents` | `{agent: "auditors", states: ["working","done",…]}` | Parallel sub-auditor dots |
| `log` | `{text, kind: msg\|tool\|ok\|err\|reject\|rollback\|commit\|phase}` | Live log |
| `baseline` | `{axe_violations, unreachable, focus_visible: [a, b]}` | Before metrics |
| `issue.detected` | full issue (spec §6.1) | Findings row (flash), KPIs |
| `issue.merged` | `{id, page}` | Adds a page to an existing issue |
| `issue.status` | `{id, status, by, note, attempt, fix_diff?, files?, human_action?}` | Status pill + verification trail |
| `score` | `{value, baseline, by_principle: {P,O,U,R}, eaa}` | Gauge, bars, sparkline |
| `batch.started` | `{id, criterion, issue_ids, attempt}` | Phase-style log |
| `commit.created` | `{sha, criterion, message, files}` | Commit list |
| `reaudit` | `{axe_violations, unreachable, focus_visible: [a, b]}` | After metrics |
| `document.written` | `{name, path, content}` | Statement tab / PR body |
| `pr.ready` | `{repo, branch, base, commits, files, body}` | Enables "Send PR to engineering" |
| `pr.sent` | `{number, url, notified: […], simulated: bool, by}` | Confirmation card (ignored in replay: the click is simulated) |
| `run.finished` | `{cost_usd, duration_s}` | "Last run" clock |

Extensions to the spec table: `issue.status` may carry `fix_diff`, `files` and `human_action` (the
orchestrator computes the diff with `git diff`); `score` carries `eaa`
(`non_compliant | partially_compliant | compliant_automated`).
