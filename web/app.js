"use strict";
/* Arma dashboard. A pure function of the event stream (arma-spec.md §10): state = events.reduce(apply).
   Live agent workflow, gauge and charts are drawn with D3 (web/vendor/d3.min.js). */

/* ------------------------------------------------------------------ constants */
const PRIN = {P: "Perceivable", O: "Operable", U: "Understandable", R: "Robust"};
const PHASES = [["crawl","Map site"],["baseline","Baseline"],["audit","Audit"],["plan","Plan"],["fix","Fix & verify"],["reaudit","Re-audit"],["report","Report"],["pr","Pull request"]];
const TEAM = [["lead","Lead"],["auditors","Page auditors"],["developer","Developer"],["tester","Tester"],["writer","Writer"]];
const STL = {detected:["Detected","p-bad"], fixing:["Developer fixing","p-info"], fixed_pending:["Tester verifying","p-info"],
             rejected:["Rejected, retrying","p-warn"], validated:["Fixed and verified","p-ok"], needs_human:["Needs review","p-warn"]};
const EAA = {non_compliant:"EAA: non-compliant", partially_compliant:"EAA: partially compliant", compliant_automated:"EAA: compliant (automated scope)"};
const OUTCOME = {satisfied:["Satisfied","p-ok"], needs_revision:["Needs revision","p-warn"], max_iterations_reached:["Max iterations reached","p-bad"], failed:["Failed","p-bad"]};
const METRIC_NAMES = {recall_all:"Recall, all defects", recall_agent_only:"Recall, defects scanners miss", precision:"Precision",
                      verified_fix_rate:"Verified fix rate", false_fix:"False fixes", regressions:"Regressions", honesty:"Honest escalations"};
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const DEMO_SITE = "maison-lumiere.fr";

/* problem types in plain language, for the compliance team (WCAG criterion → type) */
const CATS = [
  {k: "keyboard", n: "Can't be used without a mouse", d: "Buttons, choices or menus that keyboard and switch users cannot reach.", w: ["2.1.1", "2.1.2", "2.4.3", "2.4.1"]},
  {k: "focus", n: "Keyboard position is invisible", d: "Keyboard users cannot see which element they are on.", w: ["2.4.7"]},
  {k: "names", n: "Buttons without a clear name", d: "Screen readers announce icons or symbols instead of what the button does.", w: ["4.1.2", "2.5.3"]},
  {k: "forms", n: "Forms hard to fill in", d: "Missing labels, unclear errors or no autofill hints at checkout.", w: ["3.3.1", "3.3.2", "3.3.3", "3.3.4", "1.3.5"]},
  {k: "contrast", n: "Text too faint to read", d: "Low contrast or meaning carried by colour alone.", w: ["1.4.3", "1.4.11", "1.4.1"]},
  {k: "images", n: "Images not described", d: "Blind shoppers get no description of products and pictures.", w: ["1.1.1"]},
  {k: "structure", n: "Confusing page structure", d: "Headings, tables or embedded widgets that assistive technology cannot follow.", w: ["1.3.1", "2.4.6", "1.3.2"]},
  {k: "links", n: "Links that don't say where they go", d: "Repeated \u201cLearn more\u201d links with no context.", w: ["2.4.4"]},
  {k: "lang", n: "Page language or title missing", d: "Wrong voice or vague tab titles for screen reader users.", w: ["3.1.1", "3.1.2", "2.4.2"]},
  {k: "status", n: "Updates not announced", d: "Cart or error messages that appear silently.", w: ["4.1.3"]},
];
const CAT_OF = Object.fromEntries(CATS.flatMap((c) => c.w.map((w) => [w, c])));
const OTHER = {k: "other", n: "Other WCAG problems", d: "Other WCAG 2.1 AA criteria."};
const catOf = (wcag) => CAT_OF[wcag] || OTHER;
/* page path or auditor label → page key ("/" and "home" → "home", "/cart.html" → "cart") */
function pageKey(p) {
  const s = String(p || "").replace(/^https?:\/\/[^/]+/, "").replace(/[?#].*$/, "");
  if (s === "" || s === "/" || /\/index\.html?$/.test(s) || s === "home" || s === "index") return "home";
  return s.replace(/^.*\//, "").replace(/\.html?$/, "") || "home";
}
const PAGE_NAME = {home: "Home", product: "Product page", cart: "Cart", checkout: "Checkout", category: "Category"};
const pageName = (k) => PAGE_NAME[k] || k.charAt(0).toUpperCase() + k.slice(1);

/* agent labels: hosted team (lead, auditor·page, developer, tester, writer) + older SDK recordings */
function teamKey(a) {
  if (!a) return "lead";
  if (a.startsWith("auditor")) return "auditors";
  if (["lead", "developer", "tester", "writer"].includes(a)) return a;
  return null;
}

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const mmss = (t) => { const s = Math.max(0, Math.floor(t || 0)); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };
const clip = (s, n) => (s = String(s || "")).length > n ? s.slice(0, n - 1) + "…" : s;

/* ------------------------------------------------------------------ state + reducer */
function initial() {
  return {t: 0, site: "maison-lumiere.fr", repo: "", branch: "", session: "", phase: null, agents: {}, act: {}, subagents: [],
          logs: [], issues: {}, order: [], score: null, scoreHist: [], rejects: [], commits: [], docs: {}, pr: null, prSent: null,
          baselineMetrics: null, reauditMetrics: null, outcomes: [], evalRes: null, finished: false, cost: 0,
          counts: {fixes: 0, rejected: 0, validated: 0, rollbacks: 0, human: 0, batches: 0}, now: null, fresh: new Set(),
          scanned: new Set(), scanning: new Set(), pages: []};
}

function apply(S, ev) {
  const d = ev.data || {};
  S.t = Math.max(S.t, ev.t || 0);
  switch (ev.type) {
    case "run.started": {
      const f = initial();
      Object.assign(S, f, {site: d.site || f.site, repo: d.repo || "", branch: d.branch || "", session: d.session_id || "", t: ev.t || 0});
      break;
    }
    case "phase.changed": S.phase = d.phase; break;
    case "agent.status": {
      const k = teamKey(d.agent) || d.agent;
      S.agents[k] = d.status;
      if ("activity" in d) S.act[k] = d.activity;
      break;
    }
    case "subagents": S.subagents = d.states || []; break;
    case "log": {
      const a = ev.agent || "lead";
      S.logs.push({t: ev.t, a, text: d.text, kind: d.kind || "msg"});
      const k = teamKey(a);
      if (k && d.kind !== "tool") S.act[k] = d.text;
      if (d.kind !== "tool") S.now = {a, text: d.text, kind: d.kind};
      if (d.kind === "rollback") S.counts.rollbacks++;
      if (a.startsWith("auditor·")) {
        const pk = pageKey(a.slice(8));
        if (/\bfinished\b|\bfailed\b/.test(d.text)) { S.scanning.delete(pk); S.scanned.add(pk); }
        else if (!S.scanned.has(pk)) S.scanning.add(pk);
        if (!S.pages.includes(pk)) S.pages.push(pk);
      }
      // pages announced at mapping time (hosted: "register_page /cart.html (cart)"; SDK: "Registered /cart.html as …")
      const reg = /^(?:register_page|Registered)\s+(\S+)/.exec(d.text || "");
      if (reg && !S.pages.includes(pageKey(reg[1]))) S.pages.push(pageKey(reg[1]));
      // the lead logs "auditor·cart finished" when a thread ends
      const fin = /^(auditor·\S+) (finished|failed)/.exec(d.text || "");
      if (fin) { const pk = pageKey(fin[1].slice(8)); S.scanning.delete(pk); S.scanned.add(pk); }
      break;
    }
    case "baseline": S.baselineMetrics = d; break;
    case "issue.detected":
      if (!S.issues[d.id]) S.order.push(d.id);
      S.issues[d.id] = {pages: [], history: [], files: [], fix_diff: "", human_action: "", attempts: 0, ...d};
      S.fresh.add(d.id);
      for (const pg of d.pages || []) if (!S.pages.includes(pageKey(pg))) S.pages.push(pageKey(pg));
      break;
    case "issue.merged": {
      const i = S.issues[d.id];
      if (i && !i.pages.includes(d.page)) i.pages = [...i.pages, d.page];
      if (!S.pages.includes(pageKey(d.page))) S.pages.push(pageKey(d.page));
      break;
    }
    case "issue.status": {
      const i = S.issues[d.id]; if (!i) break;
      i.status = d.status;
      i.attempts = Math.max(i.attempts || 0, d.attempt || 0);
      if (d.fix_diff) i.fix_diff = d.fix_diff;
      if (d.files && d.files.length) i.files = d.files;
      if (d.human_action) i.human_action = d.human_action;
      i.history = [...i.history, {t: ev.t, status: d.status, by: d.by, note: d.note}];
      if (d.status === "fixed_pending") S.counts.fixes++;
      if (d.status === "rejected") { S.counts.rejected++; S.rejects.push({t: ev.t, id: d.id}); }
      if (d.status === "validated") S.counts.validated++;
      if (d.status === "needs_human") S.counts.human++;
      break;
    }
    case "score": S.score = d; S.scoreHist.push({t: ev.t, v: d.value}); break;
    case "batch.started": S.counts.batches++; break;
    case "commit.created": S.commits.push(d); break;
    case "reaudit": S.reauditMetrics = d; break;
    case "document.written": S.docs[d.name] = d; break;
    case "outcome": S.outcomes.push(d); break;
    case "eval": S.evalRes = d; break;
    case "pr.ready": S.pr = d; break;
    case "pr.sent": S.prSent = d; break;
    case "run.finished": S.finished = true; S.cost = d.cost_usd || 0; break;
  }
  return S;
}

/* ------------------------------------------------------------------ sources */
async function loadJSONL(url) {
  const r = await fetch(url, {cache: "no-store"});
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return (await r.text()).split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));
}

class ReplaySource {
  constructor(url) { this.url = url; this.events = []; this.timer = null; this.speed = 2; }
  async load() { this.events = await loadJSONL(this.url); return this.events; }
  start(speed, onEvent, onEnd) {
    this.speed = speed; let i = 0, vt = 0, last = performance.now();
    this.timer = setInterval(() => {
      const now = performance.now(); vt += (now - last) / 1000 * this.speed; last = now;
      while (i < this.events.length && this.events[i].t <= vt) onEvent(this.events[i++]);
      if (i >= this.events.length) { this.stop(); onEnd(); }
    }, 50);
  }
  stop() { clearInterval(this.timer); this.timer = null; }
}

class LiveSource {
  constructor(url = "/api/events") { this.url = url; }
  start(onEvent, onEnd, onError) {
    this.es = new EventSource(this.url);
    this.es.onmessage = (m) => { const ev = JSON.parse(m.data); onEvent(ev); if (ev.type === "run.finished") { this.stop(); onEnd(); } };
    this.es.onerror = () => { this.stop(); onError(); };
  }
  stop() { if (this.es) this.es.close(); this.es = null; }
}

/* ------------------------------------------------------------------ app */
let S = initial(), mode = "replay", speed = 2, running = false, source = null, recording = null;
let filter = "all", expanded = new Set(), logRendered = 0, dirty = false;

function onEvent(ev) {
  if (mode === "replay" && ev.type === "pr.sent") return; // the compliance click is simulated in replay
  apply(S, ev); fx(ev); schedule();
}
function schedule() { if (dirty) return; dirty = true; requestAnimationFrame(() => { dirty = false; render(); }); }

function resetView() {
  S = initial(); logRendered = 0; $("log").innerHTML = ""; expanded.clear(); drawGauge.prev = null; tilesKey = catsKey = "";
  $("p-pr").dataset.ready = ""; $("p-stmt").dataset.ready = ""; selectTab("findings");
}

function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 4500);
}

