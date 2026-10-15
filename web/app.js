"use strict";
/* Arma dashboard. Rendering comes from reference/arma-dashboard-prototype.html; the engine is an
   event reducer (arma-spec.md §5): state = events.reduce(apply). No business logic beyond display. */

/* ------------------------------------------------------------------ constants */
const PRIN = {P: "Perceivable", O: "Operable", U: "Understandable", R: "Robust"};
const PHASES = [["crawl","Map site"],["baseline","Baseline"],["audit","Audit"],["plan","Plan"],["fix","Fix & verify"],["reaudit","Re-audit"],["report","Report"],["pr","Pull request"]];
const AGENTS = [["orchestrator","Orchestrator"],["cartographer","Cartographer"],["auditors","Auditors"],["developer","Developer"],["tester","Tester"],["writer","Writer"]];
const STL = {detected:["Detected","p-bad"], fixing:["Developer fixing","p-info"], fixed_pending:["Tester verifying","p-info"],
             rejected:["Rejected, retrying","p-warn"], validated:["Fixed and verified","p-ok"], needs_human:["Needs review","p-warn"]};
const EAA = {non_compliant:"EAA: non-compliant", partially_compliant:"EAA: partially compliant", compliant_automated:"EAA: compliant (automated scope)"};

/* log label → colour class / team member */
function agentClass(a) {
  if (!a) return "a-orch";
  if (a.startsWith("auditor")) return "a-aud";
  return {orchestrator:"a-orch", cartographer:"a-cart", "lead-auditor":"a-chief", developer:"a-dev", tester:"a-test", writer:"a-writer", system:"a-sys"}[a] || "a-orch";
}
function teamKey(a) {
  if (!a) return "orchestrator";
  if (a.startsWith("auditor")) return "auditors";
  if (a === "lead-auditor" || a === "system") return null;
  return a;
}

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const mmss = (t) => { const s = Math.max(0, Math.floor(t || 0)); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };

/* ------------------------------------------------------------------ state + reducer */
function initial() {
  return {t: 0, site: "maison-lumiere.fr", repo: "", branch: "", phase: null, agents: {}, act: {}, subagents: [],
          logs: [], issues: {}, order: [], score: null, scoreHist: [], commits: [], docs: {}, pr: null, prSent: null,
          baselineMetrics: null, reauditMetrics: null, finished: false, cost: 0, fresh: new Set()};
}

function apply(S, ev) {
  const d = ev.data || {};
  S.t = Math.max(S.t, ev.t || 0);
  switch (ev.type) {
    case "run.started": {
      const fresh = initial();
      Object.assign(S, fresh, {site: d.site || fresh.site, repo: d.repo || "", branch: d.branch || "", t: ev.t || 0});
      break;
    }
    case "phase.changed": S.phase = d.phase; break;
    case "agent.status":
      S.agents[d.agent] = d.status;
      if ("activity" in d) S.act[d.agent] = d.activity;
      break;
    case "subagents": S.subagents = d.states || []; break;
    case "log": {
      const a = ev.agent || "orchestrator";
      S.logs.push({t: ev.t, a, text: d.text, kind: d.kind || "msg"});
      const k = teamKey(a);
      if (k && d.kind !== "tool") S.act[k] = d.text;
      break;
    }
    case "baseline": S.baselineMetrics = d; break;
    case "issue.detected":
      if (!S.issues[d.id]) S.order.push(d.id);
      S.issues[d.id] = {pages: [], history: [], files: [], fix_diff: "", human_action: "", attempts: 0, ...d};
      S.fresh.add(d.id);
      break;
    case "issue.merged": {
      const i = S.issues[d.id];
      if (i && !i.pages.includes(d.page)) i.pages = [...i.pages, d.page];
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
      break;
    }
    case "score": S.score = d; S.scoreHist.push(d.value); break;
    case "commit.created": S.commits.push(d); break;
    case "reaudit": S.reauditMetrics = d; break;
    case "document.written": S.docs[d.name] = d; break;
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
  apply(S, ev); schedule();
}
function schedule() { if (dirty) return; dirty = true; requestAnimationFrame(() => { dirty = false; render(); }); }

function resetView() {
  S = initial(); logRendered = 0; $("log").innerHTML = ""; expanded.clear();
  $("p-pr").dataset.ready = ""; $("p-stmt").dataset.ready = ""; selectTab("findings");
}

function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 4500);
}

