"""Deterministic browser tools (spec §8, "effect" column). No Claude calls here.

Every function launches its own Chromium under a shared semaphore, so MCP tools can run them in
parallel (one page-auditor per page) without exhausting the machine.
"""

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from PIL import Image, ImageChops
from playwright.async_api import Browser, Page, async_playwright

from .config import ROOT

AXE_JS = (ROOT / "vendor" / "axe.min.js").read_text()
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
VIEWPORT = {"width": 1280, "height": 800}
MAX_NODES = 8          # nodes kept per axe rule (count keeps the real total)
DIFF_THRESHOLD = 24    # grey-level delta above which a pixel counts as changed

_sem = asyncio.Semaphore(4)


@asynccontextmanager
async def _browser():
    async with _sem, async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            yield browser
        finally:
            await browser.close()


async def _open(browser: Browser, url: str) -> Page:
    page = await browser.new_page(viewport=VIEWPORT, reduced_motion="reduce")
    await page.goto(url, wait_until="load")
    return page


def _norm(url: str) -> str:
    url = urldefrag(url)[0]
    return url[: -len("index.html")] if url.endswith("/index.html") else url


def wcag_from_tags(tags: list[str]) -> list[str]:
    """axe tags → success criteria: wcag143 → 1.4.3, wcag1410 → 1.4.10."""
    out = []
    for tag in tags:
        if re.fullmatch(r"wcag\d{3,4}", tag):
            d = tag[4:]
            out.append(f"{d[0]}.{d[1]}.{d[2:]}")
    return out


# ---------------------------------------------------------------- crawl

_LINKS_JS = """() => {
  const hrefs = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'));
  const onclick = [...document.querySelectorAll('[onclick]')].map(e => e.getAttribute('onclick'));
  return {hrefs, onclick, title: document.title};
}"""
_LOCATION_RE = re.compile(r"""location(?:\.href)?\s*=\s*['"]([^'"]+)['"]""")


async def crawl(base_url: str, max_pages: int = 30) -> list[dict]:
    """Breadth-first crawl of internal pages, including navigation hidden in onclick handlers."""
    start = _norm(base_url)
    origin = urlparse(start).netloc
    seen, queue, pages = {start}, [start], []
    async with _browser() as browser:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            page = await browser.new_page(viewport=VIEWPORT)
            try:
                resp = await page.goto(url, wait_until="load")
                if resp and resp.status >= 400:
                    continue
                found = await page.evaluate(_LINKS_JS)
            except Exception:
                continue
            finally:
                await page.close()
            targets = [(h, "link") for h in found["hrefs"]]
            for js in found["onclick"]:
                targets += [(m, "onclick") for m in _LOCATION_RE.findall(js or "")]
            pages.append({"url": url, "title": found["title"]})
            for href, via in targets:
                if href.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                nxt = _norm(urljoin(url, href))
                if urlparse(nxt).netloc == origin and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
                    if via == "onclick":
                        pages[-1].setdefault("hidden_links", []).append(nxt)
    return pages


# ---------------------------------------------------------------- axe

async def axe_audit(url: str, screenshot_path: str | Path | None = None) -> dict:
    async with _browser() as browser:
        page = await _open(browser, url)
        await page.add_script_tag(content=AXE_JS)
        res = await page.evaluate(
            "tags => axe.run({runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']})",
            AXE_TAGS,
        )
        if screenshot_path:
            Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=True)
    violations = []
    for v in res["violations"]:
        nodes = [{
            "target": " >> ".join(str(t) for t in n["target"]),
            "html": n["html"][:200],
            "summary": (n.get("failureSummary") or "")[:300],
        } for n in v["nodes"][:MAX_NODES]]
        violations.append({
            "rule": v["id"], "impact": v["impact"], "help": v["help"],
            "wcag": wcag_from_tags(v["tags"]), "nodes": nodes, "count": len(v["nodes"]),
        })
    return {"url": url, "violations": violations,
            "total_nodes": sum(v["count"] for v in violations)}


# ---------------------------------------------------------------- keyboard

_SELECTOR_JS = """el => {
  const part = e => {
    if (e.id) return '#' + e.id;
    let s = e.tagName.toLowerCase();
    const cls = [...e.classList].slice(0, 2);
    if (cls.length) s += '.' + cls.join('.');
    const sib = e.parentElement ? [...e.parentElement.children].filter(c => c.tagName === e.tagName) : [];
    if (sib.length > 1) s += `:nth-of-type(${sib.indexOf(e) + 1})`;
    return s;
  };
  const parts = [];
  for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
    parts.unshift(part(e));
    if (e.id) break;
  }
  return parts.join(' > ') || el.tagName.toLowerCase();
}"""