async function runAudit(target) {
  if (running) return stopRun();
  if (mode === "live") {
    try {
      const r = await fetch("/api/run", {method: "POST", headers: {"Content-Type": "application/json"},
                                         body: JSON.stringify(target ? {url: target} : {demo: true})});
      if (!r.ok && r.status !== 409) throw new Error(String(r.status));
      resetView(); running = true; updButtons();
      source = new LiveSource();
      source.start(onEvent, () => { running = false; schedule(); }, () => {
        running = false; toast("Live connection lost. Showing the recorded run instead."); mode = "replay"; runAudit();
      });
      return;
    } catch (e) {
      if (target) { $("targetMsg").textContent = `Could not start an audit of ${target}: the Arma backend did not answer. Nothing was audited.`; return; }
      toast("Live backend unavailable. Replaying the recorded run."); mode = "replay";
    }
  }
  if (!recording || !recording.events.length) { toast("No recorded run available."); return; }
  resetView(); running = true; updButtons(); render();
  source = recording;
  source.start(speed, onEvent, () => { running = false; schedule(); });
}

function stopRun() {
  if (source) source.stop();
  running = false;
  if (mode === "replay" && recording) restAt(recording.events); // jump to the end state
  schedule();
}

function restAt(events) {
  S = initial(); logRendered = 0; $("log").innerHTML = ""; drawGauge.prev = null; tilesKey = catsKey = "";
  $("p-pr").dataset.ready = ""; $("p-stmt").dataset.ready = "";
  for (const ev of events) if (ev.type !== "pr.sent") apply(S, ev);
  S.fresh.clear();
}

/* ------------------------------------------------------------------ render */
function render() {
  const ae = document.activeElement, focusedRow = ae && ae.matches && ae.matches(".rowbtn") ? ae.dataset.id : null;
  renderHeader(); renderFlow(); renderProgress(); renderTiles(); renderScore(); renderCats(); renderProof(); renderLog(); renderRows(); renderPR(); renderStmt(); updButtons();
  S.fresh.clear();
  if (focusedRow) { const r = document.querySelector(`.rowbtn[data-id="${CSS.escape(focusedRow)}"]`); if (r) r.focus({preventScroll: true}); }
}

function renderHeader() {
  $("siteName").textContent = S.site || "maison-lumiere.fr";
  $("siteRef").textContent = S.branch ? `storefront, ${S.branch}` : "storefront, main";
  $("liveDot").className = "dot" + (running ? " live" : "");
  $("clock").textContent = running ? `Running, ${mmss(S.t)} elapsed` : (S.finished ? `Last run: ${mmss(S.t)} of agent time` : "Idle");
  $("hosted").hidden = !S.session;
  $("sess").textContent = S.session ? S.session.slice(-8) : "";
  // say honestly where the recorded run ran: hosted session, or a local Claude Agent SDK run
  $("footHost").textContent = S.session || !S.logs.length ? "hosted on Claude Managed Agents" : "(this recording: a local Claude Agent SDK run)";
}

/* ------------------------------------------------------------------ live agent workflow (D3) */
const FX = {crawl: 70, baseline: 205, audit: 345, plan: 490, fix: 650, reaudit: 815, report: 960, pr: 1105};
const FW = 1180, FH = 300, SY = 42, NY = 118, TY = 232, NW = 120, NH = 50;
const NODES = [
  {id: "lead", name: "Lead", x: FX.crawl + 6, y: NY},
  {id: "auditors", name: "Page auditors", x: FX.audit, y: NY},
  {id: "developer", name: "Developer", x: FX.fix, y: NY},
  {id: "tester", name: "Tester", x: FX.fix, y: TY},
  {id: "writer", name: "Writer", x: FX.report, y: NY},
  {id: "grader", name: "Independent grader", x: FX.pr, y: TY, w: 140},
  {id: "pr", name: "Pull request", x: FX.pr, y: NY},
];
const nodeById = Object.fromEntries(NODES.map((n) => [n.id, n]));
const R = (n) => n.x + (n.w || NW) / 2, L = (n) => n.x - (n.w || NW) / 2, T = (n) => n.y - NH / 2, B = (n) => n.y + NH / 2;
const EDGES = {
  "lead-aud": `M${R(nodeById.lead)},${NY} L${L(nodeById.auditors)},${NY}`,
  "aud-dev": `M${R(nodeById.auditors)},${NY} L${L(nodeById.developer)},${NY}`,
  "dev-test": `M${FX.fix + 22},${B(nodeById.developer)} C${FX.fix + 40},${NY + 55} ${FX.fix + 40},${TY - 55} ${FX.fix + 22},${T(nodeById.tester)}`,
  "test-dev": `M${FX.fix - 22},${T(nodeById.tester)} C${FX.fix - 40},${TY - 55} ${FX.fix - 40},${NY + 55} ${FX.fix - 22},${B(nodeById.developer)}`,
  "dev-writer": `M${R(nodeById.developer)},${NY} L${L(nodeById.writer)},${NY}`,
  "writer-pr": `M${R(nodeById.writer)},${NY} L${L(nodeById.pr)},${NY}`,
  "writer-grader": `M${FX.report + 20},${B(nodeById.writer)} C${FX.report + 30},${TY} ${FX.report + 50},${TY} ${L(nodeById.grader)},${TY}`,
  "grader-pr": `M${FX.pr},${T(nodeById.grader)} L${FX.pr},${B(nodeById.pr)}`,
};
let flowBuilt = false;

