"""Generate web/recordings/fixture.jsonl: a SCRIPTED test run for building the dashboard.

Data = the 16 issues of reference/arma-dashboard-prototype.html (ISSUES), scenario = its
buildScript(): mapping, baseline, parallel audit with an injected fault, plan, fix loop with the
tester rejecting A07 (role="button") and the 1.4.3 batch rolled back (18% visual diff), commits,
re-audit, writer documents, pr.ready, run.finished.

This is test data. It is NOT a recorded agent run and must never be shipped as one.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from arma import scoring  # noqa: E402

OUT = ROOT / "web" / "recordings" / "fixture.jsonl"
BRANCH = "a11y/eaa-remediation-2026-10-15"
PAGES = {"home": "/", "product": "/product.html", "cart": "/cart.html", "checkout": "/checkout.html"}
CRIT = {
    "1.1.1": ("Non-text Content", "A"), "1.3.1": ("Info and Relationships", "A"),
    "1.4.3": ("Contrast (Minimum)", "AA"), "2.1.1": ("Keyboard", "A"), "2.4.2": ("Page Titled", "A"),
    "2.4.4": ("Link Purpose (In Context)", "A"), "2.4.7": ("Focus Visible", "AA"),
    "3.1.1": ("Language of Page", "A"), "3.3.1": ("Error Identification", "A"),
    "3.3.2": ("Labels or Instructions", "A"), "4.1.2": ("Name, Role, Value", "A"),
}
ALL = ["home", "product", "cart", "checkout"]

ISSUES = [
    dict(id="A01", wcag="1.4.3", sev="major", src="axe", pages=ALL, sel=".hero p", rule="color-contrast",
         title="Low-contrast secondary text (hero, price notes, footer)",
         impact="Grey #b5b5b5 on #faf7f2 has a 1.9:1 ratio. Low-vision shoppers cannot read VAT notes, delivery promises or legal links.",
         evidence=".price-note { color: #aaaaaa; }\n.site-footer { color: #b0b0b0; }\n.hero p { color: #b5b5b5; }",
         fix="- .price-note { color: #aaaaaa; }\n+ .price-note { color: #6b6b6b; }  /* 5.3:1 */\n- .site-footer { color: #b0b0b0; }\n+ .site-footer { color: #666666; }  /* 5.7:1 */\n- .hero p { color: #b5b5b5; }\n+ .hero p { color: #5f5a52; }  /* 6.4:1 on #faf7f2 */",
         files=["styles.css"], final="validated"),
    dict(id="A02", wcag="3.1.1", sev="minor", src="axe", pages=["home"], sel="html", rule="html-has-lang",
         title="Page language not declared",
         impact="Screen readers read French content with an English voice, making product names unintelligible.",
         evidence="<html>", fix='- <html>\n+ <html lang="fr">', files=["index.html"], final="validated"),
    dict(id="A03", wcag="1.1.1", sev="major", src="axe", pages=["home", "cart"], sel=".card img", rule="image-alt",
         title="Product images have no text alternative",
         impact="Blind shoppers hear “image” or the file name for every product in the grid and the cart.",
         evidence='<img src="img/sneaker.svg">', fix='- <img src="img/sneaker.svg">\n+ <img src="img/sneaker.svg" alt="Leather sneakers">',
         files=["index.html", "cart.html"], final="validated"),
    dict(id="A04", wcag="1.1.1", sev="minor", src="agent", pages=["product"], sel="img.product-photo",
         title="Product photo alt text says only “image”",
         impact="The main product photo is described as “image”. Shoppers miss colour and material, which drive the purchase.",
         evidence='<img class="product-photo" src="img/sneaker.svg" alt="image">',
         fix='- alt="image"\n+ alt="Leather sneakers"   /* draft: colour and material to confirm */',
         files=["product.html"], final="needs_human",
         human="Draft alt text applied. Merchandising must confirm colour and material: the agent does not invent product facts."),
    dict(id="A05", wcag="2.4.7", sev="critical", src="agent", pages=ALL, sel="*:focus",
         title="Keyboard focus is invisible on every page",
         impact="A global rule removes the focus ring. Keyboard users cannot see where they are, so checkout is effectively impossible.",
         evidence="*:focus { outline: none; }",
         fix="- *:focus { outline: none; }\n+ :focus-visible {\n+   outline: 3px solid #2b2622;\n+   outline-offset: 3px;\n+ }",
         files=["styles.css"], final="validated"),
    dict(id="A06", wcag="4.1.2", sev="major", src="agent", pages=ALL, sel=".icons button",
         title="Header icon buttons are announced as emoji",
         impact="Search, wishlist and bag buttons are read as “magnifying glass tilted left”, “heart suit”, “shopping cart”. Their purpose is unclear.",
         evidence="<button onclick=\"toggleSearch()\">🔍</button>\n<button>♡</button>",
         fix='- <button onclick="toggleSearch()">🔍</button>\n+ <button onclick="toggleSearch()" aria-label="Search">\n+   <span aria-hidden="true">🔍</span>\n+ </button>',
         files=["index.html", "product.html", "cart.html", "checkout.html"], final="validated"),
    dict(id="A07", wcag="2.1.1", sev="critical", src="agent", pages=["product"], sel="div.btn",
         title="“Ajouter au panier” cannot be reached with the keyboard",
         impact="The main call to action is a clickable div. Keyboard and switch users cannot add anything to their bag.",
         evidence='<div class="btn" onclick="addToCart()">Ajouter au panier</div>',
         fix='- <div class="btn" onclick="addToCart()">Ajouter au panier</div>\n+ <button type="button" class="btn" onclick="addToCart()">\n+   Ajouter au panier\n+ </button>',
         files=["product.html", "styles.css"], final="validated", reject=True),
    dict(id="A08", wcag="2.1.1", sev="critical", src="agent", pages=["product"], sel="div.size",
         title="Size selector is mouse-only and has no state",
         impact="Sizes are clickable divs with no role or selected state. Screen reader users cannot choose or confirm a size.",
         evidence='<div class="size" onclick="selectSize(this)">41</div>',
         fix='+ <fieldset class="sizes"><legend>Taille</legend>\n+   <label><input type="radio" name="size" value="41"> 41</label>\n- <div class="size" onclick="selectSize(this)">41</div>',
         files=["product.html", "styles.css"], final="validated"),
    dict(id="A09", wcag="2.1.1", sev="critical", src="agent", pages=["cart", "checkout"], sel="span.btn",
         title="“Commander” and “Payer” are not keyboard operable",
         impact="Both steps that complete a purchase are clickable elements. A keyboard user is blocked at the end of the funnel.",
         evidence='<div class="btn" onclick="pay()">Payer 268 €</div>',
         fix='- <div class="btn" onclick="pay()">Payer 268 €</div>\n+ <button type="submit" class="btn">Payer 268 €</button>',
         files=["cart.html", "checkout.html"], final="validated"),
    dict(id="A10", wcag="3.3.2", sev="critical", src="agent", pages=["checkout"], sel="#checkout-form input",
         title="Checkout fields use placeholders instead of labels",
         impact="Labels disappear while typing and are not reliably announced. Name, email and address fields are easy to confuse.",
         evidence='<input type="text" name="email" placeholder="Adresse e-mail">',
         fix='+ <label for="email">Adresse e-mail</label>\n- <input type="text" name="email" placeholder="Adresse e-mail">\n+ <input type="email" id="email" name="email" autocomplete="email">',
         files=["checkout.html"], final="validated"),
    dict(id="A11", wcag="3.3.1", sev="major", src="agent", pages=["checkout"], sel="input.error",
         title="Form errors are shown only by a red border",
         impact="Colour-blind and screen reader users are not told which field failed or why.",
         evidence="i.classList.toggle('error', !ok)",
         fix="+ i.setAttribute('aria-invalid', !ok);\n+ err.textContent = 'Saisissez une adresse e-mail valide';\n+ i.setAttribute('aria-describedby', err.id);",
         files=["checkout.html"], final="validated"),
    dict(id="A12", wcag="2.4.4", sev="minor", src="agent", pages=["home"], sel=".card a",
         title="Four identical “En savoir plus” links",
         impact="Listed out of context by a screen reader, the links are indistinguishable.",
         evidence='<a href="product.html">En savoir plus</a>',
         fix='+ <a href="product.html">En savoir plus\n+   <span class="sr-only"> sur Baskets en cuir</span></a>',
         files=["index.html", "styles.css"], final="validated"),
    dict(id="A13", wcag="1.3.1", sev="major", src="agent", pages=["home"], sel=".hero h3",
         title="Home page has no h1 and skips heading levels",
         impact="The page title is an h3 and product names are h4. Heading navigation gives no outline of the page.",
         evidence="<h3>La collection automne</h3>\n<h4>Baskets en cuir</h4>",
         fix="- <h3>La collection automne</h3>\n+ <h1>La collection automne</h1>\n- <h4>Baskets en cuir</h4>\n+ <h2>Baskets en cuir</h2>",
         files=["index.html"], final="validated"),
    dict(id="A14", wcag="2.4.2", sev="minor", src="agent", pages=["checkout"], sel="title",
         title="Checkout page title is vague",
         impact="The tab reads “Paiement” with no shop name or step, which is confusing with several tabs open.",
         evidence="<title>Paiement</title>", fix="- <title>Paiement</title>\n+ <title>Paiement · Commande · Maison Lumière</title>",
         files=["checkout.html"], final="validated"),
    dict(id="A15", wcag="4.1.2", sev="major", src="agent", pages=["cart"], sel=".qty button",
         title="Quantity and remove buttons have no accessible name",
         impact="Buttons are read as “minus”, “plus”, “wastebasket” with no product named. Users risk removing the wrong item.",
         evidence='<button onclick="removeRow(this)">🗑</button>',
         fix='- <button onclick="removeRow(this)">🗑</button>\n+ <button onclick="removeRow(this)" aria-label="Retirer Baskets en cuir, taille 40">',
         files=["cart.html"], final="validated"),
    dict(id="A16", wcag="1.3.1", sev="major", src="agent", pages=["checkout"], sel="iframe.card-field",
         title="Third-party card widget not verifiable",
         impact="The payment provider's embedded field cannot be audited from the storefront code. It may block keyboard or screen reader users.",
         evidence='<iframe title="" src="about:blank" class="card-field">',
         fix="", files=[], final="needs_human",
         human="Request the provider's accessibility conformance report and add it to the statement. Vendor responsibility."),
]
BY = {i["id"]: i for i in ISSUES}
BATCHES = [
    ("2.4.7", ["A05"], "3f2a9c1", "focus visible on all interactive elements"),
    ("2.1.1", ["A07", "A08", "A09"], "8c41d07", "native buttons and radio group for keyboard access"),
    ("3.3.2", ["A10"], "b19e6a4", "labels and autocomplete on checkout form"),
    ("4.1.2", ["A06", "A15"], "e07d3f8", "accessible names for icon buttons"),
    ("1.4.3", ["A01"], "5ad21c9", "brand-safe contrast for secondary text"),
    ("3.3.1", ["A11"], "c6f0b82", "text error messages linked to fields"),
    ("1.1.1", ["A03", "A04"], "71be4d0", "text alternatives for product images"),
    ("1.3.1", ["A13", "A16"], "0d9c5ea", "heading structure on home page"),
    ("2.4.4", ["A12"], "a4e83f1", "descriptive product links"),
    ("2.4.2", ["A14"], "2bf9e07", "descriptive checkout title"),
    ("3.1.1", ["A02"], "96c1d3b", "declare page language"),
]
SHORT_FIX = {"A02": 'lang="fr" on <html>', "A03": "alt text from product names", "A04": "draft alt text from product name",
             "A05": "global :focus-visible ring", "A06": "aria-label on header icon buttons", "A08": "radio group in a fieldset with legend",
             "A09": "native buttons", "A10": "visible labels + autocomplete", "A11": "text errors linked with aria-describedby",
             "A12": "visually hidden product names in links", "A13": "h1 + corrected heading levels", "A14": "descriptive title",
             "A15": "product-specific aria-labels"}
VERIFY = {"A02": "lang detected, French voice used", "A03": "all product images announced by name",
          "A05": "focus ring visible on 24 of 24 stops", "A06": "buttons announced as Search, Wishlist, Bag",
          "A08": "sizes reachable with arrows, selection announced", "A09": "funnel completes with keyboard only",
          "A10": "every field has a programmatic label", "A11": "error text announced and tied to its field",
          "A12": "each link names its product", "A13": "one h1, no skipped levels", "A14": "title names page, step and shop",
          "A15": "each button names its product"}

events: list[dict] = []
T = 0.0
status: dict[str, str] = {}
frozen = None
base_score = None


def emit(dt, type, data, agent=None):
    global T
    T = round(T + dt, 2)
    e = {"t": T, "type": type}
    if agent:
        e["agent"] = agent
    e["data"] = data
    events.append(e)


def log(dt, agent, text, kind="msg"):
    emit(dt, "log", {"text": text, "kind": kind}, agent)


def agent(dt, name, st, activity=""):
    emit(dt, "agent.status", {"agent": name, "status": st, "activity": activity})


def score(dt=0.0):
    its = [dict(severity=BY[i]["sev"], wcag=BY[i]["wcag"], status=s) for i, s in status.items()]
    sc = scoring.compute(its, frozen)
    emit(dt, "score", {"value": sc["value"], "baseline": base_score if base_score is not None else sc["value"],
                       "by_principle": sc["by_principle"], "eaa": sc["eaa"]})
    return sc["value"]


def set_status(dt, iid, st, by, note, attempt=1, **extra):
    status[iid] = st
    emit(dt, "issue.status", {"id": iid, "status": st, "by": by, "note": note, "attempt": attempt, **extra})
    if frozen:
        score()


def commit(dt, crit, sha, msg, files):
    m = f"fix(a11y): WCAG {crit} — {msg}"
    emit(dt, "commit.created", {"sha": sha, "criterion": crit, "message": m, "files": files})
    log(0, "orchestrator", f"Commit {sha} · {m}", "commit")


# ---------------------------------------------------------------- scenario
emit(0, "run.started", {"site": "maison-lumiere.fr", "repo": "maison-lumiere/storefront", "branch": BRANCH})
emit(0, "phase.changed", {"phase": "crawl"})
agent(0, "orchestrator", "working", "coordinating run")
log(.2, "orchestrator", "Run started on http://localhost:8765 · source repo storefront@main", "phase")
agent(.6, "cartographer", "working", "crawl_site")
log(0, "cartographer", "→ crawl_site max_pages=30", "tool")
log(1.6, "cartographer", "Found 4 pages. /checkout.html is only reachable through an onclick redirect (noted).")
for k, n in [("home", "Home"), ("product", "Product page"), ("cart", "Cart"), ("checkout", "Checkout")]:
    log(.35, "cartographer", f'→ register_page {PAGES[k]} template="{n}"', "tool")
log(.6, "cartographer", "Purchase funnel fully covered: home → product → cart → checkout.", "ok")
agent(0, "cartographer", "done", "4 pages mapped")

emit(.8, "phase.changed", {"phase": "baseline"})
agent(0, "orchestrator", "working", "measuring baseline")
log(.3, "orchestrator", f"Branch created: {BRANCH}", "tool")
emit(1.2, "baseline", {"axe_violations": 17, "unreachable": 9, "focus_visible": [0, 24]})
log(0, "orchestrator", "Baseline: 17 automated violations · 9 controls unreachable by keyboard · focus visible on 0 of 24 stops")

emit(.8, "phase.changed", {"phase": "audit"})
agent(0, "auditors", "working", "dispatching page auditors")
log(.3, "lead-auditor", "Dispatching 4 page auditors in parallel (axe + keyboard walk + expert review)")
emit(.2, "subagents", {"agent": "auditors", "states": ["working"] * 4})
PA = {k: f"auditor·{k}" for k in ALL}
for i, k in enumerate(ALL):
    log(.5 if i == 0 else .1, PA[k], f"→ audit_page {PAGES[k]}", "tool")
log(.7, "system", "Tool error: Chromium crashed during analysis (Target closed). Injected fault.", "err")
log(.6, PA["checkout"], "Transient browser crash, not a page error. Retrying once.")
log(.4, PA["checkout"], "→ audit_page /checkout.html (retry)", "tool")
log(.6, PA["checkout"], "Retry succeeded.", "ok")
ORDER = [("A02", "home"), ("A01", "home"), ("A03", "home"), ("A05", "product"), ("A07", "product"), ("A13", "home"),
         ("A08", "product"), ("A10", "checkout"), ("A06", "home"), ("A15", "cart"), ("A12", "home"), ("A09", "cart"),
         ("A11", "checkout"), ("A04", "product"), ("A14", "checkout"), ("A16", "checkout")]
done_pages = set()
for n, (iid, p) in enumerate(ORDER):
    i = BY[iid]
    if i["src"] == "agent":
        tool = "keyboard_walk" if iid in ("A05", "A07", "A08") else "get_page_html"
        log(.4, PA[p], f"→ {tool} {PAGES[p]}", "tool")
    name, level = CRIT[i["wcag"]]
    first_pages = [PAGES[p]] if iid != "A06" else [PAGES["home"]]
    if iid not in ("A06",):
        first_pages = [PAGES[x] for x in i["pages"]]
    status[iid] = "detected"
    emit(.6, "issue.detected", {
        "id": iid, "wcag": i["wcag"], "criterion_name": name, "level": level,
        "principle": scoring.principle(i["wcag"]), "en301549": "9." + i["wcag"], "title": i["title"],
        "impact": i["impact"], "evidence": i["evidence"], "severity": i["sev"], "source": i["src"],
        "selector": i["sel"], "rule": i.get("rule", ""), "pages": first_pages, "status": "detected",
        "attempts": 0, "files": [], "fix_diff": "", "fix_note": "", "human_action": "",
        "history": [{"t": T, "status": "detected", "by": PA[p], "note": "Detected during page audit"}],
    }, PA[p])
    log(0, PA[p], f"add_issue {iid} [{i['wcag']}] {i['title']}")
    if iid == "A06":
        for other in ("product", "cart", "checkout"):
            emit(.1, "issue.merged", {"id": "A06", "page": PAGES[other]}, PA[other])
        log(.2, PA["product"], "A06 merged: same component on 4 pages (shared header). One fix covers all.")
    if n in (5, 9, 13):
        emit(.1, "subagents", {"agent": "auditors", "states": ["done"] * (n // 4) + ["working"] * (4 - n // 4)})
emit(.5, "subagents", {"agent": "auditors", "states": ["done"] * 4})
log(.4, "lead-auditor", "16 issues · 13 missed by automated scanners · 5 block the purchase funnel", "ok")
frozen = scoring.frozen_total([dict(severity=i["sev"]) for i in ISSUES])
base_score = scoring.compute([dict(severity=i["sev"], wcag=i["wcag"], status="detected") for i in ISSUES], frozen)["value"]
score()
agent(0, "auditors", "done", "16 issues logged")

emit(.8, "phase.changed", {"phase": "plan"})
agent(0, "orchestrator", "working", "planning batches")
log(.4, "orchestrator", f"Grouped into {len(BATCHES)} batches by WCAG criterion, purchase blockers first.")
for b in BATCHES[:4]:
    log(.15, "orchestrator", f"Batch {b[0]}: {', '.join(b[1])}", "tool")
log(.15, "orchestrator", f"… {len(BATCHES) - 4} more batches queued", "tool")

emit(.8, "phase.changed", {"phase": "fix"})
for bi, (crit, ids, sha, msg) in enumerate(BATCHES):
    emit(.6, "batch.started", {"id": f"B{bi + 1:02d}", "criterion": crit, "issue_ids": ids, "attempt": 1})
    log(0, "orchestrator", f"Batch {bi + 1}/{len(BATCHES)} · WCAG {crit} {CRIT[crit][0]} · attempt 1/3", "phase")
    agent(0, "developer", "working", f"WCAG {crit}")
    agent(0, "tester", "idle", "waiting")
    for iid in ids:
        set_status(.1, iid, "fixing", "orchestrator", "Assigned to developer")
    files = sorted({f for iid in ids for f in BY[iid]["files"]})
    grep = "'outline: none'" if crit == "2.4.7" else "'color: #'" if crit == "1.4.3" else "'onclick=|<img|aria-'"
    log(.5, "developer", f"→ Grep {grep}", "tool")
    if files:
        log(.5, "developer", f"→ Edit {', '.join(files[:2])}{' +' + str(len(files) - 2) if len(files) > 2 else ''}", "tool")

    if crit == "1.4.3":  # rejected for visual regression, rolled back, then fixed properly
        set_status(.6, "A01", "fixed_pending", "developer", "Darkened text and hero background for 4.5:1.",
                   files=["styles.css"], fix_diff="- .hero { background: #faf7f2; }\n+ .hero { background: #3d3a35; }\n- .hero p { color: #b5b5b5; }\n+ .hero p { color: #f5f5f5; }")
        log(0, "developer", "mark_fixed A01: darkened secondary text and hero background")
        agent(0, "developer", "idle", "waiting for review")
        agent(0, "tester", "working", "compare_with_baseline")
        log(.5, "tester", "→ compare_with_baseline / · changed_pixels_ratio=0.18", "tool")
        log(.5, "tester", "→ Read shots/home.diff.png", "tool")
        set_status(.6, "A01", "rejected", "tester", "Contrast passes, but the hero background changed colour (18% of pixels). Brand regression: keep #faf7f2 and adjust text colour only.")
        log(0, "tester", "REJECTED A01: hero background changed (18% of pixels). Keep the brand background, adjust text only.", "reject")
        log(.3, "tester", "Batch verdict: regression, roll back.", "reject")
        log(.4, "orchestrator", "Rollback: git checkout -- . · retrying batch with tester feedback (attempt 2/3)", "rollback")
        emit(0, "batch.started", {"id": f"B{bi + 1:02d}", "criterion": crit, "issue_ids": ids, "attempt": 2})
        agent(0, "developer", "working", "WCAG 1.4.3 · attempt 2")
        agent(0, "tester", "idle", "waiting")
        set_status(.4, "A01", "fixing", "orchestrator", "Retry with tester feedback", attempt=2)
        log(.6, "developer", "Nearest compliant shades to the brand palette: #6b6b6b (5.3:1), #5f5a52 (6.4:1). Background untouched.")
        log(.4, "developer", "→ Edit styles.css", "tool")
        set_status(.4, "A01", "fixed_pending", "developer", "Text colours only, nearest compliant shade.", attempt=2,
                   files=BY["A01"]["files"], fix_diff=BY["A01"]["fix"])
        log(0, "developer", "mark_fixed A01: text colours only, background unchanged")
        agent(0, "developer", "idle", "")
        agent(0, "tester", "working", "compare_with_baseline")
        log(.5, "tester", "→ compare_with_baseline / · resolved 8 · regressions 0 · changed_pixels_ratio=0.01", "tool")
        set_status(.5, "A01", "validated", "tester", "All secondary text ≥ 4.5:1, design unchanged (1% pixel diff).", attempt=2)
        log(0, "tester", "A01 validated: all secondary text ≥ 4.5:1, design intact", "ok")
        commit(.4, crit, sha, msg, ["styles.css"])
        continue

    for iid in ids:
        i = BY[iid]
        if i["final"] == "needs_human" and not i["files"]:
            set_status(.5, iid, "needs_human", "developer", i["human"], human_action=i["human"])
            log(0, "developer", f"cannot_fix {iid}: third-party widget outside this repository → escalated", "reject")
        elif i.get("reject"):
            set_status(.5, iid, "fixed_pending", "developer", 'Added role="button" and aria-label to the div.',
                       files=["product.html"], fix_diff='- <div class="btn" onclick="addToCart()">Ajouter au panier</div>\n+ <div class="btn" role="button" aria-label="Ajouter au panier" onclick="addToCart()">Ajouter au panier</div>')
            log(0, "developer", f'mark_fixed {iid}: added role="button" and aria-label')
        else:
            set_status(.45, iid, "fixed_pending", "developer", SHORT_FIX.get(iid, "fixed"), files=i["files"], fix_diff=i["fix"])
            log(0, "developer", f"mark_fixed {iid}: {SHORT_FIX.get(iid, 'fixed')}")
    agent(0, "developer", "idle", "waiting for review")
    agent(0, "tester", "working", "verifying")
    pg = sorted({p for iid in ids for p in BY[iid]["pages"]}, key=ALL.index)
    log(.5, "tester", f"→ compare_with_baseline {PAGES[pg[0]]}{' +' + str(len(pg) - 1) + ' pages' if len(pg) > 1 else ''}", "tool")
    if crit in ("2.4.7", "2.1.1", "4.1.2"):
        log(.4, "tester", f"→ keyboard_walk {PAGES[pg[0]]}", "tool")
    for iid in ids:
        i = BY[iid]
        if i["final"] == "needs_human" and not i["files"]:
            continue
        if i.get("reject"):
            set_status(.5, iid, "rejected", "tester", "Cosmetic fix: the div has a role but is still not focusable, and Enter does nothing. Use a native <button>.")
            log(0, "tester", f"REJECTED {iid}: still not focusable, Enter does nothing. Use a native <button>.", "reject")
        elif i["final"] == "needs_human":
            set_status(.5, iid, "needs_human", "tester", i["human"], human_action=i["human"])
            log(0, "tester", f"{iid} needs human review: draft alt text cannot confirm colour or material", "reject")
        else:
            set_status(.45, iid, "validated", "tester", VERIFY.get(iid, "verified"))
            log(0, "tester", f"{iid} validated: {VERIFY.get(iid, 'verified')}", "ok")
    if any(BY[iid].get("reject") for iid in ids):
        log(.3, "tester", "Batch verdict: no regression. Commit validated fixes, return A07.")
        commit(.4, crit, sha, "partial: " + msg, ["product.html", "styles.css", "cart.html", "checkout.html"])
        emit(.4, "batch.started", {"id": f"B{bi + 1:02d}", "criterion": crit, "issue_ids": ["A07"], "attempt": 2})
        log(0, "orchestrator", "Batch WCAG 2.1.1 · attempt 2/3 for A07 with tester feedback", "phase")
        agent(0, "developer", "working", "A07 · attempt 2")
        agent(0, "tester", "idle", "waiting")
        set_status(.3, "A07", "fixing", "orchestrator", "Retry with tester feedback", attempt=2)
        log(.6, "developer", '→ Edit product.html (div → <button type="button">)', "tool")
        set_status(.4, "A07", "fixed_pending", "developer", "Replaced div with native button; styles kept.", attempt=2,
                   files=BY["A07"]["files"], fix_diff=BY["A07"]["fix"])
        log(0, "developer", "mark_fixed A07: native <button>, same styling")
        agent(0, "developer", "idle", "")
        agent(0, "tester", "working", "keyboard_walk")
        log(.5, "tester", "→ keyboard_walk /product.html · Tab reaches “Ajouter au panier”, Enter adds item", "tool")
        set_status(.5, "A07", "validated", "tester", "Reachable by Tab, operable with Enter and Space, announced as button.", attempt=2)
        log(0, "tester", "A07 validated: reachable by Tab, works with Enter and Space", "ok")
        commit(.4, crit, "d27a8f3", "native button for Ajouter au panier", ["product.html"])
        continue
    if any(BY[iid]["files"] and BY[iid]["final"] == "validated" for iid in ids):
        commit(.4, crit, sha, msg, files)
agent(0, "developer", "done", "all batches processed")
agent(0, "tester", "done", "")

emit(.8, "phase.changed", {"phase": "reaudit"})
agent(0, "orchestrator", "working", "independent re-audit")
emit(1.2, "reaudit", {"axe_violations": 0, "unreachable": 0, "focus_visible": [24, 24]})
log(0, "orchestrator", "Re-audit: automated violations 17 → 0 · unreachable controls 9 → 0 · focus visible 0 → 24 of 24 stops", "ok")

emit(.8, "phase.changed", {"phase": "report"})
agent(0, "writer", "working", "writing")
fixed = [i for i in ISSUES if status[i["id"]] == "validated"]
human = [i for i in ISSUES if status[i["id"]] == "needs_human"]
commits = [e["data"] for e in events if e["type"] == "commit.created"]
pr_body = (
    "## Summary\n\n"
    f"This PR remediates {len(fixed)} WCAG 2.1 AA issues found by the Arma audit of maison-lumiere.fr "
    "(4 page templates covering the full purchase funnel). Each commit maps to one WCAG criterion and every fix "
    "was verified by an independent tester agent.\n\n"
    f"- Score: {base_score} → {scoring.compute([dict(severity=i['sev'], wcag=i['wcag'], status=status[i['id']]) for i in ISSUES], frozen)['value']}\n"
    "- Automated violations: 17 → 0\n- Controls unreachable by keyboard: 9 → 0\n\n"
    "## Changes by criterion\n\n"
    + "".join(f"### WCAG {c} {CRIT[c][0]}\n" + "".join(f"- {BY[x]['id']}: {BY[x]['title']}\n" for x in ids if status[x] == "validated") + "\n"
              for c, ids, _, _ in BATCHES if any(status[x] == "validated" for x in ids))
    + "## Needs human review\n\n" + "".join(f"- **{i['id']}** ({i['wcag']}) {i['title']}: {i['human']}\n" for i in human)
)
statement = (
    "# Accessibility statement · Maison Lumière\n\n"
    "Maison Lumière is committed to making maison-lumiere.fr accessible, in line with the European Accessibility Act "
    "and the French law transposing it.\n\n"
    "## Compliance status\n\nThe website is **partially compliant** with EN 301 549 v3.2.1 and WCAG 2.1 level AA, "
    "due to the non-compliant content listed below.\n\n"
    "## Non-accessible content\n\n" + "".join(f"- {i['title']} (WCAG {i['wcag']}). {i['human']}\n" for i in human)
    + "\n## How this statement was prepared\n\nAudit of 4 page templates covering the full purchase funnel on "
    "15 October 2026, combining automated testing (axe-core), keyboard testing and expert review by AI agents, with "
    "independent verification of every fix. Testing with disabled users: [TO COMPLETE].\n\n"
    "## Feedback and contact\n\nIf you cannot access content or a service, contact [TO COMPLETE: accessibility contact email]. "
    "We respond within [TO COMPLETE: time frame].\n\n"
    "## Enforcement\n\nIf you are not satisfied with our response, you can contact the market surveillance authority: "
    "[TO COMPLETE: national authority].\n"
)
log(.8, "writer", "→ Write pr-body.md", "tool")
emit(0, "document.written", {"name": "pr-body.md", "path": "state/out/pr-body.md", "content": pr_body}, "writer")
log(.6, "writer", "→ Write accessibility-statement.md (status: partially compliant)", "tool")
emit(0, "document.written", {"name": "accessibility-statement.md", "path": "state/out/accessibility-statement.md", "content": statement}, "writer")
agent(.5, "writer", "done", "2 documents")

emit(.6, "phase.changed", {"phase": "pr"})
all_files = sorted({f for c in commits for f in c["files"]})
emit(.4, "pr.ready", {"repo": "maison-lumiere/storefront", "branch": BRANCH, "base": "main",
                      "commits": len(commits), "files": all_files, "body": pr_body})
log(0, "orchestrator", f"Branch ready: {len(commits)} commits, {len(all_files)} files changed. Waiting for compliance sign-off to send to engineering.", "ok")
agent(0, "orchestrator", "done", "awaiting sign-off")
emit(.2, "run.finished", {"cost_usd": 0.0, "duration_s": T})
# The compliance sign-off (human click) — the dashboard ignores it in replay and simulates it on click.
emit(1.0, "pr.sent", {"number": 218, "url": "", "simulated": True, "by": "compliance",
                      "notified": ["Slack #eng-frontend", "Jira A11Y-42"]})

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
print(f"wrote {len(events)} events to {OUT.relative_to(ROOT)}")
