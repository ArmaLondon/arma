from arma.templates import pr_body, statement

SUMMARY = {
    "site": "maison-lumiere.fr", "date": "2026-10-15", "pages": ["/", "/checkout.html"],
    "score": {"before": 38, "after": 95, "eaa_status": "partially_compliant"},
    "metrics": {"before": {"axe_violations": 34, "unreachable": 8}, "after": {"axe_violations": 0, "unreachable": 0}},
    "issues": [
        {"id": "A01", "wcag": "1.4.3", "criterion_name": "Contrast (Minimum)", "level": "AA", "title": "Pale text",
         "status": "validated", "fix_note": "Darkened text", "human_action": ""},
        {"id": "A16", "wcag": "1.3.1", "criterion_name": "Info and Relationships", "level": "A",
         "title": "Card widget", "status": "needs_human", "fix_note": "", "human_action": "PayVite must label fields"},
    ],
    "commits": [{"sha": "abc1234", "message": "fix(a11y): WCAG 1.4.3 — Pale text"}],
}


def test_pr_body():
    body = pr_body(SUMMARY)
    assert "38 → 95" in body and "`abc1234`" in body and "PayVite must label fields" in body


def test_statement_never_claims_full_compliance():
    st = statement(SUMMARY)
    assert "partially compliant" in st and "[TO COMPLETE]" in st and "Card widget" in st
    assert "fully compliant" not in st.lower()