function buildFlow() {
  const svg = d3.select("#flow").attr("viewBox", `0 0 ${FW} ${FH}`);
  const defs = svg.append("defs");
  defs.append("marker").attr("id", "arrow").attr("viewBox", "0 0 10 10").attr("refX", 9).attr("refY", 5)
    .attr("markerWidth", 7).attr("markerHeight", 7).attr("orient", "auto-start-reverse")
    .append("path").attr("d", "M0,0 L10,5 L0,10 z").attr("fill", "currentColor").attr("class", "arrowhead");
  // tactile guidance strip: ribbed base + yellow progress
  const x0 = FX.crawl, x1 = FX.pr;
  svg.append("line").attr("class", "strip-base").attr("x1", x0).attr("x2", x1).attr("y1", SY).attr("y2", SY)
    .attr("stroke-width", 12).attr("stroke-dasharray", "3 3");
  svg.append("line").attr("id", "stripFill").attr("class", "strip-fill").attr("x1", x0).attr("x2", x0).attr("y1", SY).attr("y2", SY)
    .attr("stroke-width", 12).attr("stroke-dasharray", "3 3");
  const ph = svg.append("g").attr("id", "phases");
  PHASES.forEach(([k, n], i) => {
    const g = ph.append("g").attr("class", "phase").attr("data-k", k).attr("transform", `translate(${FX[k]},${SY})`);
    g.append("circle").attr("class", "stop").attr("r", 10);
    g.append("text").attr("class", "stop-mark").attr("text-anchor", "middle").attr("dy", "0.35em").text(i + 1);
    g.append("text").attr("class", "phase-label").attr("text-anchor", "middle").attr("y", -18).text(n);
  });
  const eg = svg.append("g").attr("id", "edges");
  Object.entries(EDGES).forEach(([id, d]) => eg.append("path").attr("id", "e-" + id).attr("class", "edge" + (id === "test-dev" ? " reject" : "")).attr("d", d).attr("marker-end", "url(#arrow)"));
  // stage notes (no agent): baseline, plan, re-audit
  const notes = svg.append("g").attr("class", "notes");
  [["baseline", "nBase"], ["plan", "nPlan"], ["reaudit", "nRe"]].forEach(([k, id]) =>
    notes.append("text").attr("id", id).attr("class", "count").attr("x", FX[k]).attr("y", NY - 4).attr("text-anchor", "middle"));
  const ng = svg.append("g").attr("id", "nodes");
  NODES.forEach((n) => {
    const w = n.w || NW, g = ng.append("g").attr("class", "node").attr("id", "n-" + n.id).attr("transform", `translate(${n.x - w / 2},${n.y - NH / 2})`);
    g.append("rect").attr("width", w).attr("height", NH).attr("rx", 9);
    g.append("text").attr("class", "name").attr("x", 12).attr("y", 20).text(n.name);
    g.append("text").attr("class", "state").attr("x", 12).attr("y", 38).text("waiting");
  });
  svg.append("g").attr("id", "subs");
  // loop counters around the developer ⇄ tester loop
  const c = svg.append("g").attr("class", "counters");
  c.append("text").attr("id", "cFix").attr("class", "count").attr("x", FX.fix + 46).attr("y", (NY + TY) / 2 + 4);
  c.append("text").attr("id", "cRej").attr("class", "count reject").attr("x", FX.fix - 46).attr("y", (NY + TY) / 2 + 4).attr("text-anchor", "end");
  c.append("text").attr("id", "cCommit").attr("class", "count ok").attr("x", FX.fix).attr("y", B(nodeById.tester) + 20).attr("text-anchor", "middle");
  c.append("text").attr("id", "cMore").attr("class", "count").attr("x", FX.fix).attr("y", B(nodeById.tester) + 38).attr("text-anchor", "middle");
  svg.append("g").attr("id", "pulses");
  flowBuilt = true;
}

function countText(sel, n, label, plural) {
  const t = d3.select(sel); t.selectAll("*").remove();
  t.append("tspan").attr("class", "v").text(n);
  t.append("tspan").text(" " + (n === 1 ? label : plural || label + "s"));
}

function nodeState(id) {
  if (id === "grader") {
    const o = S.outcomes[S.outcomes.length - 1];
    if (!o) return ["idle", "waiting"];
    return o.result === "satisfied" ? ["done", "✓ satisfied"] : o.result === "needs_revision" ? ["working", `revision asked (iteration ${o.iteration})`] : ["idle", o.result];
  }
  if (id === "pr") return S.prSent ? ["done", "✓ sent"] : S.pr ? ["done", `✓ ${S.pr.commits} commits ready`] : ["idle", "waiting"];
  let st = S.agents[id] || "idle";
  if (S.finished && st === "working") st = "done";
  if (id === "auditors" && S.subagents.length) {
    const done = S.subagents.filter((v) => v === "done").length;
    return [st, st === "done" || done === S.subagents.length ? `✓ ${S.subagents.length} pages audited` : `● ${done} of ${S.subagents.length} threads done`];
  }
  return [st, st === "working" ? "● working" : st === "done" ? "✓ done" : "waiting"];
}

function renderFlow() {
  if (!flowBuilt) buildFlow();
  const cur = PHASES.findIndex(([k]) => k === S.phase);
  const fillTo = S.finished ? FX.pr : cur >= 0 ? FX[PHASES[cur][0]] : FX.crawl;
  d3.select("#stripFill").attr("x2", fillTo);
  d3.selectAll("#phases .phase").each(function (_, i) {
    const done = S.finished || i < cur, now = !S.finished && i === cur, g = d3.select(this);
    g.select(".stop").attr("class", "stop" + (done ? " done" : now ? " now" : ""));
    g.select(".stop-mark").text(done ? "✓" : i + 1).style("fill", done ? null : "var(--ink)");
    g.select(".phase-label").attr("class", "phase-label" + (now ? " now" : ""));
  });
  NODES.forEach((n) => {
    const [st, txt] = nodeState(n.id), g = d3.select("#n-" + n.id);
    g.attr("class", "node " + st); g.select(".state").text(clip(txt, n.w ? 22 : 18));
  });
  // auditor threads as dots under the auditors node
  const subs = S.subagents.length ? S.subagents : [];
  const sx = (i) => FX.audit + (i - (subs.length - 1) / 2) * 22;
  const dots = d3.select("#subs").selectAll("circle").data(subs);
  dots.join("circle").attr("class", (v) => "sub " + v).attr("r", 7).attr("cx", (_, i) => sx(i)).attr("cy", B(nodeById.auditors) + 22);
  const lbl = d3.select("#subs").selectAll("text").data(subs.length ? [subs.length] : []);
  lbl.join("text").attr("class", "count").attr("x", FX.audit).attr("y", B(nodeById.auditors) + 50).attr("text-anchor", "middle").text((n) => `${n} parallel threads`);
  // edges become "hot" once traversed
  d3.select("#e-lead-aud").classed("hot", !!S.subagents.length || S.order.length > 0);
  d3.select("#e-aud-dev").classed("hot", S.counts.batches > 0);
  d3.select("#e-dev-test").classed("hot", S.counts.fixes > 0);
  d3.select("#e-test-dev").classed("hot", S.counts.rejected > 0);
  d3.select("#e-dev-writer").classed("hot", !!S.docs["pr-body.md"] || (S.agents.writer || "idle") !== "idle");
  d3.select("#e-writer-grader").classed("hot", S.outcomes.length > 0);
  d3.select("#e-grader-pr").classed("hot", S.outcomes.some((o) => o.result === "satisfied"));
  d3.select("#e-writer-pr").classed("hot", !!S.pr);
  countText("#cFix", S.counts.fixes, "fix handed over", "fixes handed over");
  countText("#cRej", S.counts.rejected, "rejected", "rejected");
  countText("#cCommit", S.commits.length, "commit");
  const more = [S.counts.rollbacks ? `${S.counts.rollbacks} rollback${S.counts.rollbacks > 1 ? "s" : ""}` : "", S.counts.human ? `${S.counts.human} to a human` : ""].filter(Boolean).join(", ");
  d3.select("#cMore").text(more);
  const bm = S.baselineMetrics, rm = S.reauditMetrics;
  d3.select("#nBase").text(bm ? `${bm.axe_violations} violations` : "");
  d3.select("#nPlan").text(S.counts.batches ? `${new Set(Object.values(S.issues).map((i) => i.wcag)).size} batches` : "");
  d3.select("#nRe").text(rm ? `${rm.axe_violations} violations` : "");
  // text alternatives
  const phaseTxt = cur >= 0 ? `Phase ${cur + 1} of 8, ${PHASES[cur][1]}${S.finished ? ", run finished" : ""}.` : "No run yet.";
  $("flowDesc").textContent = `Agent workflow. ${phaseTxt} ${S.counts.fixes} fixes handed to the tester, ${S.counts.rejected} rejected and sent back to the developer, ${S.commits.length} commits, ${S.counts.rollbacks} rollbacks, ${S.counts.human} escalated to a human.`;
  $("agentList").innerHTML = [...TEAM, ["grader", "Independent grader"], ["pr", "Pull request"]].map(([k, n]) => `<li>${n}: ${esc(nodeState(k)[1])}</li>`).join("");
  $("flowNow").innerHTML = S.now ? `<b>${esc(S.now.a)}</b> ${esc(clip(S.now.text, 150))}` : "Run an audit to watch the agents work.";
}

