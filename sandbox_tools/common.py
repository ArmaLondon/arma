"""Shared helpers for Arma's sandbox tools (run inside the Managed Agents sandbox with bash).

Every script prints one JSON object on stdout. On failure it prints {"error": "..."} with an
actionable message and exits non-zero; it never dies with an unhandled traceback.
Env: ARMA_CHROMIUM (optional browser binary; default: Playwright's bundled Chromium), ARMA_WORK (default /workspace/arma),
ARMA_BASE (site root, default http://127.0.0.1:8765/).
"""
import json
import os
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

HERE = Path(__file__).resolve().parent
AXE_JS = (HERE / "vendor" / "axe.min.js").read_text()
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
VIEWPORT = {"width": 1280, "height": 800}
WORK = Path(os.environ.get("ARMA_WORK", "/workspace/arma"))
BASE = os.environ.get("ARMA_BASE", "http://127.0.0.1:8765/")
MAX_NODES = 6


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def fail(msg):
    out({"error": msg}, 1)


def main(fn):
    """Run fn() and turn any exception into an actionable JSON error."""
    try:
        out(fn())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc().strip().splitlines()[-1]
        hint = ""
        if "Executable doesn't exist" in str(e) or "No such file" in str(e):
            hint = " Unset ARMA_CHROMIUM to use Playwright's bundled Chromium (/usr/bin/chromium-browser is a snap wrapper that does not run). Never run playwright install."
        elif "ERR_CONNECTION_REFUSED" in str(e):
            hint = " The site is not served: run `python -m http.server 8765 -d /workspace/site &` first."
        fail(f"{type(e).__name__}: {str(e)[:300]} ({tb[:200]}).{hint} This may be transient: retry once.")


def launch(p):
    # Playwright's bundled Chromium (present in the sandbox image) by default. /usr/bin/chromium-browser on
    # Ubuntu is only a snap wrapper and does not run: set ARMA_CHROMIUM only to a real binary.
    kw = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    exe = os.environ.get("ARMA_CHROMIUM")
    if exe and Path(exe).exists():
        kw["executable_path"] = exe
    return p.chromium.launch(**kw)


def open_page(browser, url):
    page = browser.new_page(viewport=VIEWPORT, reduced_motion="reduce")
    page.goto(url, wait_until="load")
    return page


def norm(url):
    url = urldefrag(url)[0]
    return url[: -len("index.html")] if url.endswith("/index.html") else url


def path_of(url):
    return urlparse(norm(url)).path or "/"


def slug(url):
    p = path_of(url).strip("/") or "index"
    return re.sub(r"[^a-zA-Z0-9]+", "_", p)


def wcag_from_tags(tags):
    res = []
    for t in tags:
        if re.fullmatch(r"wcag\d{3,4}", t):
            d = t[4:]
            res.append(f"{d[0]}.{d[1]}.{d[2:]}")
    return res


LINKS_JS = """() => ({hrefs: [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')),
  onclick: [...document.querySelectorAll('[onclick]')].map(e => e.getAttribute('onclick')), title: document.title})"""
LOCATION_RE = re.compile(r"""location(?:\.href)?\s*=\s*['"]([^'"]+)['"]""")


def crawl(browser, start, max_pages=30):
    start = norm(start)
    origin = urlparse(start).netloc
    seen, queue, pages = {start}, [start], []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        page = browser.new_page(viewport=VIEWPORT)
        try:
            resp = page.goto(url, wait_until="load")
            if resp and resp.status >= 400:
                continue
            found = page.evaluate(LINKS_JS)
        finally:
            page.close()
        entry = {"url": url, "path": path_of(url), "title": found["title"]}
        targets = [(h, "link") for h in found["hrefs"]]
        for js in found["onclick"]:
            targets += [(m, "onclick") for m in LOCATION_RE.findall(js or "")]
        for href, via in targets:
            if href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            nxt = norm(urljoin(url, href))
            if urlparse(nxt).netloc == origin and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
                if via == "onclick":
                    entry.setdefault("reachable_only_via_onclick", []).append(path_of(nxt))
        pages.append(entry)
    return pages


def axe(page):
    page.add_script_tag(content=AXE_JS)
    res = page.evaluate("tags => axe.run({runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']})", AXE_TAGS)
    vs = []
    for v in res["violations"]:
        vs.append({"rule": v["id"], "impact": v["impact"], "help": v["help"], "wcag": wcag_from_tags(v["tags"]),
                   "count": len(v["nodes"]),
                   "nodes": [{"target": " >> ".join(str(t) for t in n["target"]), "html": n["html"][:160]}
                             for n in v["nodes"][:MAX_NODES]]})
    return vs


