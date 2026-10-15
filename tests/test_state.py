import json

import pytest

from arma import scoring
from arma.state import (DETECTED, NEEDS_HUMAN, REJECTED, VALIDATED, Store)

# the 16 issues of the prototype / fixture: (id, wcag, severity)
FIXTURE = [
    ("A01", "1.4.3", "major"), ("A02", "3.1.1", "minor"), ("A03", "1.1.1", "major"),
    ("A04", "1.1.1", "minor"), ("A05", "2.4.7", "critical"), ("A06", "4.1.2", "major"),
    ("A07", "2.1.1", "critical"), ("A08", "2.1.1", "critical"), ("A09", "2.1.1", "critical"),
    ("A10", "3.3.2", "critical"), ("A11", "3.3.1", "major"), ("A12", "2.4.4", "minor"),
    ("A13", "1.3.1", "major"), ("A14", "2.4.2", "minor"), ("A15", "4.1.2", "major"),
    ("A16", "1.3.1", "major"),
]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "state.json")


def test_duplicate_merges_pages(store):
    a, merged = store.add_issue(wcag="4.1.2", selector=".icons button", rule="", title="Icon buttons unnamed",
                                severity="major", source="agent", pages=["home"])
    assert not merged and a["id"] == "A01"
    b, merged = store.add_issue(wcag="4.1.2", selector=" .icons  button", rule="",
                                title="icon buttons UNNAMED", pages=["product"])
    assert merged and b["id"] == "A01" and b["pages"] == ["home", "product"]
    c, merged = store.add_issue(wcag="1.4.3", selector=".footer", rule="color-contrast", title="Footer contrast",
                                pages=["home"])
    d, merged = store.add_issue(wcag="1.4.3", selector=".footer", rule="color-contrast", title="Other wording",
                                pages=["cart"])
    assert merged and d["id"] == c["id"] and d["pages"] == ["home", "cart"]
    e, merged = store.add_issue(wcag="4.1.2", selector=".icons button", title="Different problem", pages=["home"])
    assert not merged and e["id"] == "A03"
    assert len(store.issues()) == 3


def test_issue_enrichment(store):
    i, _ = store.add_issue(wcag="2.4.7", selector="*:focus", title="Focus invisible", severity="critical",
                           source="keyboard", page="home")
    assert (i["criterion_name"], i["level"], i["principle"], i["en301549"]) == \
        ("Focus Visible", "AA", "O", "9.2.4.7")
    assert i["status"] == DETECTED and i["history"][0]["status"] == DETECTED and i["pages"] == ["home"]


def test_atomic_persistence(tmp_path, store):
    store.add_page("http://x/", "Home", "home")
    store.add_issue(wcag="3.1.1", selector="html", rule="html-has-lang", title="No lang", source="axe")
    store.set_status("A01", REJECTED, "tester", "still failing", attempt=1)
    store.finish_phase("audit")
    store.add_cost(0.25)
    assert not list(tmp_path.glob("*.tmp"))
    again = Store(tmp_path / "state.json")
    assert again.phase_done("audit") and not again.phase_done("fix")
    assert again.issue("A01")["status"] == REJECTED
    assert again.issue("A01")["history"][-1] == {**again.issue("A01")["history"][-1], "attempt": 1, "by": "tester"}
    assert "attempt" not in again.issue("A01")
    assert again.pages()[0]["template"] == "home" and again.get("cost_usd") == 0.25
    assert json.loads((tmp_path / "state.json").read_text())["issues"][0]["id"] == "A01"


def test_invalid_status(store):
    store.add_issue(wcag="3.1.1", title="x")
    with pytest.raises(ValueError):
        store.set_status("A01", "done", "tester")
    with pytest.raises(KeyError):
        store.set_status("A99", VALIDATED, "tester")


def _fixture_store(tmp_path):
    s = Store(tmp_path / "s.json")
    for iid, w, sev in FIXTURE:
        s.add_issue(wcag=w, selector=iid, title=iid, severity=sev)
    s.freeze_score()
    return s


def test_baseline_score_in_credible_zone(tmp_path):
    s = _fixture_store(tmp_path)
    sc = s.score()
    assert 30 <= sc["value"] <= 45
    assert sc["eaa"] == scoring.NON_COMPLIANT


def test_score_with_two_escalated(tmp_path):
    s = _fixture_store(tmp_path)
    for i in s.issues():
        st = NEEDS_HUMAN if i["title"] in ("A04", "A16") else VALIDATED
        s.set_status(i["id"], st, "tester")
    sc = s.score()
    assert 93 <= sc["value"] <= 97
    assert sc["eaa"] == scoring.PARTIALLY_COMPLIANT
    assert sc["by_principle"]["O"] == 100 and sc["by_principle"]["P"] < 100


def test_frozen_total_does_not_move_with_new_issues(tmp_path):
    s = _fixture_store(tmp_path)
    before = s.score()["value"]
    s.add_issue(wcag="1.4.1", title="late", severity="critical")
    assert s.score()["value"] < before   # open penalty grows, denominator stays frozen