/* event-driven pulses along the workflow edges */
function pulse(edge, cls, reverse) {
  if (REDUCED || !flowBuilt || document.hidden) return;
  const path = document.getElementById("e-" + edge); if (!path) return;
  const len = path.getTotalLength(), dur = Math.max(250, 900 / (speed || 1));
  d3.select("#pulses").append("circle").attr("class", "pulse " + (cls || "")).attr("r", 6)
    .transition().duration(dur).ease(d3.easeCubicInOut)
    .attrTween("transform", () => (k) => { const p = path.getPointAtLength((reverse ? 1 - k : k) * len); return `translate(${p.x},${p.y})`; })
    .remove();
}
function fx(ev) {
  const d = ev.data || {};
  if (ev.type === "issue.detected") pulse("lead-aud");
  else if (ev.type === "batch.started") pulse("aud-dev");
  else if (ev.type === "issue.status" && d.status === "fixed_pending") pulse("dev-test");
  else if (ev.type === "issue.status" && d.status === "rejected") pulse("test-dev", "reject");
  else if (ev.type === "commit.created") pulse("dev-test", "ok");
  else if (ev.type === "document.written") pulse("dev-writer");
  else if (ev.type === "outcome") { pulse("writer-grader"); if (d.result === "satisfied") setTimeout(() => pulse("grader-pr", "ok"), 400); }
  else if (ev.type === "pr.ready") pulse("writer-pr", "ok");
}

/* ------------------------------------------------------------------ overall progress */
const PHASE_SPAN = {crawl: [0, 5], baseline: [5, 10], audit: [10, 30], plan: [30, 33], fix: [33, 86], reaudit: [86, 91], report: [91, 97], pr: [97, 100]};
const PHASE_TXT = {crawl: "Mapping the store", baseline: "Measuring the starting point", audit: "Auditing every page in parallel",
                   plan: "Planning the fixes", fix: "Fixing and verifying, one WCAG rule at a time", reaudit: "Re-measuring the store",
                   report: "Writing the pull request and the accessibility statement", pr: "Preparing the pull request"};
function progressPct() {
  if (S.finished) return 100;
  const span = PHASE_SPAN[S.phase]; if (!span) return 0;
  let k = 0.5;
  if (S.phase === "audit" && S.subagents.length) k = S.subagents.filter((x) => x === "done").length / S.subagents.length;
  if (S.phase === "fix") { const its = issuesList(); k = its.length ? its.filter((i) => ["validated", "needs_human"].includes(i.status)).length / its.length : 0; }
  return Math.round(span[0] + (span[1] - span[0]) * Math.min(1, k));
}
function renderProgress() {
  const pct = progressPct();
  $("progFill").style.width = pct + "%";
  $("progBar").setAttribute("aria-valuenow", pct);
  $("progPct").textContent = pct + "%";
  $("progTxt").textContent = S.finished ? "Done: pull request ready for compliance sign-off" : PHASE_TXT[S.phase] || "Not started";
  $("progress").classList.toggle("on", running);
}

/* ------------------------------------------------------------------ store map: one tile per page, one dot per problem */
let tilesKey = "";
function renderTiles() {
  const auditing = S.phase === "audit" && S.agents.auditors !== "done" && !S.finished;
  const fixing = new Set(issuesList().filter((i) => ["fixing", "fixed_pending"].includes(i.status)).flatMap((i) => i.pages.map(pageKey)));
  const rows = S.pages.map((pk) => {
    const its = issuesList().filter((i) => i.pages.some((p) => pageKey(p) === pk));
    const scan = auditing && !S.scanned.has(pk) && (S.scanning.has(pk) || S.subagents.includes("working"));
    return {pk, its, scan, fix: fixing.has(pk)};
  });
  const key = JSON.stringify(rows.map((r) => [r.pk, r.scan, r.fix, r.its.map((i) => i.id + i.status)]));
  if (key === tilesKey) return; tilesKey = key;
  if (!rows.length) { $("tiles").innerHTML = `<li class="tile empty-tile">Pages appear here once the lead agent has mapped the store.</li>`; return; }
  const word = {detected: "open", rejected: "open", fixing: "being fixed", fixed_pending: "being fixed", validated: "fixed", needs_human: "need a decision"};
  $("tiles").innerHTML = rows.map(({pk, its, scan, fix}) => {
    const by = {}; its.forEach((i) => { const w = word[i.status] || "open"; by[w] = (by[w] || 0) + 1; });
    const sum = its.length ? `${its.length} problem${its.length > 1 ? "s" : ""}: ` + Object.entries(by).map(([w, n]) => `${n} ${w}`).join(", ") : scan ? "being audited" : "no problem recorded yet";
    const state = scan ? `<span class="tstate scan">Auditing…</span>` : fix ? `<span class="tstate fix">Fixing…</span>`
      : its.length && its.every((i) => ["validated", "needs_human"].includes(i.status)) ? `<span class="tstate done">✓ Done</span>` : "";
    return `<li class="tile${scan ? " scanning" : ""}${fix ? " fixing" : ""}"><div class="thead"><b>${esc(pageName(pk))}</b>${state}</div>
      <div class="dots" aria-hidden="true">${its.map((i) => `<i class="d ${esc(i.status)}${S.fresh.has(i.id) ? " pop" : ""}" title="${esc(i.id)} ${esc(i.title)}"></i>`).join("")}</div>
      <p class="tsum">${esc(sum)}</p></li>`;
  }).join("");
}

/* ------------------------------------------------------------------ what was wrong: problems per plain-language type */
let catsKey = "";
function renderCats() {
  const its = issuesList();
  const key = its.map((i) => i.id + i.status).join(",");
  if (key === catsKey) return; catsKey = key;
  if (!its.length) { $("cats").innerHTML = `<li class="empty">The breakdown appears as the auditors record problems.</li>`; return; }
  const groups = new Map();
  for (const i of its) { const c = catOf(i.wcag); if (!groups.has(c.k)) groups.set(c.k, {c, its: []}); groups.get(c.k).its.push(i); }
  const list = [...groups.values()].sort((a, b) => b.its.length - a.its.length || CATS.indexOf(a.c) - CATS.indexOf(b.c));
  const max = Math.max(...list.map((g) => g.its.length));
  const seg = (g, cls, test) => { const n = g.its.filter(test).length; return n ? `<span class="seg ${cls}" style="width:${100 * n / max}%"></span>` : ""; };
  const isOpen = (i) => !["validated", "needs_human", "fixing", "fixed_pending"].includes(i.status);
  $("cats").innerHTML = list.map((g) => {
    const n = g.its.length, f = g.its.filter((i) => i.status === "validated").length, h = g.its.filter((i) => i.status === "needs_human").length;
    const w = g.its.filter((i) => ["fixing", "fixed_pending"].includes(i.status)).length, o = n - f - h - w;
    const parts = [f && `${f} fixed`, w && `${w} being fixed`, h && `${h} need${h > 1 ? "" : "s"} a decision`, o && `${o} open`].filter(Boolean).join(", ");
    const blockers = g.its.filter((i) => i.severity === "critical").length;
    return `<li class="cat"><p class="cat-txt"><span class="cat-n">${n}</span><b>${esc(g.c.n)}</b>${blockers ? `<span class="cat-crit">${blockers} block${blockers > 1 ? "" : "s"} a purchase</span>` : ""}</p>
      <div class="cat-bar" role="img" aria-label="${esc(g.c.n)}: ${n} problem${n > 1 ? "s" : ""}, ${esc(parts)}">${seg(g, "ok", (i) => i.status === "validated")}${seg(g, "info", (i) => ["fixing", "fixed_pending"].includes(i.status))}${seg(g, "warn", (i) => i.status === "needs_human")}${seg(g, "bad", isOpen)}</div>
      <p class="cat-parts"><span class="cat-state">${esc(parts)}</span> · ${esc(g.c.d)}</p></li>`;
  }).join("");
}

