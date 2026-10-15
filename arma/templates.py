"""Deterministic fallback documents, used only if the writer agent fails (the demo never blocks)."""

from .scoring import COMPLIANT_AUTOMATED, NON_COMPLIANT

EAA_LABEL = {NON_COMPLIANT: "non-compliant", COMPLIANT_AUTOMATED: "compliant (automated scope)"}


def _status(s: dict) -> str:
    return EAA_LABEL.get(s["score"]["eaa_status"], "partially compliant")


def pr_body(s: dict) -> str:
    fixed = [i for i in s["issues"] if i["status"] == "validated"]
    human = [i for i in s["issues"] if i["status"] == "needs_human"]
    other = [i for i in s["issues"] if i["status"] not in ("validated", "needs_human")]
    b, a = s["metrics"]["before"] or {}, s["metrics"]["after"] or {}
    out = [
        "## Summary", "",
        f"This PR remediates {len(fixed)} WCAG 2.1 AA issues found by the Arma audit of {s['site']} "
        f"({len(s['pages'])} pages covering the purchase funnel). Each commit maps to one WCAG criterion and "
        "every fix was verified by an independent tester agent.", "",
        f"- Score: {s['score']['before']} → {s['score']['after']} ({_status(s)})",
        f"- Scanner violations: {b.get('axe_violations', '?')} → {a.get('axe_violations', '?')}",
        f"- Controls unreachable by keyboard: {b.get('unreachable', '?')} → {a.get('unreachable', '?')}",
        "",
    ]
    by_crit: dict[str, list[dict]] = {}
    for i in fixed:
        by_crit.setdefault(i["wcag"], []).append(i)
    for crit in sorted(by_crit, key=lambda c: [int(x) for x in c.split(".")]):
        its = by_crit[crit]
        out += [f"### WCAG {crit} {its[0]['criterion_name']} (Level {its[0]['level']})", ""]
        out += [f"- **{i['id']}** {i['title']}: {i['fix_note'] or 'fixed'}" for i in its]
        commits = [c for c in s["commits"] if f"WCAG {crit} " in c["message"]]
        out += [f"- Commit: `{c['sha']}`" for c in commits] + [""]
    out += ["## Needs human review", ""]
    out += [f"- **{i['id']}** {i['title']} (WCAG {i['wcag']}): {i['human_action']}" for i in human] or ["- None"]
    if other:
        out += ["", "## Still open", ""] + [f"- **{i['id']}** {i['title']} ({i['status']})" for i in other]
    out += ["", "## How this was verified", "",
            "Each batch was re-scanned with axe-core, walked with the keyboard and compared pixel by pixel with "
            "the previous state by a tester agent that never saw the developer's diff. Rejected fixes were "
            "retried; regressions were rolled back.", ""]
    return "\n".join(out)


def statement(s: dict) -> str:
    human = [i for i in s["issues"] if i["status"] != "validated"]
    out = [
        f"# Accessibility statement: {s['site']}", "",
        f"*Draft, {s['date']}. Status: **{_status(s)}** with WCAG 2.1 Level AA (EN 301 549).*", "",
        "## Compliance status", "",
        f"{s['site']} is {_status(s)} with WCAG 2.1 Level AA, the standard referenced by the European "
        "Accessibility Act, because of the non-accessible content listed below.", "",
        "## Non-accessible content", "",
    ]
    out += [f"- {i['title']} (WCAG {i['wcag']}): {i['human_action'] or 'remediation in progress'}" for i in human] \
        or ["- None identified in the assessed scope."]
    out += ["", "## How this statement was prepared", "",
            f"Assessment of {len(s['pages'])} pages ({', '.join(s['pages'])}) on {s['date']}, combining automated "
            "testing (axe-core), keyboard testing and expert review by AI agents, with independent verification "
            "of every fix. Automated and agent review cover only part of WCAG: testing with disabled users "
            "remains required.", "",
            "## Feedback and contact", "", "- Contact: [TO COMPLETE]", "- Response time: [TO COMPLETE]", "",
            "## Enforcement procedure", "", "[TO COMPLETE: national enforcement body and how to contact it]", ""]
    return "\n".join(out)


TEMPLATES = {"pr-body.md": pr_body, "accessibility-statement.md": statement}