SELECTOR_JS = """el => { const part = e => { if (e.id) return '#' + e.id; let s = e.tagName.toLowerCase();
  const cls = [...e.classList].slice(0, 2); if (cls.length) s += '.' + cls.join('.');
  const sib = e.parentElement ? [...e.parentElement.children].filter(c => c.tagName === e.tagName) : [];
  if (sib.length > 1) s += `:nth-of-type(${sib.indexOf(e) + 1})`; return s; };
  const parts = []; for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) { parts.unshift(part(e)); if (e.id) break; }
  return parts.join(' > ') || el.tagName.toLowerCase(); }"""
FOCUS_JS = """() => { const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const cs = getComputedStyle(el); const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
  const shadow = cs.boxShadow && cs.boxShadow !== 'none';
  const name = (el.getAttribute('aria-label') || (el.labels && el.labels[0] ? el.labels[0].innerText : '') || el.innerText ||
    el.getAttribute('alt') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
  return {selector: (%s)(el), tag: el.tagName.toLowerCase(), name,
    focus_visible: el.tagName === 'IFRAME' ? null : (outline || shadow)}; }""" % SELECTOR_JS
UNREACHABLE_JS = """() => [...document.querySelectorAll('[onclick], .btn, [role=button]')]
  .filter(e => e.tabIndex < 0 || e.disabled)
  .map(e => ({selector: (%s)(e), tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '', text: e.innerText.trim().slice(0, 50)}))""" % SELECTOR_JS


def keyboard(page, max_tabs=40):
    stops, cycle = [], False
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        info = page.evaluate(FOCUS_JS)
        if info is None:
            if stops:
                cycle = True
                break
            continue
        if stops and info["selector"] == stops[0]["selector"]:
            cycle = True
            break
        if stops and info["selector"] == stops[-1]["selector"]:
            continue
        stops.append(info)
    unreachable = page.evaluate(UNREACHABLE_JS)
    meas = [s for s in stops if s["focus_visible"] is not None]
    return {"stops": stops, "cycle_complete": cycle, "focus_visible": [sum(1 for s in meas if s["focus_visible"]), len(meas)],
            "unreachable": unreachable}


def visual_diff(before, after, outp, threshold=24):
    from PIL import Image, ImageChops
    a, b = Image.open(before).convert("RGB"), Image.open(after).convert("RGB")
    size = (max(a.width, b.width), max(a.height, b.height))
    pa, pb = Image.new("RGB", size, "white"), Image.new("RGB", size, "white")
    pa.paste(a)
    pb.paste(b)
    mask = ImageChops.difference(pa, pb).convert("L").point(lambda v: 255 if v > threshold else 0)
    changed = mask.histogram()[255]
    overlay = Image.blend(pb, Image.new("RGB", size, "white"), 0.6)
    overlay.paste(Image.new("RGB", size, (220, 0, 0)), mask=mask)
    Path(outp).parent.mkdir(parents=True, exist_ok=True)
    overlay.save(outp)
    return round(changed / (size[0] * size[1]), 4)


def measure_all(browser, pages, shots_dir):
    """axe + keyboard + full-page screenshot for every page."""
    res = {}
    for pg in pages:
        url = pg["url"] if isinstance(pg, dict) else pg
        page = open_page(browser, url)
        shot = Path(shots_dir) / f"{slug(url)}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot), full_page=True)
        res[path_of(url)] = {"url": url, "axe": axe(page), "screenshot": str(shot)}
        page.close()
        page = open_page(browser, url)
        res[path_of(url)]["keyboard"] = keyboard(page)
        page.close()
    return res


def summary(measures):
    fv = [0, 0]
    for m in measures.values():
        fv[0] += m["keyboard"]["focus_visible"][0]
        fv[1] += m["keyboard"]["focus_visible"][1]
    return {"pages": len(measures), "axe_violations": sum(v["count"] for m in measures.values() for v in m["axe"]),
            "unreachable": sum(len(m["keyboard"]["unreachable"]) for m in measures.values()), "focus_visible": fv}


def violation_keys(m):
    return {(v["rule"], n["target"]) for v in m["axe"] for n in v["nodes"]}


def pages_list():
    f = WORK / "pages.json"
    if f.exists():
        return json.loads(f.read_text())
    return None