/* ------------------------------------------------------------------ score: gauge, timeline (D3) */
let chartKey = "";
function renderScore() {
  const sc = S.score ? S.score.value : null, base = S.score ? S.score.baseline : null;
  if (sc == null) $("gVal").textContent = "–";
  $("gaugeBox").setAttribute("aria-label", sc == null ? "Compliance score not measured yet" : `Compliance score ${sc} out of 100, baseline ${base}`);
  const its = issuesList();
  const nh = its.filter((i) => i.status === "needs_human").length;
  const open = its.filter((i) => !["validated","needs_human"].includes(i.status)).length;
  const eaaKey = S.score && S.score.eaa ? S.score.eaa : open > 0 ? "non_compliant" : nh ? "partially_compliant" : "compliant_automated";
  let eaa;
  if (sc == null) eaa = `<span class="pill p-mute">${S.phase ? "Audit in progress" : "Not audited"}</span>`;
  else if (eaaKey === "non_compliant") eaa = `<span class="pill p-bad">${EAA[eaaKey]}</span><span>baseline ${base}</span>`;
  else if (eaaKey === "partially_compliant") eaa = `<span class="pill p-warn">${EAA[eaaKey]}</span><span>${nh} item${nh > 1 ? "s" : ""} need${nh > 1 ? "" : "s"} review, baseline ${base}</span>`;
  else eaa = `<span class="pill p-ok">${EAA[eaaKey] || eaaKey}</span><span>baseline ${base}</span>`;
  $("eaa").innerHTML = eaa;
  const fixedN = its.filter((i) => i.status === "validated").length, hiddenN = its.filter((i) => i.source !== "axe").length;
  countTo("kFound", its.length ? its.length : null);
  countTo("kHidden", its.length ? hiddenN : null);
  countTo("kFixed", its.length ? fixedN : null);
  countTo("kHuman", its.length ? nh : null);
  $("nFind").textContent = its.length;
  $("verdict").innerHTML = verdictText(its, sc, base, fixedN, hiddenN, nh, open);
  const key = [S.scoreHist.length, S.rejects.length, $("timeline").clientWidth, sc].join("|");
  if (key === chartKey) return;
  chartKey = key;
  drawGauge(sc, base); drawTimeline();
}

/* one plain-language paragraph for a non-technical reader */
function verdictText(its, sc, base, fixedN, hiddenN, nh, open) {
  if (!its.length) return S.phase ? "The agents are mapping and auditing the store. Problems will appear as they are found."
    : "No audit yet. Try the demo store to see the agent team at work.";
  const types = new Set(its.map((i) => catOf(i.wcag).k)).size;
  let t = `The audit found <b>${its.length} accessibility problems</b> of ${types} different types`;
  t += hiddenN ? `, and <b>${hiddenN}</b> of them would have been missed by an automated scanner. ` : ". ";
  if (sc == null) return t + "The audit is still running.";
  if (!fixedN && !nh) return t + `Starting score: ${base} out of 100. The agents are about to fix them.`;
  t += `<b>${fixedN}</b> ${fixedN === 1 ? "is" : "are"} now fixed in the code and checked by an independent tester`;
  t += open ? `, ${open} still in progress. ` : ". ";
  if (nh) t += `<b>${nh}</b> need${nh === 1 ? "s" : ""} a human decision (see “Needs review”). `;
  t += `Score: ${base} → <b>${sc}</b> out of 100.`;
  return t;
}

/* KPI numbers count up/down to their new value */
function countTo(id, v) {
  const el = $(id), from = parseInt(el.dataset.v ?? "", 10);
  if (v == null) { el.textContent = "–"; el.dataset.v = ""; return; }
  if (from === v) return;
  el.dataset.v = v;
  if (REDUCED || isNaN(from) || !running) { el.textContent = v; return; }
  const t0 = performance.now(), dur = 500;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / dur), x = Math.round(from + (v - from) * (1 - Math.pow(1 - k, 3)));
    if (el.dataset.v == v) el.textContent = x;
    if (k < 1 && el.dataset.v == v) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
  el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump");
}

function drawGauge(v, base) {
  const w = 220, h = 124, r = 100, cx = w / 2, cy = 112;
  const svg = d3.select("#gauge").selectAll("svg").data([0]).join("svg").attr("viewBox", `0 0 ${w} ${h}`);
  const arc = d3.arc().innerRadius(r - 16).outerRadius(r).cornerRadius(4);
  const a = (x) => -Math.PI / 2 + Math.PI * x / 100;
  svg.selectAll("path.g-track").data([0]).join("path").attr("class", "g-track").attr("transform", `translate(${cx},${cy})`).attr("d", arc({startAngle: a(0), endAngle: a(100)}));
  const fill = svg.selectAll("path.g-fill").data(v == null ? [] : [v]).join("path").attr("transform", `translate(${cx},${cy})`)
    .attr("class", (d) => "g-fill " + (d >= 85 ? "ok" : d >= 60 ? "warn" : "bad"));
  const prev = drawGauge.prev ?? v;
  drawGauge.prev = v;
  if (v != null && running && !REDUCED && prev != null && prev !== v) {
    fill.transition().duration(700).ease(d3.easeCubicOut)
      .attrTween("d", () => { const i = d3.interpolate(prev, v); return (k) => arc({startAngle: a(0), endAngle: a(Math.max(i(k), 1))}); });
    const num = $("gVal"); d3.select(num).transition().duration(700).tween("text", () => { const i = d3.interpolateRound(prev, v); return (k) => { num.textContent = i(k); }; });
  } else {
    fill.attr("d", (d) => arc({startAngle: a(0), endAngle: a(Math.max(d, 1))}));
    if (v != null) $("gVal").textContent = v;
  }
  svg.selectAll("line.g-base").data(base == null ? [] : [base]).join("line").attr("class", "g-base")
    .attr("x1", (d) => cx + (r - 22) * Math.sin(a(d))).attr("y1", (d) => cy - (r - 22) * Math.cos(a(d)))
    .attr("x2", (d) => cx + (r + 6) * Math.sin(a(d))).attr("y2", (d) => cy - (r + 6) * Math.cos(a(d)));
}