async function runAudit() {
  if (running) return stopRun();
  if (mode === "live") {
    try {
      const r = await fetch("/api/run", {method: "POST"});
      if (!r.ok && r.status !== 409) throw new Error(String(r.status));
      resetView(); running = true; updButtons();
      source = new LiveSource();
      source.start(onEvent, () => { running = false; schedule(); }, () => {
        running = false; toast("Live connection lost. Showing the recorded run instead."); mode = "replay"; runAudit();
      });
      return;
    } catch (e) { toast("Live backend unavailable. Replaying the recorded run."); mode = "replay"; }
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
  S = initial(); logRendered = 0; $("log").innerHTML = "";
  $("p-pr").dataset.ready = ""; $("p-stmt").dataset.ready = "";
  for (const ev of events) if (ev.type !== "pr.sent") apply(S, ev);
  S.fresh.clear();
}

/* ------------------------------------------------------------------ render */
function render() {
  const ae = document.activeElement, focusedRow = ae && ae.matches && ae.matches(".rowbtn") ? ae.dataset.id : null;
  renderRail(); renderHeader(); renderScore(); renderAgents(); renderLog(); renderRows(); renderPR(); renderStmt(); updButtons();
  S.fresh.clear();
  if (focusedRow) { const r = document.querySelector(`.rowbtn[data-id="${CSS.escape(focusedRow)}"]`); if (r) r.focus({preventScroll: true}); }
}

function renderHeader() {
  $("siteName").textContent = S.site || "maison-lumiere.fr";
  $("siteRef").textContent = S.branch ? `storefront · ${S.branch}` : "storefront · main";
  $("liveDot").className = "dot" + (running ? " live" : "");
  $("clock").textContent = running ? `Running · ${mmss(S.t)} elapsed` : (S.finished ? `Last run · ${mmss(S.t)} agent time` : "Idle");
}

function renderRail() {
  const cur = PHASES.findIndex(([k]) => k === S.phase);
  $("rail").innerHTML = PHASES.map(([k, n], i) => {
    const d = S.finished || i < cur, now = !S.finished && i === cur;
    return `<span class="ph ${d ? "done" : now ? "now" : ""}"${now ? ' aria-current="step"' : ""}><i aria-hidden="true">${d ? "✓" : i + 1}</i>${n}${d ? '<span class="vh"> (done)</span>' : now ? '<span class="vh"> (in progress)</span>' : ""}</span>`;
  }).join("");
}

function issuesList() { return S.order.map((id) => S.issues[id]); }

function renderScore() {
  const sc = S.score ? S.score.value : null, base = S.score ? S.score.baseline : null;
  $("gVal").textContent = sc == null ? "–" : sc;
  $("gaugeLbl").textContent = sc == null ? "Compliance score: not measured yet" : `Compliance score ${sc} out of 100, baseline ${base}`;
  $("gArc").setAttribute("stroke-dasharray", `${sc || 0} 100`);
  $("gArc").setAttribute("stroke", sc == null ? "var(--faint)" : sc >= 85 ? "var(--ok)" : sc >= 60 ? "var(--warn)" : "var(--bad)");
  if (base != null) {
    const a = Math.PI * (1 - base / 100), cx = 115, cy = 125, r1 = 82, r2 = 108;
    $("gBase").setAttribute("x1", cx + r1 * Math.cos(a)); $("gBase").setAttribute("y1", cy - r1 * Math.sin(a));
    $("gBase").setAttribute("x2", cx + r2 * Math.cos(a)); $("gBase").setAttribute("y2", cy - r2 * Math.sin(a));
  } else ["x1","y1","x2","y2"].forEach((k) => $("gBase").setAttribute(k, 0));

  const its = issuesList();
  const nh = its.filter((i) => i.status === "needs_human").length;
  const open = its.filter((i) => !["validated","needs_human"].includes(i.status)).length;
  const eaaKey = S.score && S.score.eaa ? S.score.eaa : open > 0 ? "non_compliant" : nh ? "partially_compliant" : "compliant_automated";
  let eaa;
  if (sc == null) eaa = `<span class="pill p-mute">${S.phase ? "Audit in progress" : "Not audited"}</span>`;
  else if (eaaKey === "non_compliant") eaa = `<span class="pill p-bad">${EAA[eaaKey]}</span><span class="muted" style="font-size:13px">baseline ${base}</span>`;
  else if (eaaKey === "partially_compliant") eaa = `<span class="pill p-warn">${EAA[eaaKey]}</span><span class="muted" style="font-size:13px">${nh} item${nh > 1 ? "s" : ""} need${nh > 1 ? "" : "s"} review · baseline ${base}</span>`;
  else eaa = `<span class="pill p-ok">${EAA[eaaKey] || eaaKey}</span><span class="muted" style="font-size:13px">baseline ${base}</span>`;
  $("eaa").innerHTML = eaa;

  $("pour").innerHTML = Object.entries(PRIN).map(([k, n]) => {
    const v = sc == null ? null : ((S.score.by_principle || {})[k] ?? 100);
    return `<div class="pour-row"><span>${n}</span><div class="track" role="img" aria-label="${n}: ${v == null ? "not measured" : v + "% resolved"}"><span style="width:${v || 0}%;background:${v == null ? "var(--line)" : v >= 85 ? "var(--ok)" : v >= 50 ? "var(--warn)" : "var(--bad)"}"></span></div><span class="mono" style="text-align:right">${v == null ? "–" : v + "%"}</span></div>`;
  }).join("");

  const h = S.scoreHist;
  if (h.length > 1) {
    const w = 300, H = 54, p = 4, xs = (i) => p + (w - 2 * p) * i / (h.length - 1), ys = (v) => H - p - (H - 2 * p) * v / 100;
    const d = h.map((v, i) => (i ? "L" : "M") + xs(i).toFixed(1) + " " + ys(v).toFixed(1)).join(" ");
    $("spark").innerHTML = `<line x1="0" x2="${w}" y1="${ys(85)}" y2="${ys(85)}" stroke="var(--line)" stroke-dasharray="3 3"/><path d="${d} L${xs(h.length - 1)} ${H} L${xs(0)} ${H}Z" fill="var(--faint)"/><path d="${d}" fill="none" stroke="var(--ink)" stroke-width="1.6" vector-effect="non-scaling-stroke"/><circle cx="${xs(h.length - 1)}" cy="${ys(h[h.length - 1])}" r="3" fill="var(--ink)"/>`;
    $("sparkLbl").textContent = `Score over the run: ${h[0]} → ${h[h.length - 1]} · dashed line = target 85`;
    $("spark").setAttribute("aria-label", `Score during the run, from ${h[0]} to ${h[h.length - 1]}; target 85`);
  } else { $("spark").innerHTML = ""; $("sparkLbl").textContent = "Score over the run"; }

  $("kFound").textContent = its.length || "–";
  $("kHidden").textContent = its.length ? its.filter((i) => i.source !== "axe").length : "–";
  $("kFixed").textContent = its.length ? its.filter((i) => i.status === "validated").length : "–";
  $("kHuman").textContent = its.length ? nh : "–";
  $("nFind").textContent = its.length;
}

function renderAgents() {
  $("agents").innerHTML = AGENTS.map(([k, n]) => {
    const st = S.agents[k] || "idle";
    const subs = k === "auditors" ? S.subagents : [];
    const sub = subs.length ? `<span class="subdots" aria-hidden="true">${subs.map((v) => `<i class="${v === "working" ? "on" : v === "done" ? "ok" : ""}"></i>`).join("")}</span>` : "";
    const subTxt = subs.length ? `, ${subs.filter((v) => v === "done").length} of ${subs.length} page auditors done` : "";
    const act = S.act[k] || (st === "idle" ? "idle" : "");
    return `<div class="ag ${st}"><span class="st" aria-hidden="true"></span><span class="nm">${n}${sub}</span><span class="act" title="${esc(act)}">${esc(act)}</span><span class="vh">${st}${subTxt}</span></div>`;
  }).join("");
}

function renderLog() {
  const lg = $("log"), stick = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 40;
  if (S.logs.length > logRendered) {
    lg.insertAdjacentHTML("beforeend", S.logs.slice(logRendered).map((l) =>
      `<div class="ln k-${esc(l.kind)}"><span class="t">${mmss(l.t)}</span><span><span class="a ${agentClass(l.a)}">[${esc(l.a)}]</span> <span class="x">${esc(l.text)}</span></span></div>`).join(""));
    logRendered = S.logs.length;
    if (stick) lg.scrollTop = lg.scrollHeight;
  }
}

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
    const [sl, scl] = STL[i.status] || [i.status, "p-mute"], ex = expanded.has(i.id), att = i.attempts || 0;
    const sev = i.severity || "minor";
    let row = `<tr class="row${S.fresh.has(i.id) ? " fresh" : ""}" data-id="${esc(i.id)}">
      <td class="mono"><button type="button" class="rowbtn" data-id="${esc(i.id)}" aria-expanded="${ex}" aria-controls="d-${esc(i.id)}">${esc(i.id)}<span class="vh"> details</span></button></td>
      <td><div class="crit"><span class="num">${esc(i.wcag)}</span><span class="lvl">${esc(i.level)}</span></div><div class="src">${esc(i.criterion_name)}</div></td>
      <td>${esc(i.title)}<div class="src">${esc(pagesLabel(i))}</div></td>
      <td><span class="sev ${esc(sev)}" aria-hidden="true"></span>${esc(sev[0].toUpperCase() + sev.slice(1))}</td>
      <td class="src ${i.source !== "axe" ? "agent" : ""}">${i.source !== "axe" ? "Agent review" : "Scanner (axe)"}</td>
      <td><span class="pill ${scl}">${sl}</span>${att > 1 ? `<div class="src">attempt ${att}</div>` : ""}</td></tr>`;
    if (ex) {
      const hist = (i.history || []).map((h) => `<li><time>${mmss(h.t)}</time><span class="who">${esc(h.by)}</span><span>${esc(h.note)}</span></li>`).join("");
      const fix = i.fix_diff ? `<pre>${diffHtml(i.fix_diff)}</pre><div class="src" style="margin-top:4px">${i.files && i.files.length ? "Files: " + i.files.map(esc).join(", ") : "No file changed"}</div>`
        : i.status === "needs_human" ? `<p style="margin:0">No code change possible in this repository.</p>` : `<p class="muted" style="margin:0">Not fixed yet.</p>`;
      const human = i.human_action ? `<h3 style="margin-top:12px">Human action</h3><p style="margin:0">${esc(i.human_action)}</p>` : "";
      row += `<tr class="detail" id="d-${esc(i.id)}"><td colspan="6"><div class="dgrid">
        <div><h3>Specification</h3><p style="margin:0 0 8px">WCAG 2.1 · ${esc(i.wcag)} ${esc(i.criterion_name)} (Level ${esc(i.level)}) · EN 301 549 clause ${esc(i.en301549 || "9." + i.wcag)} · ${PRIN[i.principle] || ""}</p>
          <h3>User impact</h3><p style="margin:0 0 8px">${esc(i.impact)}</p><h3>Evidence</h3><pre>${esc(i.evidence)}</pre></div>
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
    p.innerHTML = `<div class="empty">The pull request is assembled once every fix has been verified by the tester agent.${S.commits.length ? ` <br><span class="mono">${S.commits.length} commit${S.commits.length > 1 ? "s" : ""} so far</span>` : ""}</div>`;
    return;
  }
  if (p.dataset.ready === "1") return;
  p.dataset.ready = "1";
  const its = issuesList(), fixed = its.filter((i) => i.status === "validated"), nh = its.filter((i) => i.status === "needs_human");
  const sc = S.score || {};
  p.innerHTML = `<div class="prgrid">
   <div>
     <h2 style="margin-bottom:10px">a11y: EAA remediation, WCAG 2.1 AA</h2>
     <dl class="kv"><dt>Repository</dt><dd class="mono">${esc(S.pr.repo)}</dd>
       <dt>Branch</dt><dd class="mono">${esc(S.pr.branch)} → ${esc(S.pr.base)}</dd>
       <dt>Changes</dt><dd>${esc(S.pr.commits)} commits · ${(S.pr.files || []).length} files · ${fixed.length} issues fixed and verified</dd>
       <dt>Open items</dt><dd>${nh.length ? nh.map((i) => `<span class="mono">${esc(i.id)}</span> ${esc(i.title)}`).join("<br>") : "None"}</dd>
       <dt>Score</dt><dd>${esc(sc.baseline)} → ${esc(sc.value)}</dd></dl>
     <ul class="commits">${S.commits.map((c) => `<li><span class="h">${esc(String(c.sha).slice(0, 7))}</span><span>${esc(c.message)}</span></li>`).join("")}</ul>
     ${S.pr.body ? `<details class="body"><summary>Pull request description</summary><div class="md">${md(S.pr.body, 3)}</div></details>` : ""}
   </div>
   <form id="prForm" novalidate>
     <fieldset><legend>Reviewers</legend>
       <label class="opt"><input type="checkbox" id="rv1" checked> Frontend team</label>
       <label class="opt"><input type="checkbox" id="rv2" checked> Léa Martin · tech lead</label>
       <label class="opt"><input type="checkbox" id="rv3"> Tom Baker · QA</label></fieldset>
     <fieldset><legend>Notify</legend>
       <label class="opt"><input type="checkbox" id="nt1" checked> Slack · #eng-frontend</label>
       <label class="opt"><input type="checkbox" id="nt2" checked> Create Jira ticket in A11Y</label>
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
      out.insertAdjacentHTML("beforeend", `<div class="sent" role="status"><b>Pull request #${esc(result.number)} opened</b>${result.url ? `<a class="mono" href="${esc(result.url)}">${esc(result.url)}</a>` : `<span class="mono">${esc(repo)} · ${esc(branch)}</span>`}<div class="src" style="margin-top:4px">Engineering notified. ${ext}</div></div>`);
      btn.textContent = "Sent";
    }
  }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 60 : 650);
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
  p.innerHTML = `<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px"><span class="pill p-warn">Draft · partially compliant</span><button class="btn small" id="copyStmt" type="button">Copy statement</button></div>
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
    const tr = e.target.closest("tr.row"); if (!tr || (e.target.closest("a, input, textarea"))) return;
    toggleRow(tr.dataset.id, !!e.target.closest(".rowbtn"));
  });
  document.querySelectorAll("[data-speed]").forEach((b) => b.addEventListener("click", () => {
    speed = +b.dataset.speed; if (source instanceof ReplaySource) source.speed = speed;
    document.querySelectorAll("[data-speed]").forEach((x) => x.setAttribute("aria-pressed", x === b));
  }));
  $("runBtn").addEventListener("click", runAudit);
  $("prBtn").addEventListener("click", () => {
    selectTab("pr"); $("p-pr").scrollIntoView({behavior: "smooth", block: "start"});
    const s = $("sendPr"); if (s) s.focus({preventScroll: true});
  });
  $("copyLog").addEventListener("click", () => copyText(S.logs.map((l) => `${mmss(l.t)} [${l.a}] ${l.text}`).join("\n"), $("copyLog")));
  $("aboutBtn").addEventListener("click", () => $("about").showModal());
  $("about").addEventListener("close", () => { if (location.hash === "#about") history.replaceState(null, "", location.pathname + location.search); });
  const openHash = () => { if (location.hash === "#about" && !$("about").open) $("about").showModal(); };
  addEventListener("hashchange", openHash); openHash();
}

async function init() {
  const q = new URLSearchParams(location.search);
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
