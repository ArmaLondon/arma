"""Compliance score (spec §6.3).

score = round(100 * (1 - open_penalty / frozen_total)), frozen_total = total_penalty * 1.6,
frozen once the audit is done so the score only moves thanks to fixes.
An issue is "open" until it is validated. Never claims full compliance.
"""

PEN = {"critical": 10, "major": 6, "minor": 3}
MULTIPLIER = 1.6
PRINCIPLE_OF = {"1": "P", "2": "O", "3": "U", "4": "R"}

NON_COMPLIANT = "non_compliant"
PARTIALLY_COMPLIANT = "partially_compliant"
COMPLIANT_AUTOMATED = "compliant_automated"


def principle(wcag: str) -> str:
    return PRINCIPLE_OF.get(str(wcag)[:1], "R")


def penalty(issue: dict) -> int:
    return PEN.get(issue.get("severity", "minor"), 3)


def frozen_total(issues: list[dict]) -> float:
    return sum(penalty(i) for i in issues) * MULTIPLIER


def compute(issues: list[dict], frozen_total: float | None = None) -> dict:
    total = sum(penalty(i) for i in issues)
    denom = frozen_total if frozen_total else total * MULTIPLIER
    open_pen = sum(penalty(i) for i in issues if i.get("status") != "validated")
    value = round(100 * (1 - open_pen / denom)) if denom else 100
    by = {}
    for p in "POUR":
        its = [i for i in issues if principle(i.get("wcag", "")) == p]
        tot = sum(penalty(i) for i in its)
        ok = sum(penalty(i) for i in its if i.get("status") == "validated")
        by[p] = round(100 * ok / tot) if tot else 100
    statuses = [i.get("status") for i in issues]
    if any(s not in ("validated", "needs_human") for s in statuses):
        eaa = NON_COMPLIANT
    elif "needs_human" in statuses:
        eaa = PARTIALLY_COMPLIANT
    else:
        eaa = COMPLIANT_AUTOMATED
    return {"value": max(0, min(100, value)), "by_principle": by, "eaa": eaa,
            "open_penalty": open_pen, "total_penalty": total}