function drawTimeline() {
  const el = $("timeline"), w = Math.max(240, el.clientWidth || 320), h = 150, m = {t: 10, r: 46, b: 22, l: 30};
  const data = S.scoreHist, maxT = Math.max(1, S.t, ...(data.map((d) => d.t)));
  const x = d3.scaleLinear().domain([0, maxT]).range([m.l, w - m.r]), y = d3.scaleLinear().domain([0, 100]).range([h - m.b, m.t]);
  const svg = d3.select(el).selectAll("svg").data([0]).join("svg").attr("viewBox", `0 0 ${w} ${h}`).attr("aria-hidden", "true");
  svg.selectAll("*").remove();
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${h - m.b})`).call(d3.axisBottom(x).ticks(4).tickSize(0).tickPadding(6).tickFormat((t) => mmss(t)));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).tickValues([0, 50, 100]).tickSize(0).tickPadding(6)).select(".domain").remove();
  svg.append("line").attr("class", "target-line").attr("x1", m.l).attr("x2", w - m.r).attr("y1", y(85)).attr("y2", y(85));
  svg.append("text").attr("class", "target-label").attr("x", w - m.r + 4).attr("y", y(85) + 4).text("target 85");
  if (data.length) {
    const pts = [...data, {t: maxT, v: data[data.length - 1].v}];
    svg.append("path").attr("class", "score-area").attr("d", d3.area().curve(d3.curveStepAfter).x((d) => x(d.t)).y0(h - m.b).y1((d) => y(d.v))(pts));
    svg.append("path").attr("class", "score-line").attr("d", d3.line().curve(d3.curveStepAfter).x((d) => x(d.t)).y((d) => y(d.v))(pts));
    svg.append("text").attr("class", "base-label").attr("x", x(data[0].t) + 4).attr("y", y(data[0].v) + 14).text(`baseline ${data[0].v}`);
    svg.append("text").attr("class", "target-label").attr("x", w - m.r + 4).attr("y", y(data[data.length - 1].v) + 4).style("font-weight", 700).style("fill", "var(--ink)").text(data[data.length - 1].v);
  }
  svg.selectAll("path.reject-mark").data(S.rejects).join("path").attr("class", "reject-mark")
    .attr("d", d3.symbol(d3.symbolTriangle, 40)).attr("transform", (d) => `translate(${x(d.t)},${h - m.b - 6}) rotate(180)`);
  // hover: crosshair + tooltip on the nearest score change
  const hl = svg.append("line").attr("class", "hover-line").attr("y1", m.t).attr("y2", h - m.b).style("display", "none");
  const hd = svg.append("circle").attr("class", "hover-dot").attr("r", 4).style("display", "none");
  const tip = d3.select(el).selectAll("div.tip").data([0]).join("div").attr("class", "tip").style("display", "none");
  const bis = d3.bisector((d) => d.t).right;
  svg.append("rect").attr("class", "hit").attr("x", m.l).attr("y", m.t).attr("width", w - m.l - m.r).attr("height", h - m.t - m.b)
    .on("pointermove", (e) => {
      if (!data.length) return;
      const [px] = d3.pointer(e), t = x.invert(px), d = data[Math.max(0, bis(data, t) - 1)];
      const rj = S.rejects.filter((r) => Math.abs(x(r.t) - px) < 6).map((r) => r.id);
      hl.style("display", null).attr("x1", px).attr("x2", px); hd.style("display", null).attr("cx", px).attr("cy", y(d.v));
      const sx = el.clientWidth / w;
      tip.style("display", null).style("left", `${px * sx}px`).style("top", `${y(d.v) * sx}px`)
        .text(`${mmss(t)}  score ${d.v}${rj.length ? `, ${rj.join(", ")} rejected` : ""}`);
    })
    .on("pointerleave", () => { hl.style("display", "none"); hd.style("display", "none"); tip.style("display", "none"); });
  $("timelineTable").querySelector("tbody").innerHTML = data.map((d) => `<tr><td>${mmss(d.t)}</td><td>${d.v}</td></tr>`).join("");
}

/* ------------------------------------------------------------------ proof: grader + eval */
let proofKey = "";
function renderProof() {
  const key = S.outcomes.length + "|" + (S.evalRes ? 1 : 0) + "|" + $("evalBody").clientWidth;
  if (key === proofKey) return; proofKey = key;
  const o = S.outcomes[S.outcomes.length - 1];
  if (!o) $("graderBody").innerHTML = `<p class="muted">The outcome rubric is graded once the agents finish their work.</p>`;
  else {
    const [lab, cls] = OUTCOME[o.result] || [o.result, "p-mute"];
    $("graderBody").innerHTML = `<p class="verdict"><span class="pill ${cls}">${esc(lab)}</span><span class="muted">iteration ${esc(o.iteration)} of the rubric</span></p>
      <details><summary>Why</summary><ol>${S.outcomes.map((x) => `<li><b>${esc((OUTCOME[x.result] || [x.result])[0])}.</b> ${esc(x.explanation)}</li>`).join("")}</ol></details>`;
  }
  const ev = S.evalRes;
  if (!ev) { $("evalBody").innerHTML = `<p class="muted">Recall, precision and fix rate are measured against the planted defects after the run.</p>`; return; }
  const rows = Object.entries(ev.metrics || {}).map(([k, v]) => {
    const th = (ev.thresholds || {})[k], ok = !th || (th.op === "=" ? v === th.value : th.op === "<=" ? v <= th.value : v >= th.value);
    return `<tr><td>${esc(METRIC_NAMES[k] || k)}</td><td class="num">${esc(v)}</td><td class="num">${th ? `${th.op === ">=" ? "≥" : th.op === "<=" ? "≤" : "="} ${esc(th.value)}` : "–"}</td><td><span class="pill ${ok ? "p-ok" : "p-bad"}">${ok ? "Pass" : "Fail"}</span></td></tr>`;
  }).join("");
  $("evalBody").innerHTML = `<p class="evalhead"><span class="pill ${ev.passed ? "p-ok" : "p-bad"}">${ev.passed ? "Eval passed" : "Eval failed"}</span></p>
    <div class="tablewrap" tabindex="0" role="region" aria-label="Eval metrics"><table class="evaltable"><thead><tr><th scope="col">Metric</th><th scope="col" class="num">Value</th><th scope="col" class="num">Threshold</th><th scope="col">Result</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="history" id="history"></div>`;
  drawHistory(ev.history || []);
}

function drawHistory(hist) {
  if (hist.length < 2) return;
  const el = $("history"), w = Math.max(240, el.clientWidth || 320), h = 110, m = {t: 12, r: 170, b: 20, l: 28};
  const x = d3.scalePoint().domain(hist.map((d) => d.version)).range([m.l, w - m.r]), y = d3.scaleLinear().domain([0, 1]).range([h - m.b, m.t]);
  const series = [["recall_agent_only", "agent-only recall", ""], ["verified_fix_rate", "verified fix rate", "alt"]];
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${w} ${h}`).attr("role", "img")
    .attr("aria-label", "Hill climb by agent version: " + hist.map((d) => `${d.version} agent-only recall ${d.recall_agent_only}, verified fix rate ${d.verified_fix_rate}`).join("; "));
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${h - m.b})`).call(d3.axisBottom(x).tickSize(0).tickPadding(6));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).tickValues([0, .5, 1]).tickSize(0).tickPadding(4)).select(".domain").remove();
  const last = hist[hist.length - 1];
  const ly = series.map(([k]) => y(last[k]) + 4).sort((a, b) => a - b);
  if (ly[1] - ly[0] < 15) ly[1] = ly[0] + 15; // keep the two direct labels apart
  const order = [...series].sort((a, b) => y(last[a[0]]) - y(last[b[0]]));
  order.forEach(([k, label, cls], j) => {
    svg.append("path").attr("class", "h-line " + cls).attr("d", d3.line().x((d) => x(d.version)).y((d) => y(d[k]))(hist));
    svg.selectAll(null).data(hist).join("circle").attr("class", "h-dot").attr("r", 3.5).attr("cx", (d) => x(d.version)).attr("cy", (d) => y(d[k]));
    svg.append("text").attr("class", "h-label").attr("x", x(last.version) + 12).attr("y", ly[j]).text(`${cls ? "- - " : "—— "}${label} ${last[k]}`);
  });
  svg.append("text").attr("class", "target-label").attr("x", m.l).attr("y", 8).text("Hill climb by agent version");
}

/* ------------------------------------------------------------------ log, findings, PR, statement */
function renderLog() {
  const lg = $("log"), stick = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 40;
  if (S.logs.length > logRendered) {
    lg.insertAdjacentHTML("beforeend", S.logs.slice(logRendered).map((l) =>
      `<div class="ln k-${esc(l.kind)}"><span class="t">${mmss(l.t)}</span><span><span class="a">[${esc(l.a)}]</span> <span class="x">${esc(l.text)}</span></span></div>`).join(""));
    logRendered = S.logs.length;
    if (stick) lg.scrollTop = lg.scrollHeight;
  }
}

function issuesList() { return S.order.map((id) => S.issues[id]); }
function pagesLabel(i) {
  const all = new Set(issuesList().flatMap((x) => x.pages));
  return all.size > 1 && i.pages.length >= all.size ? "All pages" : i.pages.join(", ");
}
function diffHtml(t) {
  return String(t).split("\n").map((l) => l.startsWith("+") ? `<span class="add">${esc(l)}</span>` : l.startsWith("-") ? `<span class="del">${esc(l)}</span>` : esc(l)).join("\n");
}

function renderRows() {
  let its = issuesList();
  if (filter === "open") its = its.filter((i) => !["validated","needs_human"].includes(i.status));
  else if (filter === "agent") its = its.filter((i) => i.source !== "axe");
  else if (filter !== "all") its = its.filter((i) => i.status === filter);
  if (!its.length) {
    $("rows").innerHTML = `<tr><td colspan="6" class="empty">${S.phase ? "No findings in this view yet." : "Run an audit to see findings. Agents map the site, audit each page and record every WCAG issue here."}</td></tr>`;
    return;
  }
  $("rows").innerHTML = its.map((i) => {
    const [sl, scl] = STL[i.status] || [i.status, "p-mute"], ex = expanded.has(i.id), att = i.attempts || 0, sev = i.severity || "minor";
    let row = `<tr class="row${S.fresh.has(i.id) ? " fresh" : ""}" data-id="${esc(i.id)}">
      <td><button type="button" class="rowbtn" data-id="${esc(i.id)}" aria-expanded="${ex}" aria-controls="d-${esc(i.id)}">${esc(i.id)}<span class="vh"> details</span></button></td>
      <td><div class="crit"><span class="num">${esc(i.wcag)}</span><span class="lvl">${esc(i.level)}</span></div><div class="src">${esc(i.criterion_name)}</div></td>
      <td>${esc(i.title)}<div class="src">${esc(catOf(i.wcag).n)} · ${esc(pagesLabel(i))}</div></td>
      <td><span class="sev ${esc(sev)}" aria-hidden="true"></span>${esc(sev[0].toUpperCase() + sev.slice(1))}</td>
      <td class="src ${i.source !== "axe" ? "agent" : ""}">${i.source === "axe" ? "Scanner (axe)" : i.source === "keyboard" ? "Keyboard test" : "Agent review"}</td>
      <td><span class="pill ${scl}">${sl}</span>${att > 1 ? `<div class="src">attempt ${att}</div>` : ""}</td></tr>`;
    if (ex) {
      const hist = (i.history || []).map((h) => `<li><time>${mmss(h.t)}</time><span class="who">${esc(h.by)}</span><span>${esc(h.note)}</span></li>`).join("");
      const fix = i.fix_diff ? `<pre>${diffHtml(i.fix_diff)}</pre><p class="src" style="margin-top:4px">${i.files && i.files.length ? "Files: " + i.files.map(esc).join(", ") : "No file changed"}</p>`
        : i.status === "needs_human" ? `<p>No code change possible in this repository.</p>` : `<p class="muted">Not fixed yet.</p>`;
      const human = i.human_action ? `<h3>Human action</h3><p>${esc(i.human_action)}</p>` : "";
      row += `<tr class="detail" id="d-${esc(i.id)}"><td colspan="6"><div class="dgrid">
        <div><h3>Specification</h3><p>WCAG 2.1 ${esc(i.wcag)} ${esc(i.criterion_name)} (Level ${esc(i.level)}), EN 301 549 clause ${esc(i.en301549 || "9." + i.wcag)}, ${PRIN[i.principle] || ""}</p>
          <h3>User impact</h3><p>${esc(i.impact)}</p><h3>Evidence</h3><pre>${esc(i.evidence)}</pre></div>
        <div><h3>Fix applied in source</h3>${fix}${human}
          <h3 style="margin-top:12px">Verification trail</h3><ul class="hist">${hist}</ul></div></div></td></tr>`;
    }
    return row;
  }).join("");
}

/* tiny markdown renderer for writer documents (headings, lists, bold, code, [TO COMPLETE] placeholders) */
function md(src, headingBase) {
  const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\](?!\()/g, (m, x) => `<span class="todo">[${x}]</span>`);
  let out = "", list = false;
  for (const line of String(src).split("\n")) {
    const li = line.match(/^\s*[-*]\s+(.*)/), h = line.match(/^(#{1,4})\s+(.*)/);
    if (li) { if (!list) { out += "<ul>"; list = true; } out += `<li>${inline(li[1])}</li>`; continue; }
    if (list) { out += "</ul>"; list = false; }
    if (h) { const n = Math.min(6, headingBase + h[1].length - 1); out += `<h${n}>${inline(h[2])}</h${n}>`; }
    else if (line.trim()) out += `<p>${inline(line)}</p>`;
  }
  return out + (list ? "</ul>" : "");
}

function renderPR() {
  const p = $("p-pr");
  if (!S.pr) {
    p.dataset.ready = "";
    p.innerHTML = `<div class="empty">The pull request is assembled once every fix has been verified by the tester agent.${S.commits.length ? `<br>${S.commits.length} commit${S.commits.length > 1 ? "s" : ""} so far.` : ""}</div>`;
    return;
  }
  if (p.dataset.ready === "1") return;
  p.dataset.ready = "1";
  const its = issuesList(), fixed = its.filter((i) => i.status === "validated"), nh = its.filter((i) => i.status === "needs_human");
  const sc = S.score || {};
  p.innerHTML = `<div class="prgrid">
   <div>
     <h2>a11y: EAA remediation, WCAG 2.1 AA</h2>
     <dl class="kv"><dt>Repository</dt><dd>${esc(S.pr.repo)}</dd>
       <dt>Branch</dt><dd>${esc(S.pr.branch)} → ${esc(S.pr.base)}</dd>
       <dt>Changes</dt><dd>${esc(S.pr.commits)} commits, ${(S.pr.files || []).length} files, ${fixed.length} issues fixed and verified</dd>
       <dt>Open items</dt><dd>${nh.length ? nh.map((i) => `${esc(i.id)} ${esc(i.title)}`).join("<br>") : "None"}</dd>
       <dt>Score</dt><dd>${esc(sc.baseline)} → ${esc(sc.value)}</dd></dl>
     <ul class="commits">${S.commits.map((c) => `<li><span class="h">${esc(String(c.sha).slice(0, 7))}</span><span>${esc(c.message)}</span></li>`).join("")}</ul>
     ${S.pr.body ? `<details class="body"><summary>Pull request description</summary><div class="md">${md(S.pr.body, 3)}</div></details>` : ""}
   </div>
   <form id="prForm" novalidate>
     <fieldset><legend>Reviewers</legend>
       <label class="opt"><input type="checkbox" id="rv1" checked> Frontend team</label>
       <label class="opt"><input type="checkbox" id="rv2" checked> Léa Martin, tech lead</label>
       <label class="opt"><input type="checkbox" id="rv3"> Tom Baker, QA</label></fieldset>
     <fieldset><legend>Notify</legend>
       <label class="opt"><input type="checkbox" id="nt1" checked> Slack #eng-frontend</label>
       <label class="opt"><input type="checkbox" id="nt2" checked> Create a Jira ticket in A11Y</label>
       <label class="opt"><input type="checkbox" id="nt3"> Email the compliance report to legal</label></fieldset>
     <label class="lbl" for="prMsg">Message to engineering</label>
     <textarea id="prMsg">Compliance has reviewed and approved these accessibility fixes. Each commit maps to one WCAG 2.1 AA criterion and was verified by an independent tester agent (diffs and verification trail in the description).${nh.length ? ` ${nh.length} item${nh.length > 1 ? "s need" : " needs"} a human decision (see open items).` : ""} Target merge before the next release.</textarea>
     <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center">
       <button class="btn primary" type="submit" id="sendPr">Send pull request</button>
       <span class="muted" style="font-size:13px">Sign-off is recorded in the audit trail.</span></div>
     <div id="sendOut"></div>
   </form></div>`;
  $("prForm").addEventListener("submit", (e) => { e.preventDefault(); sendPR(); });
}

async function sendPR() {
  const btn = $("sendPr"); btn.disabled = true;
  const repo = S.pr.repo, branch = S.pr.branch;
  const reviewers = [["rv1","Frontend team"],["rv2","Léa Martin"],["rv3","Tom Baker"]].filter(([id]) => $(id).checked).map(([, n]) => n);
  const notify = {slack: $("nt1").checked, jira: $("nt2").checked, email: $("nt3").checked};
  let result = {number: 218, url: "", simulated: true};
  if (mode === "live") {
    try {
      const r = await fetch("/api/pr", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({reviewers, notify, message: $("prMsg").value})});
      if (r.ok) result = await r.json();
    } catch (e) { /* fall back to the simulated send */ }
  }
  const steps = [`Push branch ${branch}`, `Open pull request on ${repo}`];
  if (reviewers.length) steps.push("Request reviews");
  if (notify.slack) steps.push("Post to Slack #eng-frontend");
  if (notify.jira) steps.push("Create Jira ticket A11Y-42");
  if (notify.email) steps.push("Email report to legal");
  const out = $("sendOut"); let k = 0;
  const draw = () => { out.innerHTML = `<ul class="steps">${steps.map((s, i) => `<li class="${i < k ? "ok" : i === k ? "run" : ""}">${esc(s)}</li>`).join("")}</ul>`; };
  draw();
  const iv = setInterval(() => {
    k++; draw();
    if (k >= steps.length) {
      clearInterval(iv);
      const ext = result.simulated ? "Demo workspace: no external system was contacted." : "Slack, Jira and email are simulated in this demo.";
      out.insertAdjacentHTML("beforeend", `<div class="sent" role="status"><b>Pull request #${esc(result.number)} opened</b>${result.url ? `<a href="${esc(result.url)}">${esc(result.url)}</a>` : `<span>${esc(repo)}, ${esc(branch)}</span>`}<p class="src" style="margin-top:4px">Engineering notified. ${ext}</p></div>`);
      btn.textContent = "Sent";
    }
  }, REDUCED ? 60 : 650);
}