_FOCUS_JS = """() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const sel = (%s)(el);
  const cs = getComputedStyle(el);
  const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
  const shadow = cs.boxShadow && cs.boxShadow !== 'none';
  const r = el.getBoundingClientRect();
  const labelled = el.getAttribute('aria-labelledby');
  const label = el.labels && el.labels[0] ? el.labels[0].innerText : '';
  const name = (el.getAttribute('aria-label') ||
    (labelled && document.getElementById(labelled)?.innerText) || label ||
    el.innerText || el.getAttribute('alt') || el.getAttribute('title') ||
    el.getAttribute('placeholder') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
  return {selector: sel, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
          name, name_source: el.getAttribute('aria-label') ? 'aria-label' : label ? 'label'
            : el.innerText?.trim() ? 'text' : el.getAttribute('placeholder') ? 'placeholder' : 'none',
          // focus inside an embedded frame is drawn by the frame's own document: not measurable here
          focus_visible: el.tagName === 'IFRAME' ? null : (outline || shadow),
          ...(el.tagName === 'IFRAME' ? {note: 'focus is inside an embedded frame (third-party content); its focus style cannot be measured from this page'} : {}),
          on_screen: r.width > 0 && r.height > 0};
}""" % _SELECTOR_JS

_UNREACHABLE_JS = """() => [...document.querySelectorAll('[onclick], .btn, [role=button]')]
  .filter(e => e.tabIndex < 0 || e.disabled)
  .map(e => ({selector: (%s)(e), tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '',
              text: e.innerText.trim().slice(0, 60), onclick: (e.getAttribute('onclick') || '').slice(0, 80)}))
""" % _SELECTOR_JS


async def keyboard_walk(url: str, max_tabs: int = 40) -> dict:
    """Tab through the page: focus order, accessible names, visible focus, unreachable controls."""
    async with _browser() as browser:
        page = await _open(browser, url)
        stops, cycle = [], False
        for _ in range(max_tabs):
            await page.keyboard.press("Tab")
            info = await page.evaluate(_FOCUS_JS)
            if info is None:            # focus left the document: one full cycle done
                cycle = bool(stops)
                if cycle:
                    break
                continue
            if stops and info["selector"] == stops[0]["selector"]:
                cycle = True
                break
            if stops and info["selector"] == stops[-1]["selector"]:
                continue                # tabbing inside an iframe keeps the same host element
            stops.append(info)
        unreachable = await page.evaluate(_UNREACHABLE_JS)
    measurable = [s for s in stops if s["focus_visible"] is not None]
    visible = sum(1 for s in measurable if s["focus_visible"])
    return {"url": url, "stops": stops, "cycle_complete": cycle,
            "focus_visible": [visible, len(measurable)], "unreachable": unreachable}


# ---------------------------------------------------------------- html / screenshots

async def page_html(url: str, max_chars: int = 15000) -> str:
    async with _browser() as browser:
        page = await _open(browser, url)
        html = await page.content()
    if len(html) > max_chars:
        html = html[:max_chars] + f"\n<!-- truncated: {len(html) - max_chars} more chars -->"
    return html


async def screenshot(url: str, path: str | Path) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with _browser() as browser:
        page = await _open(browser, url)
        await page.screenshot(path=str(path), full_page=True)
    return str(path)


def _visual_diff(before: Path, after: Path, out: Path) -> float:
    a, b = Image.open(before).convert("RGB"), Image.open(after).convert("RGB")
    size = (max(a.width, b.width), max(a.height, b.height))
    pa, pb = Image.new("RGB", size, "white"), Image.new("RGB", size, "white")
    pa.paste(a)
    pb.paste(b)
    mask = ImageChops.difference(pa, pb).convert("L").point(lambda v: 255 if v > DIFF_THRESHOLD else 0)
    changed = mask.histogram()[255]
    overlay = Image.blend(pb, Image.new("RGB", size, "white"), 0.6)
    overlay.paste(Image.new("RGB", size, (220, 0, 0)), mask=mask)
    out.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(out)
    return round(changed / (size[0] * size[1]), 4)


async def visual_diff(before: str | Path, after: str | Path, out: str | Path) -> float:
    """Share of changed pixels between two screenshots; writes a red overlay image to `out`."""
    return await asyncio.to_thread(_visual_diff, Path(before), Path(after), Path(out))