function renderStmt() {
  const p = $("p-stmt"), doc = S.docs["accessibility-statement.md"];
  if (!doc) {
    p.dataset.ready = "";
    p.innerHTML = `<div class="empty">The writer agent drafts the accessibility statement required by the EAA once the re-audit is done.</div>`;
    return;
  }
  if (p.dataset.ready === "1") return;
  p.dataset.ready = "1";
  p.innerHTML = `<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px"><span class="pill p-warn">Draft, partially compliant</span><button class="btn small" id="copyStmt" type="button">Copy statement</button></div>
    <article class="statement" id="stmt">${md(doc.content, 2)}</article>`;
  $("copyStmt").addEventListener("click", () => copyText(doc.content, $("copyStmt")));
}

/* ------------------------------------------------------------------ wiring */
function updButtons() {
  $("runBtn").textContent = running ? "■ Stop" : "▶ Run audit";
  $("prBtn").disabled = !S.pr;
}
function copyText(txt, btn) {
  const done = () => { const o = btn.textContent; btn.textContent = "Copied"; setTimeout(() => (btn.textContent = o), 1400); };
  try { navigator.clipboard.writeText(txt).then(done, () => toast("Copy failed: select the text manually.")); }
  catch (e) { toast("Copy failed: select the text manually."); }
}
function selectTab(name, focus) {
  ["findings","pr","stmt"].forEach((n) => {
    const on = n === name, t = $("t-" + n);
    t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1; $("p-" + n).hidden = !on;
    if (on && focus) t.focus();
  });
}
function toggleRow(id, refocus) {
  expanded.has(id) ? expanded.delete(id) : expanded.add(id);
  renderRows();
  const r = document.querySelector(`.rowbtn[data-id="${CSS.escape(id)}"]`);
  if (r && refocus) r.focus({preventScroll: true});
}

function wire() {
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => selectTab(b.id.slice(2))));
  document.querySelector(".tabs").addEventListener("keydown", (e) => {
    const ts = [...document.querySelectorAll(".tab")], i = ts.indexOf(document.activeElement);
    if (i < 0) return;
    const n = {ArrowRight: i + 1, ArrowLeft: i - 1 + ts.length, Home: 0, End: ts.length - 1}[e.key];
    if (n == null) return;
    e.preventDefault(); selectTab(ts[n % ts.length].id.slice(2), true);
  });
  document.querySelectorAll(".fbtn").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.f; document.querySelectorAll(".fbtn").forEach((x) => x.setAttribute("aria-pressed", x === b)); renderRows();
  }));
  // the ID button is the keyboard control (Enter/Space natively); the whole row is a mouse target
  $("rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr.row"); if (!tr || e.target.closest("a, input, textarea")) return;
    toggleRow(tr.dataset.id, !!e.target.closest(".rowbtn"));
  });
  document.querySelectorAll("[data-speed]").forEach((b) => b.addEventListener("click", () => {
    speed = +b.dataset.speed; if (source instanceof ReplaySource) source.speed = speed;
    document.querySelectorAll("[data-speed]").forEach((x) => x.setAttribute("aria-pressed", x === b));
  }));
  $("runBtn").addEventListener("click", () => runAudit());
  $("prBtn").addEventListener("click", () => {
    selectTab("pr"); $("p-pr").scrollIntoView({behavior: REDUCED ? "auto" : "smooth", block: "start"});
    const s = $("sendPr"); if (s) s.focus({preventScroll: true});
  });
  $("copyLog").addEventListener("click", () => copyText(S.logs.map((l) => `${mmss(l.t)} [${l.a}] ${l.text}`).join("\n"), $("copyLog")));
  $("aboutBtn").addEventListener("click", () => $("about").showModal());
  $("themeBtn").addEventListener("click", () => setTheme(isDark() ? "light" : "dark", true));
  $("demoBtn").addEventListener("click", () => {
    $("domain").value = "";
    $("targetMsg").textContent = "Replaying a real recorded run of the agent team on the demo store, Maison Lumière.";
    if (running) stopRun();
    runAudit();
    $("flowH").scrollIntoView({behavior: REDUCED ? "auto" : "smooth", block: "start"});
  });
  $("targetForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw = $("domain").value.trim(), dom = raw.replace(/^https?:\/\//i, "").replace(/\/.*$/, "").toLowerCase();
    const msg = $("targetMsg");
    $("domain").removeAttribute("aria-invalid");
    if (!/^([a-z0-9-]+\.)+[a-z]{2,}$/.test(dom)) {
      $("domain").setAttribute("aria-invalid", "true");
      msg.textContent = "Enter a domain such as yourstore.eu, or try the demo store.";
      $("domain").focus(); return;
    }
    if (mode === "live") {
      msg.textContent = `Starting a read-only audit of ${dom}…`;
      return runAudit(dom);
    }
    // static hosting: never pretend an audit of their domain happened
    msg.innerHTML = `Auditing <b>${esc(dom)}</b> needs the Arma agent backend, which this hosted demo does not run: nothing was sent anywhere. ` +
      `<button type="button" class="linkbtn" id="demoInline">Watch the demo store instead</button>`;
    $("demoInline").addEventListener("click", () => $("demoBtn").click());
  });
  $("about").addEventListener("close", () => { if (location.hash === "#about") history.replaceState(null, "", location.pathname + location.search); });
  const openHash = () => { if (location.hash === "#about" && !$("about").open) $("about").showModal(); };
  addEventListener("hashchange", openHash); openHash();
  let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { chartKey = ""; proofKey = ""; render(); }, 150); });
}

/* light/dark: follows the system until the user picks one, then remembered */
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function setTheme(t, save) {
  document.documentElement.dataset.theme = t;
  if (save) try { localStorage.setItem("arma-theme", t); } catch (e) { /* private mode */ }
  const dark = t === "dark";
  $("themeBtn").setAttribute("aria-pressed", dark);
  $("themeIcon").textContent = dark ? "☀" : "☾";
  chartKey = ""; proofKey = ""; tilesKey = ""; schedule();
}

async function init() {
  const q = new URLSearchParams(location.search);
  let saved = null; try { saved = localStorage.getItem("arma-theme"); } catch (e) { /* private mode */ }
  if (saved === "light" || saved === "dark") setTheme(saved);
  else { $("themeBtn").setAttribute("aria-pressed", isDark()); $("themeIcon").textContent = isDark() ? "☀" : "☾"; }
  speed = [1, 2, 4].includes(+q.get("speed")) ? +q.get("speed") : 2;
  document.querySelectorAll("[data-speed]").forEach((b) => b.setAttribute("aria-pressed", +b.dataset.speed === speed));
  wire();
  if (q.get("mode") === "live") mode = "live";
  else if (!q.get("mode") && !location.hostname.endsWith("vercel.app")) { // static hosting has no backend
    try {
      const ctl = new AbortController(); setTimeout(() => ctl.abort(), 1200);
      const r = await fetch("/api/state", {cache: "no-store", signal: ctl.signal});
      mode = r.ok && (r.headers.get("content-type") || "").includes("json") ? "live" : "replay";
    } catch (e) { mode = "replay"; }
  }
  // the last recorded run, shown at rest so the page is never empty
  const candidates = q.get("run") ? [q.get("run")] : ["recordings/demo-run.jsonl", "recordings/fixture.jsonl"];
  for (const url of candidates) {
    try { recording = new ReplaySource(url); await recording.load(); break; } catch (e) { recording = null; }
  }
  if (recording) restAt(recording.events); else toast("No recorded run found.");
  render();
  if (q.get("autoplay") === "1") runAudit();
}
init();
