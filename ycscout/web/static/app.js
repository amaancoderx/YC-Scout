/* YC Scout dashboard */
"use strict";

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n ?? 0).toLocaleString();
const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many || one + "s"}`;

const ICONS = {
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  memory: '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M12 5v13"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  spark: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
  settings: '<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.8l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.8v-.4a2 2 0 0 1 1-1.8l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
  linkedin: '<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4v-7a6 6 0 0 1 6-6zM2 9h4v12H2z"/><circle cx="4" cy="4" r="2"/>',
  x: '<path d="M4 4h4.5L20 20h-4.5zM20 4l-6.6 7.2M4 20l6.6-7.2"/>',
  github: '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
  external: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  play: '<path d="m6 3 14 9-14 9z"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  sheet: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
  arrowUp: '<path d="M12 19V5M5 12l7-7 7 7"/>',
};
const icon = (name, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
function hydrateIcons(root = document) {
  $$("[data-icon]", root).forEach((el) => { if (!el.firstChild) el.innerHTML = icon(el.dataset.icon); });
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new Error("Can't reach the YC Scout server. Is it still running?");
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : `Request failed (${res.status})`;
    throw new Error(detail);
  }
  return data;
}

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, kind === "error" ? 6000 : 3200);
  setTimeout(() => el.remove(), kind === "error" ? 6400 : 3600);
}

async function withLoading(btn, fn) {
  if (btn) btn.classList.add("loading");
  try { return await fn(); }
  catch (e) { toast(e.message, "error"); }
  finally { if (btn) btn.classList.remove("loading"); }
}

function timeAgo(iso) {
  if (!iso) return "-";
  const t = new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function initials(name) {
  return esc((name || "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase());
}
function logo(url, name, cls = "") {
  return `<span class="logo ${cls}">${url ? `<img src="${esc(url)}" alt="" loading="lazy" onerror="this.remove()">` : ""}${url ? "" : initials(name)}</span>`;
}

const CONF_LABEL = { verified: "Verified", inferred: "Inferred", likely: "Likely", guess: "Guess" };
const CONF_HELP = {
  verified: "Published by the company or in a cited public source",
  inferred: "Built from the company's own email format",
  likely: "first@domain on a small team with a working mail server",
  guess: "Common format, unconfirmed",
};
const conf = (c) => c ? `<span class="conf conf-${esc(c)}" title="${esc(CONF_HELP[c] || "")}"><span class="d"></span>${esc(CONF_LABEL[c] || c)}</span>` : "";

const STAGES = ["new", "qualified", "contacted", "replied", "meeting", "won", "lost", "skip"];
const STAGE_CLASS = { new: "", qualified: "b-violet", contacted: "b-blue", replied: "b-green", meeting: "b-green", won: "b-green", lost: "b-red", skip: "" };
const stageBadge = (s) => `<span class="badge ${STAGE_CLASS[s] || ""}">${esc((s || "new").replace(/^./, (c) => c.toUpperCase()))}</span>`;
const STATUS_CLASS = { draft: "", approved: "b-violet", sending: "b-blue", sent: "b-blue", replied: "b-green", bounced: "b-red", failed: "b-red", cancelled: "", running: "b-blue", done: "b-green", queued: "" };
const statusBadge = (s) => `<span class="badge ${STATUS_CLASS[s] || ""}">${s === "running" ? '<span class="d"></span>' : ""}${esc(s)}</span>`;

let mdReady = false;
function md(src) {
  if (window.marked && window.DOMPurify) {
    if (!mdReady) {
      marked.setOptions({ gfm: true, breaks: false });
      DOMPurify.addHook("afterSanitizeAttributes", (n) => { if (n.tagName === "A") { n.setAttribute("target", "_blank"); n.setAttribute("rel", "noopener"); } });
      mdReady = true;
    }
    try { return DOMPurify.sanitize(marked.parse(String(src || ""))); } catch { /* fall back below */ }
  }
  return mdLite(src);
}
function mdLite(src) {
  // Minimal, safe markdown: escape first, then format.
  const lines = esc(src || "").split(/\r?\n/);
  let out = "", inList = false, table = [];
  const inline = (t) => t
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r));
    const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
    out += "<table><thead><tr>" + cells(rows[0]).map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>" +
      rows.slice(1).map((r) => "<tr>" + cells(r).map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
    table = [];
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^\s*\|.*\|\s*$/.test(line)) { if (inList) { out += "</ul>"; inList = false; } table.push(line.trim()); continue; }
    flushTable();
    const li = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (li) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${inline(li[1])}</li>`; continue; }
    if (inList) { out += "</ul>"; inList = false; }
    const h = line.match(/^#{1,4}\s+(.*)$/);
    if (h) { out += `<p><strong>${inline(h[1])}</strong></p>`; continue; }
    if (line.trim()) out += `<p>${inline(line)}</p>`;
  }
  flushTable();
  if (inList) out += "</ul>";
  return out;
}

function copy(text) {
  navigator.clipboard.writeText(text).then(() => toast(`Copied ${text}`), () => toast("Copy failed", "error"));
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
function openModal(html, onMount) {
  $("#modal").innerHTML = html;
  $("#modal-backdrop").hidden = false;
  hydrateIcons($("#modal"));
  onMount && onMount($("#modal"));
  const first = $("#modal").querySelector("input, textarea, select");
  first && first.focus();
}
function closeModal() { $("#modal-backdrop").hidden = true; $("#modal").innerHTML = ""; }
$("#modal-backdrop").addEventListener("mousedown", (e) => { if (e.target.id === "modal-backdrop") closeModal(); });

function confirmModal({ title, body, confirm = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    openModal(`
      <div class="modal-head"><h3>${esc(title)}</h3></div>
      <div class="modal-body"><div class="prose">${body}</div></div>
      <div class="modal-foot"><button class="btn" data-x="no">Cancel</button><button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-x="yes">${esc(confirm)}</button></div>`,
      (m) => {
        m.querySelector('[data-x="no"]').onclick = () => { closeModal(); resolve(false); };
        m.querySelector('[data-x="yes"]').onclick = () => { closeModal(); resolve(true); };
      });
  });
}

// ---------------------------------------------------------------------------
// App state + router
// ---------------------------------------------------------------------------
const state = {
  status: null,
  companies: { q: "", batch: "", industry: "", stage: "", hiring: false, remote: false, phone: false, email: "", researched: false, sort: "fit", dir: "desc", page: 1, selected: new Set(), data: null },
  outreach: { tab: "draft", activeId: null, selected: new Set(), data: null },
  agent: { session: null, messages: [], chats: [] },
  runPoll: null,
};

const PAGES = {
  overview: { title: "Overview", sub: "Recently funded YC startups at a glance", render: renderOverview },
  companies: { title: "Companies", sub: "Every company, founder, contact and open role", render: renderCompanies },
  outreach: { title: "Outreach", sub: "Review, approve and send. Nothing goes out without approval.", render: renderOutreach },
  pipeline: { title: "Pipeline", sub: "Pull batches from YC, enrich, research and automate", render: renderPipeline },
  agent: { title: "Agent", sub: "Run the whole workflow in plain English", render: renderAgent },
  settings: { title: "Settings", sub: "Integrations, your profile, templates and sending rules", render: renderSettings },
};

function route() {
  const name = (location.hash.replace(/^#\/?/, "").split("?")[0] || "overview");
  const page = PAGES[name] || PAGES.overview;
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  $("#page-title").textContent = page.title;
  $("#page-sub").textContent = page.sub;
  $("#page-actions").innerHTML = "";
  if (state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; }
  const content = $("#content");
  content.innerHTML = `<div class="card card-body"><div class="skeleton" style="width:40%"></div><br><div class="skeleton"></div><br><div class="skeleton" style="width:70%"></div></div>`;
  const open = new URLSearchParams(location.hash.split("?")[1] || "").get("open");
  if (open) openCompany(+open);
  page.render(content).catch((e) => {
    content.innerHTML = `<div class="card"><div class="empty"><h3>Something went wrong</h3><p>${esc(e.message)}</p><button class="btn" onclick="route()">Try again</button></div></div>`;
  });
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------------------
// Status polling (sidebar)
// ---------------------------------------------------------------------------
async function pollStatus() {
  try {
    const s = await api("/api/status");
    state.status = s;
    const names = { ai: "Gemini AI", smtp: "Email sending", imap: "Reply tracking", sheets: "Google Sheets" };
    $("#integrations").innerHTML = Object.entries(s.integrations).map(([k, v]) =>
      `<a class="integration" href="#/settings" title="${esc(v.detail)}"><span class="dot ${v.ok ? "on" : "off"}"></span><b>${names[k]}</b><span class="grow"></span>${v.ok ? "" : '<span class="faint">off</span>'}</a>`).join("");
    $("#badge-pipeline").hidden = !s.active_runs.length;
    const counts = await api("/api/outreach?status=draft&limit=1");
    const d = counts.counts.draft || 0;
    $("#badge-outreach").hidden = !d;
    $("#badge-outreach").textContent = d;
  } catch { /* server restarting; ignore */ }
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------
async function renderOverview(root) {
  const [o, batches] = await Promise.all([api("/api/overview"), api("/api/batches").catch(() => [])]);
  const k = o.kpis;
  $("#page-actions").innerHTML = `<a class="btn" href="/api/export.xlsx">${icon("download")}Export Excel</a><a class="btn btn-primary" href="#/pipeline">${icon("refresh")}Sync batches</a>`;

  if (!k.companies) {
    const latest = batches.filter((b) => b.count >= 20).slice(0, 2);
    root.innerHTML = `
      <div class="card"><div class="empty" style="padding:56px 20px">
        <h3>Start by pulling the latest YC batches</h3>
        <p>YC Scout fetches every company in a batch, then its founders, open roles, website contacts and email addresses.</p>
        <button class="btn btn-primary" id="quick-sync">${icon("play")}Sync ${latest.map((b) => esc(b.name)).join(" + ") || "latest batches"}</button>
        <p class="faint" style="margin-top:12px">Takes roughly 3–6 minutes for ~450 companies.</p>
      </div></div>`;
    $("#quick-sync").onclick = (e) => withLoading(e.currentTarget, async () => {
      await api("/api/runs/sync", { method: "POST", body: { batches: latest.map((b) => b.slug), crawl: true } });
      toast("Sync started");
      location.hash = "#/pipeline";
    });
    return;
  }

  const maxB = Math.max(1, ...o.batches.map((b) => b.companies));
  const maxI = Math.max(1, ...o.industries.map((i) => i.n));
  const maxR = Math.max(1, ...o.roles.map((i) => i.n));
  const replyRate = k.sent ? Math.round((k.replied / k.sent) * 100) : 0;
  root.innerHTML = `
    <div class="kpis">
      ${kpi("Companies", k.companies, `${fmt(k.founders)} founders`)}
      ${kpi("Verified contact", k.with_verified_email, `${pct(k.with_verified_email, k.companies)} of companies`)}
      ${kpi("Any email", k.with_any_email, `${pct(k.with_any_email, k.companies)} coverage`)}
      ${kpi("Hiring", k.hiring, `${fmt(k.open_roles)} open roles · ${fmt(k.remote_roles)} remote`)}
      ${kpi("Emails sent", k.sent, `${fmt(k.drafts)} drafts · ${fmt(k.approved)} queued`)}
      ${kpi("Reply rate", replyRate + "%", `${fmt(k.replied)} replies`)}
    </div>
    <div class="grid grid-main">
      <div class="stack">
        <div class="card">
          <div class="card-head"><div><h3>Pipeline</h3><p>Where every company sits in your outreach</p></div><a class="btn btn-sm" href="#/companies">Open companies</a></div>
          <div class="card-body"><div class="funnel">
            ${["new", "qualified", "contacted", "replied", "meeting", "won"].map((s) => `<a href="#/companies" data-stage="${s}"><div class="n">${fmt(o.funnel[s])}</div><div class="l">${s}</div></a>`).join("")}
          </div></div>
        </div>
        <div class="card">
          <div class="card-head"><div><h3>Batches</h3><p>Companies loaded, hiring and with a verified contact</p></div></div>
          <div class="card-body"><div class="bar-list">
            ${o.batches.map((b) => `<div class="bar-row"><span class="name">${esc(b.batch)}</span><div class="bar-track"><div class="bar-fill" style="width:${(b.companies / maxB) * 100}%"></div></div><span class="n">${fmt(b.companies)}</span></div>
              <div class="bar-row" style="margin-top:-6px"><span></span><span class="faint" style="font-size:12px">${fmt(b.hiring)} hiring · ${fmt(b.verified)} verified contacts</span><span></span></div>`).join("")}
          </div></div>
        </div>
        <div class="grid grid-2">
          <div class="card"><div class="card-head"><h3>Industries</h3></div><div class="card-body"><div class="bar-list">
            ${o.industries.map((i) => `<div class="bar-row"><span class="name">${esc(i.industry)}</span><div class="bar-track"><div class="bar-fill" style="width:${(i.n / maxI) * 100}%"></div></div><span class="n">${i.n}</span></div>`).join("") || '<p class="muted">No data yet</p>'}
          </div></div></div>
          <div class="card"><div class="card-head"><h3>Roles being hired</h3></div><div class="card-body"><div class="bar-list">
            ${o.roles.map((i) => `<div class="bar-row"><span class="name">${esc(i.role)}</span><div class="bar-track"><div class="bar-fill" style="width:${(i.n / maxR) * 100}%"></div></div><span class="n">${i.n}</span></div>`).join("") || '<p class="muted">No open roles found yet</p>'}
          </div></div></div>
        </div>
      </div>
      <div class="stack">
        <div class="card">
          <div class="card-head"><h3>Recently added</h3></div>
          <div>${o.newest.map((c) => `<div class="mail-item" data-open="${c.id}">${logo(c.logo_url, c.name)}<div class="meta"><div class="subj">${esc(c.name)} <span class="faint">· ${esc(c.batch)}</span></div><div class="to">${esc(c.one_liner)}</div></div></div>`).join("")}</div>
        </div>
        <div class="card">
          <div class="card-head"><h3>Recent jobs</h3><a class="btn btn-sm" href="#/pipeline">View all</a></div>
          <div>${o.runs.map(runRow).join("") || '<div class="empty">No runs yet</div>'}</div>
        </div>
      </div>
    </div>`;
  $$("[data-open]", root).forEach((el) => (el.onclick = () => openCompany(+el.dataset.open)));
  $$("[data-stage]", root).forEach((el) => (el.onclick = () => { Object.assign(state.companies, { stage: el.dataset.stage, page: 1 }); }));
}
const kpi = (label, value, sub) => `<div class="card kpi"><div class="label">${esc(label)}</div><div class="value">${typeof value === "number" ? fmt(value) : esc(value)}</div><div class="sub">${esc(sub)}</div></div>`;
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0) + "%";
function runRow(r) {
  const p = r.total ? Math.round((r.progress / r.total) * 100) : r.status === "done" ? 100 : 0;
  return `<div class="mail-item" onclick="location.hash='#/pipeline'"><div class="meta"><div class="row"><span class="subj grow">${esc(r.label || r.kind)}</span>${statusBadge(r.status)}</div>
    <div class="to">${r.status === "running" ? `<div class="progress" style="margin-top:6px"><div style="width:${p}%"></div></div>` : esc(r.summary || "")} <span class="faint">${timeAgo(r.started_at)}</span></div></div></div>`;
}

// ---------------------------------------------------------------------------
// Companies
// ---------------------------------------------------------------------------
async function renderCompanies(root) {
  const batches = await api("/api/batches").catch(() => []);
  const s = state.companies;
  $("#page-actions").innerHTML = `
    <button class="btn" id="export-csv">${icon("download")}CSV</button>
    <button class="btn" id="export-xlsx">${icon("download")}Excel</button>`;
  $("#export-xlsx").onclick = () => exportFiltered("xlsx");
  $("#export-csv").onclick = () => exportFiltered("csv");

  root.innerHTML = `
    <div class="toolbar">
      <div class="search">${icon("search")}<input class="input" id="f-q" placeholder="Search companies, founders, tags" value="${esc(s.q)}"></div>
      <select class="select" id="f-batch"><option value="">All batches</option>${batches.filter((b) => b.loaded).map((b) => `<option value="${b.slug}" ${s.batch === b.slug ? "selected" : ""}>${esc(b.name)} (${b.loaded})</option>`).join("")}</select>
      <select class="select" id="f-industry"><option value="">All industries</option></select>
      <select class="select" id="f-stage"><option value="">Any stage</option>${STAGES.map((x) => `<option value="${x}" ${s.stage === x ? "selected" : ""}>${x[0].toUpperCase() + x.slice(1)}</option>`).join("")}</select>
      <select class="select" id="f-email">
        <option value="" ${!s.email ? "selected" : ""}>Any contact</option>
        <option value="verified" ${s.email === "verified" ? "selected" : ""}>Verified / inferred email</option>
        <option value="any" ${s.email === "any" ? "selected" : ""}>Has an email</option>
        <option value="none" ${s.email === "none" ? "selected" : ""}>No email</option>
      </select>
      <span class="chip ${s.hiring ? "on" : ""}" id="f-hiring">Hiring</span>
      <span class="chip ${s.remote ? "on" : ""}" id="f-remote" title="Companies with at least one open remote role">Remote jobs</span>
      <span class="chip ${s.phone ? "on" : ""}" id="f-phone" title="Companies that publish a phone or WhatsApp number">Has phone</span>
      <span class="chip ${s.researched ? "on" : ""}" id="f-researched">AI researched</span>
      <span class="grow"></span>
      <span class="muted" id="result-count"></span>
    </div>
    <div class="table-wrap"><table class="table"><thead><tr>
      <th class="cb"><input type="checkbox" class="check" id="select-page"></th>
      ${th("Company", "name")}${th("Fit", "fit")}${th("Batch", "batch")}<th>Founders</th><th>Best contact</th><th>Raised</th>${th("Roles", "roles")}${th("Team", "team")}${th("Stage", "stage")}
    </tr></thead><tbody id="rows"></tbody></table></div>
    <div class="pager" id="pager"></div>
    <div class="bulkbar" id="bulkbar" hidden></div>`;

  let t;
  $("#f-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { s.q = e.target.value.trim(); s.page = 1; loadCompanies(); }, 220); };
  const bind = (id, key) => ($(id).onchange = (e) => { s[key] = e.target.value; s.page = 1; loadCompanies(); });
  bind("#f-batch", "batch"); bind("#f-industry", "industry"); bind("#f-stage", "stage"); bind("#f-email", "email");
  $("#f-hiring").onclick = (e) => { s.hiring = !s.hiring; e.currentTarget.classList.toggle("on", s.hiring); s.page = 1; loadCompanies(); };
  $("#f-remote").onclick = (e) => { s.remote = !s.remote; e.currentTarget.classList.toggle("on", s.remote); s.page = 1; loadCompanies(); };
  $("#f-phone").onclick = (e) => { s.phone = !s.phone; e.currentTarget.classList.toggle("on", s.phone); s.page = 1; loadCompanies(); };
  $("#f-researched").onclick = (e) => { s.researched = !s.researched; e.currentTarget.classList.toggle("on", s.researched); s.page = 1; loadCompanies(); };
  $$("th[data-sort]", root).forEach((el) => (el.onclick = () => {
    const key = el.dataset.sort;
    if (s.sort === key) s.dir = s.dir === "asc" ? "desc" : "asc"; else { s.sort = key; s.dir = key === "name" ? "asc" : "desc"; }
    renderCompanies(root);
  }));
  $("#select-page").onchange = (e) => {
    (s.data?.rows || []).forEach((r) => (e.target.checked ? s.selected.add(r.id) : s.selected.delete(r.id)));
    paintRows(); paintBulk();
  };
  await loadCompanies();
}
function th(label, key) {
  const s = state.companies;
  const arrow = s.sort === key ? `<span class="arrow">${s.dir === "asc" ? "▲" : "▼"}</span>` : "";
  return `<th class="sortable" data-sort="${key}">${label}${arrow}</th>`;
}
function companyQuery(extra = {}) {
  const s = state.companies;
  const p = new URLSearchParams({ q: s.q, batch: s.batch, industry: s.industry, stage: s.stage, email: s.email, sort: s.sort, dir: s.dir, page: s.page, page_size: 50, ...extra });
  if (s.hiring) p.set("hiring", "true");
  if (s.remote) p.set("remote", "true");
  if (s.phone) p.set("phone", "true");
  if (s.researched) p.set("researched", "true");
  return p.toString();
}
async function loadCompanies() {
  const s = state.companies;
  const data = await api(`/api/companies?${companyQuery()}`);
  s.data = data;
  const ind = $("#f-industry");
  if (ind && ind.options.length <= 1) {
    ind.innerHTML = `<option value="">All industries</option>` + data.industries.map((i) => `<option ${s.industry === i ? "selected" : ""}>${esc(i)}</option>`).join("");
  }
  $("#result-count").textContent = plural(data.total, "company", "companies");
  paintRows();
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  $("#pager").innerHTML = data.total ? `<span>Showing ${fmt((s.page - 1) * data.page_size + 1)}–${fmt(Math.min(data.total, s.page * data.page_size))} of ${fmt(data.total)}</span>
    <span class="row"><button class="btn btn-sm" ${s.page <= 1 ? "disabled" : ""} id="prev">Previous</button><span>Page ${s.page} of ${pages}</span><button class="btn btn-sm" ${s.page >= pages ? "disabled" : ""} id="next">Next</button></span>` : "";
  $("#prev") && ($("#prev").onclick = () => { s.page--; loadCompanies(); });
  $("#next") && ($("#next").onclick = () => { s.page++; loadCompanies(); });
  paintBulk();
}
function phoneKey(n) {
  let d = String(n || "").replace(/\D/g, "");
  if (d.startsWith("00")) d = d.slice(2);
  return d.length >= 10 ? d.slice(-10) : d;
}
function parseList(v) {
  if (Array.isArray(v)) return v;
  try { return JSON.parse(v || "[]") || []; } catch { return []; }
}
function phoneMark(c) {
  const phones = parseList(c.phones).map((p) => p.number).filter(Boolean);
  const wa = parseList(c.whatsapp);
  if (!phones.length && !wa.length) return "";
  const label = [...phones, ...wa.map((w) => (w.number ? w.number + " (WhatsApp)" : "WhatsApp link"))];
  const unique = [...new Map(label.map((x) => [phoneKey(x) || x, x])).values()];
  return ` <span class="phone-mark ${wa.length ? "wa" : ""}" title="${esc(unique.join(" · "))}">${icon("phone")}</span>`;
}
function fitBadge(score, reasons) {
  if (score == null) return '<span class="faint">-</span>';
  let list = reasons;
  if (typeof list === "string") { try { list = JSON.parse(list); } catch { list = []; } }
  const cls = score >= 60 ? "b-green" : score >= 35 ? "b-amber" : "";
  return `<span class="badge ${cls}" title="${esc((list || []).join(" · ") || "No specific match")}">${score}</span>`;
}
function paintRows() {
  const s = state.companies;
  const rows = s.data?.rows || [];
  const body = $("#rows");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="10"><div class="empty"><h3>No companies match</h3><p>Adjust the filters, or pull more batches from the Pipeline page.</p><a class="btn" href="#/pipeline">Open pipeline</a></div></td></tr>`;
    return;
  }
  body.innerHTML = rows.map((c) => `
    <tr data-id="${c.id}" class="${s.selected.has(c.id) ? "selected" : ""}">
      <td class="cb"><input type="checkbox" class="check" data-cb="${c.id}" ${s.selected.has(c.id) ? "checked" : ""}></td>
      <td><div class="co">${logo(c.logo_url, c.name)}<div style="min-width:0"><div class="co-name">${esc(c.name)}${phoneMark(c)}${c.priority ? ' <span class="badge b-accent">Priority</span>' : ""}</div><div class="co-line">${esc(c.one_liner)}</div></div></div></td>
      <td>${fitBadge(c.fit_score, c.fit_reasons)}</td>
      <td class="nowrap">${esc(shortBatch(c.batch))}</td>
      <td><div class="ellipsis" style="max-width:170px" title="${esc(c.founders || "")}">${esc(c.founders || "-")}</div></td>
      <td>${c.best_email ? `<div class="mono ellipsis" style="max-width:210px" title="${esc(c.best_email)}">${esc(c.best_email)}</div>${conf(c.best_confidence)}` : '<span class="faint">-</span>'}</td>
      <td class="nowrap">${esc(c.funding_total || "-")}${c.funding_source === "researched" ? ' <span class="badge b-green" title="Funding found in cited sources">cited</span>' : ""}</td>
      <td>${c.open_roles ? `<span class="badge b-blue">${c.open_roles}</span>${c.remote_roles ? ` <span class="badge b-green" title="${c.remote_roles} remote">${c.remote_roles} remote</span>` : ""}` : '<span class="faint">0</span>'}</td>
      <td>${c.team_size ?? "-"}</td>
      <td>${stageBadge(c.stage)}${c.last_outreach ? `<div class="faint" style="font-size:11.5px;margin-top:2px">email ${esc(c.last_outreach)}</div>` : ""}</td>
    </tr>`).join("");
  $$("tr[data-id]", body).forEach((tr) => (tr.onclick = (e) => {
    if (e.target.closest("[data-cb]")) return;
    openCompany(+tr.dataset.id);
  }));
  $$("[data-cb]", body).forEach((cb) => (cb.onchange = (e) => {
    const id = +cb.dataset.cb;
    e.target.checked ? s.selected.add(id) : s.selected.delete(id);
    cb.closest("tr").classList.toggle("selected", e.target.checked);
    paintBulk();
  }));
  const all = $("#select-page");
  if (all) all.checked = rows.length > 0 && rows.every((r) => s.selected.has(r.id));
}
const shortBatch = (b) => { const m = /^(\w+) (\d{4})$/.exec(b || ""); return m ? `${m[1]} ’${m[2].slice(2)}` : b || "-"; };

function paintBulk() {
  const s = state.companies;
  const bar = $("#bulkbar");
  if (!bar) return;
  const n = s.selected.size;
  bar.hidden = !n;
  if (!n) return;
  const total = s.data?.total || 0;
  bar.innerHTML = `
    <span class="count">${plural(n, "selected", "selected")}</span>
    ${total > n && total <= 500 ? `<button class="btn btn-sm" id="bulk-all">Select all ${fmt(total)}</button>` : ""}
    <button class="btn" id="bulk-draft">${icon("mail")}Draft emails</button>
    <button class="btn" id="bulk-research">${icon("spark")}Research with AI</button>
    <select class="select" id="bulk-stage"><option value="">Set stage…</option>${STAGES.map((x) => `<option value="${x}">${x[0].toUpperCase() + x.slice(1)}</option>`).join("")}</select>
    <button class="btn" id="bulk-export">${icon("download")}Export</button>
    <button class="btn btn-icon" id="bulk-clear" title="Clear selection">${icon("close")}</button>`;
  $("#bulk-clear").onclick = () => { s.selected.clear(); paintRows(); paintBulk(); };
  $("#bulk-all") && ($("#bulk-all").onclick = async () => {
    const ids = await api(`/api/companies/ids?${companyQuery()}`);
    ids.forEach((i) => s.selected.add(i)); paintRows(); paintBulk();
  });
  $("#bulk-draft").onclick = () => draftModal([...s.selected]);
  $("#bulk-research").onclick = () => researchCompanies([...s.selected]);
  $("#bulk-export").onclick = () => { location.href = `/api/export.xlsx?ids=${[...s.selected].join(",")}`; };
  $("#bulk-stage").onchange = async (e) => {
    if (!e.target.value) return;
    await withLoading(null, async () => {
      await api("/api/companies/bulk", { method: "POST", body: { ids: [...s.selected], stage: e.target.value } });
      toast(`Moved ${plural(s.selected.size, "company", "companies")} to ${e.target.value}`);
      loadCompanies();
    });
  };
}

async function exportFiltered(kind) {
  const ids = await api(`/api/companies/ids?${companyQuery()}`);
  const filtered = state.companies.q || state.companies.batch || state.companies.industry || state.companies.stage || state.companies.email || state.companies.hiring || state.companies.remote || state.companies.phone || state.companies.researched;
  const idParam = filtered ? `ids=${ids.join(",")}` : "";
  location.href = kind === "xlsx" ? `/api/export.xlsx?${idParam}` : `/api/export.csv?${idParam}`;
}

async function researchCompanies(ids, force = false) {
  if (!state.status?.integrations.ai.ok) return toast("AI research needs GEMINI_API_KEY in your .env file.", "error");
  const ok = await confirmModal({
    title: force ? "Refresh AI research for this company?" : `Research ${plural(ids.length, "company", "companies")} with AI?`,
    body: `<p>Gemini searches Google for funding rounds, published contact details, traction and news. Every email it reports is checked against the cited page before it's saved, and every fact keeps its source.</p><p class="muted">${force ? "This company was researched before; this runs it again to pick up anything new." : "Companies already researched are skipped, so nothing is collected twice."} Uses about 2 Gemini requests per company. Free keys allow roughly 10 a minute.</p>`,
    confirm: "Start research",
  });
  if (!ok) return;
  await withLoading(null, async () => {
    await api("/api/runs/research", { method: "POST", body: { ids, force } });
    toast("Research started. Track it on the Pipeline page.");
  });
}

function draftModal(ids) {
  const ai = state.status?.integrations.ai.ok;
  let mode = ai ? "ai" : "template";
  let target = "ceo";
  openModal(`
    <div class="modal-head"><h3>Draft emails for ${plural(ids.length, "company", "companies")}</h3><p>Drafts land in Outreach for review. Nothing is sent yet.</p></div>
    <div class="modal-body">
      <div class="field"><label>Writer</label>
        <div class="segmented" id="seg-mode"><button data-v="ai" class="${mode === "ai" ? "on" : ""}" ${ai ? "" : "disabled title='Add GEMINI_API_KEY to enable'"}>AI personalized</button><button data-v="template" class="${mode === "template" ? "on" : ""}">My template</button></div>
        <span class="hint">${ai ? "AI writes a unique email per founder from their company, jobs, launch and bio, using your profile in Settings." : "Add GEMINI_API_KEY to .env for AI-personalized emails."}</span>
      </div>
      <div class="field"><label>Recipients</label>
        <div class="segmented" id="seg-target"><button data-v="ceo" class="on">CEO / lead founder</button><button data-v="founders">All founders</button><button data-v="inbox">Company inbox</button></div>
      </div>
      <div class="field" id="instr-field"><label>Angle for these emails <span class="faint">(optional)</span></label>
        <textarea class="textarea" id="instr" rows="3" placeholder="e.g. Mention I've shipped two dev-tool products and ask about their open engineering role."></textarea></div>
      <div class="callout">Companies already emailed, and addresses on your do-not-contact list, are skipped automatically.</div>
    </div>
    <div class="modal-foot"><button class="btn" id="m-cancel">Cancel</button><button class="btn btn-primary" id="m-go">Create drafts</button></div>`,
    (m) => {
      const seg = (id, set) => $$(`#${id} button`, m).forEach((b) => (b.onclick = () => { if (b.disabled) return; $$(`#${id} button`, m).forEach((x) => x.classList.remove("on")); b.classList.add("on"); set(b.dataset.v); }));
      seg("seg-mode", (v) => { mode = v; $("#instr-field", m).hidden = v !== "ai"; });
      seg("seg-target", (v) => (target = v));
      $("#instr-field", m).hidden = mode !== "ai";
      $("#m-cancel", m).onclick = closeModal;
      $("#m-go", m).onclick = (e) => withLoading(e.currentTarget, async () => {
        await api("/api/runs/drafts", { method: "POST", body: { ids, mode, target, instructions: $("#instr", m).value } });
        closeModal();
        toast(mode === "ai" ? "Writing drafts… they'll appear in Outreach as they're ready." : "Drafts created");
        setTimeout(pollStatus, 1500);
      });
    });
}

// ---------------------------------------------------------------------------
// Company drawer
// ---------------------------------------------------------------------------
function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer-backdrop").hidden = true;
}
$("#drawer-backdrop").onclick = closeDrawer;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { if (!$("#modal-backdrop").hidden) closeModal(); else closeDrawer(); }
});

async function openCompany(id) {
  const drawer = $("#drawer");
  drawer.innerHTML = `<div class="drawer-body"><div class="skeleton" style="width:50%"></div><div class="skeleton"></div><div class="skeleton" style="width:80%"></div></div>`;
  drawer.classList.add("open");
  $("#drawer-backdrop").hidden = false;
  try {
    paintCompany(await api(`/api/companies/${id}`));
  } catch (e) {
    drawer.innerHTML = `<div class="empty"><h3>Couldn't load company</h3><p>${esc(e.message)}</p></div>`;
  }
}

function linkBtn(url, ic, title) {
  return url ? `<a class="btn btn-sm" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(title)}">${icon(ic)}${esc(title)}</a>` : "";
}

function paintCompany(c) {
  const drawer = $("#drawer");
  const founders = c.founders.filter((f) => f.is_active);
  const byFounder = (fid) => c.contacts.filter((x) => x.founder_id === fid);
  const companyEmails = c.contacts.filter((x) => !x.founder_id);
  const other = c.other_links || {};
  const emailRow = (x) => `
    <div class="email-row">
      <span class="mono grow" title="${esc(x.email)}">${esc(x.email)}</span>
      ${x.label ? `<span class="badge">${esc(x.label)}</span>` : ""}
      ${conf(x.confidence)}
      ${x.mx_ok === 0 ? '<span class="badge b-red" title="Domain has no working mail server">No MX</span>' : ""}
      ${x.source_url ? `<a class="btn btn-ghost btn-sm btn-icon" href="${esc(x.source_url)}" target="_blank" rel="noopener" title="Found on ${esc(x.source_url)}">${icon("external")}</a>` : ""}
      <button class="btn btn-ghost btn-sm btn-icon" data-copy="${esc(x.email)}" title="Copy">${icon("copy")}</button>
      <button class="btn btn-ghost btn-sm btn-icon" data-del-contact="${x.id}" title="Remove">${icon("trash")}</button>
    </div>`;
  const facts = [
    ["Batch", c.batch], ["Location", c.location], ["Founded", c.year_founded],
    ["Team size", c.team_size], ["Industry", c.subindustry || c.industry], ["YC status", c.yc_status],
    ["YC partner", c.yc_partner], ["Mail domain", c.mail_domain || c.domain], ["Added", timeAgo(c.first_seen_at)],
  ];
  drawer.innerHTML = `
    <div class="drawer-head">
      <div class="drawer-title">
        ${logo(c.logo_url, c.name, "logo-lg")}
        <div class="grow" style="min-width:0">
          <div class="row"><h2>${esc(c.name)}</h2><span class="badge">${esc(c.batch || "")}</span></div>
          <p>${esc(c.one_liner)}</p>
        </div>
        <button class="btn btn-ghost btn-icon" id="d-close" title="Close (Esc)">${icon("close")}</button>
      </div>
      <div class="drawer-links">
        ${linkBtn(c.website, "globe", "Website")}${linkBtn(c.yc_url, "external", "YC")}${linkBtn(c.linkedin_url, "linkedin", "LinkedIn")}${linkBtn(c.twitter_url, "x", "X")}${linkBtn(c.github_url, "github", "GitHub")}${linkBtn(other.calendly, "calendar", "Book a call")}${linkBtn(c.launch_url, "external", "Launch")}
        <span class="grow"></span>
        <select class="select" id="d-stage" style="height:28px">${STAGES.map((x) => `<option value="${x}" ${c.stage === x ? "selected" : ""}>${x[0].toUpperCase() + x.slice(1)}</option>`).join("")}</select>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="btn btn-primary btn-sm" id="d-draft">${icon("mail")}Draft email</button>
        <button class="btn btn-sm" id="d-research">${icon("spark")}${c.researched_at ? "Re-research" : "Research with AI"}</button>
        <button class="btn btn-sm" id="d-refresh">${icon("refresh")}Refresh data</button>
        <button class="btn btn-sm" id="d-priority">${c.priority ? "Unmark priority" : "Mark priority"}</button>
        <span class="grow"></span>
        <span class="faint" style="font-size:12px">Updated ${timeAgo(c.updated_at)}</span>
      </div>
    </div>
    <div class="drawer-body">
      ${c.fit_score != null ? `<div class="section"><h4>Why it fits you <span class="faint" style="text-transform:none;letter-spacing:0;font-weight:400">${c.fit_score}/100</span></h4>
        ${(JSON.parse(c.fit_reasons || "[]")).length ? `<ul class="fit-list">${JSON.parse(c.fit_reasons).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : '<p class="faint" style="margin:0">No direct match with your strengths or open roles.</p>'}
        ${c.fit_proof ? `<div class="muted" style="margin-top:8px;font-size:12.5px">Your proof point for this one: ${esc(c.fit_proof)}</div>` : ""}
      </div>` : ""}
      <div class="section"><h4>About</h4>
        <div class="prose"><p>${esc(c.summary || c.one_liner)}</p></div>
        ${c.description && c.description !== c.summary ? `<details><summary class="link" style="cursor:pointer;font-size:12.5px">Full description</summary><div class="prose" style="margin-top:8px;white-space:pre-line">${esc(c.description)}</div></details>` : ""}
        ${(c.tags || []).length ? `<div class="row" style="flex-wrap:wrap;margin-top:10px">${c.tags.map((t) => `<span class="badge">${esc(t)}</span>`).join("")}</div>` : ""}
      </div>
      <div class="section"><div class="facts">${facts.map(([k, v]) => `<div><div class="k">${k}</div><div class="v">${esc(v ?? "-") || "-"}</div></div>`).join("")}</div></div>

      <div class="section"><h4>Funding</h4>
        <div class="row"><span style="font-size:20px;font-weight:650">${esc(c.funding_total || "$500K")}</span>
          ${c.funding_source === "researched" ? '<span class="badge b-green">From cited sources</span>' : '<span class="badge">YC standard deal</span>'}</div>
        <div class="muted" style="margin-top:4px">${esc(c.funding_detail || "")}</div>
        ${(c.funding_rounds || []).length ? `<div class="email-list" style="margin-top:10px">${c.funding_rounds.map((r) => `<div class="email-row"><span class="grow"><b>${esc(r.round)}</b> ${esc(r.amount || "")} <span class="muted">${esc(r.date || "")}${r.investors?.length ? " · " + esc(r.investors.join(", ")) : ""}</span></span><a class="btn btn-ghost btn-sm btn-icon" href="${esc(r.source_url)}" target="_blank" rel="noopener" title="Source">${icon("external")}</a></div>`).join("")}</div>`
          : c.researched_at ? '<p class="faint" style="margin:6px 0 0">AI research found no announced round beyond YC.</p>' : '<p class="faint" style="margin:6px 0 0">Run AI research to look for rounds beyond YC.</p>'}
      </div>

      <div class="section"><h4>Founders <span class="faint" style="text-transform:none;letter-spacing:0;font-weight:400">${founders.length}</span></h4>
        <div class="stack">${founders.map((f) => `
          <div class="person">
            <div class="person-head">
              <div><div class="person-name">${esc(f.name)}</div><div class="muted" style="font-size:12.5px">${esc(f.title || "Founder")}</div></div>
              <div class="row">${f.linkedin_url ? `<a class="btn btn-sm btn-icon" href="${esc(f.linkedin_url)}" target="_blank" rel="noopener" title="LinkedIn">${icon("linkedin")}</a>` : ""}${f.twitter_url ? `<a class="btn btn-sm btn-icon" href="${esc(f.twitter_url)}" target="_blank" rel="noopener" title="X">${icon("x")}</a>` : ""}</div>
            </div>
            ${f.bio ? `<div class="person-bio" data-bio>${esc(f.bio)}</div>` : ""}
            <div class="email-list">${byFounder(f.id).map(emailRow).join("") || '<span class="faint">No email found. Add one below if you have it.</span>'}</div>
          </div>`).join("") || '<p class="muted">No founders listed on YC.</p>'}</div>
      </div>

      <div class="section"><h4>Company contact</h4>
        <div class="email-list">${companyEmails.map(emailRow).join("") || '<span class="faint">No company inbox published on the website.</span>'}</div>
        ${(c.phones || []).length || (c.whatsapp || []).length ? `<div class="email-list" style="margin-top:8px">
          ${(c.whatsapp || []).filter((w) => !w.number || !(c.phones || []).some((p) => phoneKey(p.number) === phoneKey(w.number))).map((w) => `<div class="email-row">${icon("phone")}<span class="mono grow">${esc(w.number || w.link)}</span><span class="badge b-green">WhatsApp</span><a class="btn btn-sm" href="${esc(w.number ? "https://wa.me/" + w.number.replace(/\D/g, "") : w.link)}" target="_blank" rel="noopener">Open chat</a>${w.source_url ? `<a class="btn btn-ghost btn-sm btn-icon" href="${esc(w.source_url)}" target="_blank" title="Source">${icon("external")}</a>` : ""}</div>`).join("")}
          ${(c.phones || []).map((p) => `<div class="email-row">${icon("phone")}<span class="mono grow">${esc(p.number)}</span>${(c.whatsapp || []).some((w) => w.number && phoneKey(w.number) === phoneKey(p.number)) ? '<span class="badge b-green">WhatsApp</span>' : ""}<a class="btn btn-sm" href="https://wa.me/${esc(p.number.replace(/\D/g, ""))}" target="_blank" rel="noopener" title="Try this number on WhatsApp">WhatsApp</a><a class="btn btn-sm" href="tel:${esc(p.number)}">Call</a>${p.source_url ? `<a class="btn btn-ghost btn-sm btn-icon" href="${esc(p.source_url)}" target="_blank" title="Source">${icon("external")}</a>` : ""}</div>`).join("")}
        </div>` : '<p class="faint" style="margin:8px 0 0">No phone or WhatsApp number is published.</p>'}
        <form class="row" id="add-email" style="margin-top:10px">
          <input class="input grow mono" name="email" placeholder="Add an email you know" autocomplete="off">
          <select class="select" name="founder"><option value="">Company</option>${founders.map((f) => `<option value="${f.id}">${esc(f.name)}</option>`).join("")}</select>
          <button class="btn" type="submit">${icon("plus")}Add</button>
        </form>
      </div>

      <div class="section"><h4>Open roles <span class="faint" style="text-transform:none;letter-spacing:0;font-weight:400">${c.jobs.length}</span></h4>
        <div class="stack" style="gap:8px">${c.jobs.map((j) => `
          <a class="job" href="${esc(j.url)}" target="_blank" rel="noopener">
            <div><div class="job-title">${esc(j.title)}${/remote/i.test(j.location || "") ? ' <span class="badge b-green">Remote</span>' : ""}</div><div class="job-meta">${[j.location, j.type, j.salary, j.equity && "equity " + j.equity, j.experience, j.visa].filter(Boolean).map((x) => `<span>${esc(x)}</span>`).join("")}</div></div>
            <span class="row muted nowrap" style="font-size:12px">${esc(j.posted ? j.posted + " ago" : "")} ${icon("external")}</span>
          </a>`).join("") || `<p class="faint" style="margin:0">No public roles on YC's job board right now.</p>`}</div>
      </div>

      ${c.research_notes ? `<div class="section"><h4>AI research <span class="faint" style="text-transform:none;letter-spacing:0;font-weight:400">${timeAgo(c.researched_at)}</span></h4><div class="prose">${md(c.research_notes)}</div></div>` : ""}

      ${c.news.length ? `<div class="section"><h4>News</h4><div class="stack" style="gap:6px">${c.news.map((n) => `<a class="link" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a><span class="faint" style="font-size:12px;margin-top:-6px">${esc(n.date || "")}</span>`).join("")}</div></div>` : ""}

      <div class="section"><h4>Outreach</h4>
        ${c.outreach.length ? `<div class="email-list">${c.outreach.map((o) => `<div class="email-row"><span class="grow ellipsis"><b>${esc(o.subject)}</b> <span class="muted">→ ${esc(o.to_email)}${o.step > 1 ? " · follow-up " + (o.step - 1) : ""}</span></span>${statusBadge(o.status)}<span class="faint nowrap" style="font-size:12px">${timeAgo(o.sent_at || o.created_at)}</span></div>`).join("")}</div>` : '<p class="faint" style="margin:0">Not contacted yet.</p>'}
      </div>

      <div class="section"><h4>Notes</h4><textarea class="textarea" id="d-notes" rows="4" placeholder="Private notes. Saved automatically.">${esc(c.notes || "")}</textarea></div>
    </div>`;

  hydrateIcons(drawer);
  $("#d-close").onclick = closeDrawer;
  $("#d-stage").onchange = (e) => updateCompany(c.id, { stage: e.target.value }, "Stage updated");
  $("#d-priority").onclick = () => updateCompany(c.id, { priority: c.priority ? 0 : 1 }, c.priority ? "Priority removed" : "Marked as priority", true);
  $("#d-draft").onclick = () => draftModal([c.id]);
  $("#d-research").onclick = () => researchCompanies([c.id], !!c.researched_at);
  $("#d-refresh").onclick = (e) => withLoading(e.currentTarget, async () => { paintCompany(await api(`/api/companies/${c.id}/refresh`, { method: "POST" })); toast("Company refreshed from YC and its website"); });
  let nt;
  $("#d-notes").oninput = (e) => { clearTimeout(nt); nt = setTimeout(() => api(`/api/companies/${c.id}`, { method: "PATCH", body: { notes: e.target.value } }).catch((er) => toast(er.message, "error")), 600); };
  $$("[data-copy]", drawer).forEach((b) => (b.onclick = () => copy(b.dataset.copy)));
  $$("[data-bio]", drawer).forEach((b) => (b.onclick = () => b.classList.toggle("open")));
  $$("[data-del-contact]", drawer).forEach((b) => (b.onclick = () => withLoading(b, async () => paintCompany(await api(`/api/contacts/${b.dataset.delContact}`, { method: "DELETE" })))));
  $("#add-email").onsubmit = (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    withLoading(e.target.querySelector("button"), async () => {
      paintCompany(await api("/api/contacts", { method: "POST", body: { company_id: c.id, email: f.get("email"), founder_id: f.get("founder") ? +f.get("founder") : null } }));
      toast("Email added");
    });
  };
}

async function updateCompany(id, body, msg, repaint = false) {
  await withLoading(null, async () => {
    await api(`/api/companies/${id}`, { method: "PATCH", body });
    toast(msg);
    if (repaint) paintCompany(await api(`/api/companies/${id}`));
    if (location.hash.startsWith("#/companies")) loadCompanies();
  });
}

// ---------------------------------------------------------------------------
// Outreach
// ---------------------------------------------------------------------------
const OUT_TABS = [["draft", "Drafts"], ["approved", "Ready to send"], ["sent", "Sent"], ["replied", "Replied"], ["bounced,failed", "Bounced / failed"], ["cancelled", "Cancelled"]];

async function renderOutreach(root) {
  const o = state.outreach;
  const data = await api(`/api/outreach?status=${o.tab}`);
  o.data = data;
  const smtp = state.status?.integrations.smtp.ok;
  const approved = data.counts.approved || 0;
  $("#page-actions").innerHTML = `
    <span class="muted" style="font-size:12.5px">${fmt(data.sent_today)} / ${fmt(data.daily_limit)} sent today</span>
    <button class="btn" id="o-replies" ${state.status?.integrations.imap.ok ? "" : "disabled title='Configure email in .env'"}>${icon("refresh")}Check replies</button>
    <button class="btn" id="o-follow">Create follow-ups</button>
    <button class="btn btn-accent" id="o-send" ${approved && smtp ? "" : "disabled"} title="${smtp ? "" : "Add SMTP settings to .env"}">${icon("send")}Send ${fmt(approved)} approved</button>`;
  $("#o-send").onclick = sendApproved;
  $("#o-replies").onclick = (e) => withLoading(e.currentTarget, async () => { await api("/api/runs/replies", { method: "POST" }); toast("Checking your inbox for replies…"); setTimeout(() => renderOutreach(root), 4000); });
  $("#o-follow").onclick = (e) => withLoading(e.currentTarget, async () => { const r = await api("/api/outreach/followups", { method: "POST" }); toast(r.created ? `${plural(r.created, "follow-up")} drafted` : "No emails are due for a follow-up yet"); renderOutreach(root); });

  const count = (k) => k.split(",").reduce((a, s) => a + (data.counts[s] || 0), 0);
  const rows = data.rows;
  if (!rows.find((r) => r.id === o.activeId)) o.activeId = rows[0]?.id ?? null;
  o.selected = new Set([...o.selected].filter((id) => rows.some((r) => r.id === id)));

  root.innerHTML = `
    ${!smtp ? `<div class="callout warn" style="margin-bottom:14px">Sending is off. Add <span class="mono">SMTP_USER</span> and <span class="mono">SMTP_PASSWORD</span> to <span class="mono">.env</span> (see README). You can still draft, edit and approve.</div>` : ""}
    <div class="tabs">${OUT_TABS.map(([k, l]) => `<div class="tab ${o.tab === k ? "active" : ""}" data-tab="${k}">${l}<span class="n">${fmt(count(k))}</span></div>`).join("")}</div>
    ${rows.length ? `
    <div class="split">
      <div class="card">
        <div class="card-head" style="padding:10px 14px">
          <label class="check"><input type="checkbox" id="o-all"> <span class="muted">${plural(rows.length, "email")}</span></label>
          <div class="row" id="o-bulk"></div>
        </div>
        <div class="mail-list">${rows.map((r) => `
          <div class="mail-item ${r.id === o.activeId ? "active" : ""}" data-mail="${r.id}">
            <input type="checkbox" class="check" data-sel="${r.id}" ${o.selected.has(r.id) ? "checked" : ""} style="margin-top:3px">
            ${logo(r.logo_url, r.company)}
            <div class="meta">
              <div class="row"><span class="subj grow">${esc(r.company)}</span>${r.step > 1 ? `<span class="badge">Follow-up ${r.step - 1}</span>` : ""}</div>
              <div class="to">${esc(r.subject)}</div>
              <div class="to mono">${esc(r.to_email)} ${conf(r.confidence)}</div>
            </div>
          </div>`).join("")}</div>
      </div>
      <div id="editor"></div>
    </div>` : `<div class="card"><div class="empty"><h3>${o.tab === "draft" ? "No drafts" : "Nothing here yet"}</h3><p>${o.tab === "draft" ? "Select companies on the Companies page and choose “Draft emails”, or ask the Agent." : "Emails show up here as they move through the pipeline."}</p>${o.tab === "draft" ? '<a class="btn" href="#/companies">Go to companies</a>' : ""}</div></div>`}`;

  $$("[data-tab]", root).forEach((t) => (t.onclick = () => { o.tab = t.dataset.tab; o.activeId = null; o.selected.clear(); renderOutreach(root); }));
  $$("[data-mail]", root).forEach((el) => (el.onclick = (e) => {
    if (e.target.closest("[data-sel]")) return;
    o.activeId = +el.dataset.mail;
    $$("[data-mail]", root).forEach((x) => x.classList.toggle("active", +x.dataset.mail === o.activeId));
    paintEditor();
  }));
  $$("[data-sel]", root).forEach((cb) => (cb.onchange = () => { cb.checked ? o.selected.add(+cb.dataset.sel) : o.selected.delete(+cb.dataset.sel); paintOutBulk(); }));
  $("#o-all") && ($("#o-all").onchange = (e) => { rows.forEach((r) => (e.target.checked ? o.selected.add(r.id) : o.selected.delete(r.id))); $$("[data-sel]", root).forEach((cb) => (cb.checked = e.target.checked)); paintOutBulk(); });
  paintOutBulk();
  paintEditor();
}

function paintOutBulk() {
  const o = state.outreach;
  const el = $("#o-bulk");
  if (!el) return;
  const n = o.selected.size;
  const actions = { draft: [["approve", "Approve"], ["delete", "Delete"]], approved: [["unapprove", "Back to drafts"], ["delete", "Delete"]], "bounced,failed": [["retry", "Retry"]], cancelled: [["delete", "Delete"]] }[o.tab] || [];
  el.innerHTML = n ? actions.map(([a, l]) => `<button class="btn btn-sm ${a === "delete" ? "btn-danger" : a === "approve" ? "btn-primary" : ""}" data-bulk="${a}">${l} ${n}</button>`).join("") : "";
  $$("[data-bulk]", el).forEach((b) => (b.onclick = () => withLoading(b, async () => {
    if (b.dataset.bulk === "delete" && !(await confirmModal({ title: `Delete ${plural(n, "email")}?`, body: "<p>This can't be undone.</p>", confirm: "Delete", danger: true }))) return;
    await api("/api/outreach/bulk", { method: "POST", body: { ids: [...o.selected], action: b.dataset.bulk } });
    toast(b.dataset.bulk === "approve" ? `${plural(n, "email")} approved` : "Done");
    o.selected.clear();
    renderOutreach($("#content"));
    pollStatus();
  })));
}

function paintEditor() {
  const o = state.outreach;
  const box = $("#editor");
  if (!box) return;
  const r = o.data.rows.find((x) => x.id === o.activeId);
  if (!r) { box.innerHTML = ""; return; }
  const editable = ["draft", "approved", "cancelled", "failed"].includes(r.status);
  box.innerHTML = `
    <div class="card editor">
      <div class="card-head">
        <div class="row" style="min-width:0">${logo(r.logo_url, r.company)}<div style="min-width:0"><h3 class="ellipsis">${esc(r.company)}</h3><p class="ellipsis">${esc(r.to_name || "")} ${r.batch ? "· " + esc(r.batch) : ""}</p></div></div>
        <div class="row">${statusBadge(r.status)}<button class="btn btn-sm" id="e-company">Company</button></div>
      </div>
      <div class="card-body stack">
        <div class="field"><label>To</label><input class="input mono" id="e-to" value="${esc(r.to_email)}" ${editable ? "" : "disabled"}><span class="hint">${conf(r.confidence)} ${r.confidence ? esc(CONF_HELP[r.confidence] || "") : ""}</span></div>
        <div class="field"><label>Subject</label><input class="input" id="e-subject" value="${esc(r.subject)}" ${editable ? "" : "disabled"}></div>
        <div class="field"><label>Message</label><textarea class="textarea body" id="e-body" ${editable ? "" : "disabled"}>${esc(r.body)}</textarea></div>
        <div class="footer-preview" id="e-footer"></div>
        ${r.error ? `<div class="callout warn">${esc(r.error)}</div>` : ""}
        <div class="row">
          ${r.status === "draft" ? `<button class="btn btn-primary" id="e-approve">${icon("check")}Approve</button>` : ""}
          ${r.status === "approved" ? `<button class="btn" id="e-unapprove">Move back to drafts</button>` : ""}
          ${editable ? `<button class="btn" id="e-save">Save</button>` : ""}
          ${r.status === "sent" ? `<button class="btn" id="e-replied">Mark as replied</button>` : ""}
          <span class="grow"></span>
          <span class="faint" style="font-size:12px">${r.sent_at ? "Sent " + timeAgo(r.sent_at) : "Created " + timeAgo(r.created_at)} · ${r.generated_by === "ai" ? "AI written" : "Template"}</span>
          ${editable ? `<button class="btn btn-ghost btn-danger btn-icon" id="e-delete" title="Delete">${icon("trash")}</button>` : ""}
        </div>
      </div>
    </div>`;
  api("/api/settings").then((s) => {
    const f = [s.signature_footer, s.physical_address].filter((x) => x && x.trim()).join("\n");
    $("#e-footer") && ($("#e-footer").textContent = f ? `Added automatically when sent:\n--\n${f}` : "");
  }).catch(() => {});
  const save = async (extra = {}) => {
    const body = editable ? { to_email: $("#e-to").value, subject: $("#e-subject").value, body: $("#e-body").value, ...extra } : extra;
    return api(`/api/outreach/${r.id}`, { method: "PATCH", body });
  };
  $("#e-company").onclick = () => openCompany(r.company_id);
  $("#e-save") && ($("#e-save").onclick = (e) => withLoading(e.currentTarget, async () => { Object.assign(r, await save()); toast("Saved"); }));
  $("#e-approve") && ($("#e-approve").onclick = (e) => withLoading(e.currentTarget, async () => { await save({ status: "approved" }); toast("Approved and queued to send"); advance(r.id); }));
  $("#e-unapprove") && ($("#e-unapprove").onclick = (e) => withLoading(e.currentTarget, async () => { await save({ status: "draft" }); toast("Moved back to drafts"); advance(r.id); }));
  $("#e-replied") && ($("#e-replied").onclick = (e) => withLoading(e.currentTarget, async () => { await api(`/api/outreach/${r.id}/replied`, { method: "POST" }); toast("Marked as replied. Follow-ups cancelled."); advance(r.id); }));
  $("#e-delete") && ($("#e-delete").onclick = () => withLoading(null, async () => { await api("/api/outreach/bulk", { method: "POST", body: { ids: [r.id], action: "delete" } }); toast("Deleted"); advance(r.id); }));
}
function advance(id) {
  const o = state.outreach;
  const rows = o.data.rows;
  const i = rows.findIndex((x) => x.id === id);
  o.activeId = rows[i + 1]?.id ?? rows[i - 1]?.id ?? null;
  renderOutreach($("#content"));
  pollStatus();
}
async function sendApproved() {
  const s = await api("/api/settings");
  const n = state.outreach.data.counts.approved || 0;
  const left = Math.max(0, s.daily_send_limit - state.outreach.data.sent_today);
  const ok = await confirmModal({
    title: `Send ${plural(Math.min(n, left), "email")} now?`,
    body: `<p>Emails go out from <b>${esc(state.status.integrations.smtp.detail)}</b>, one every ${s.send_delay_seconds}s to protect your sender reputation.</p>
      ${n > left ? `<p>Your daily limit allows ${left} more today. The rest stay queued for tomorrow.</p>` : ""}
      <p class="muted">You can cancel the job from the Pipeline page while it runs.</p>`,
    confirm: "Send emails",
  });
  if (!ok) return;
  await withLoading(null, async () => {
    await api("/api/runs/send", { method: "POST" });
    toast("Sending started");
    location.hash = "#/pipeline";
  });
}

// ---------------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------------
async function renderPipeline(root) {
  const [batches, runs, settings] = await Promise.all([api("/api/batches"), api("/api/runs"), api("/api/settings")]);
  const ai = state.status?.integrations.ai.ok;
  const recent = batches.filter((b) => b.count >= 20).slice(0, 2).map((b) => b.slug);
  const selected = new Set(recent);
  root.innerHTML = `
    <div class="grid grid-main">
      <div class="stack">
        <div class="card">
          <div class="card-head"><div><h3>Sync from Y Combinator</h3><p>Roster → YC company page → website crawl → email intelligence${ai ? " → AI research" : ""}</p></div></div>
          <div class="card-body">
            <div>${batches.map((b) => `
              <label class="batch-row">
                <input type="checkbox" class="check" data-batch="${b.slug}" ${selected.has(b.slug) ? "checked" : ""}>
                <span><b>${esc(b.name)}</b> <span class="muted">· ${fmt(b.count)} companies</span>${b.count < 20 ? ' <span class="badge">Early admits</span>' : ""}</span>
                <span class="muted nowrap" style="font-size:12.5px">${b.loaded ? `${fmt(b.loaded)} loaded` : "Not loaded"}</span>
                <span class="faint nowrap" style="font-size:12px;min-width:70px;text-align:right">${b.last_scraped ? timeAgo(b.last_scraped) : ""}</span>
              </label>`).join("")}</div>
            <div class="divider" style="margin:14px 0"></div>
            <div class="stack" style="gap:10px">
              <label class="check"><input type="checkbox" id="opt-crawl" checked> Crawl company websites for emails, phone, WhatsApp and booking links</label>
              <label class="check" title="${ai ? "" : "Needs GEMINI_API_KEY"}"><input type="checkbox" id="opt-research" ${ai ? "" : "disabled"}> AI deep research: funding rounds, published founder emails, highlights <span class="faint">(uses Gemini quota)</span></label>
              <label class="check"><input type="checkbox" id="opt-force"> Force refresh companies scraped in the last 2 days</label>
            </div>
            <div class="row" style="margin-top:16px"><button class="btn btn-primary" id="run-sync">${icon("play")}Run sync</button><span class="faint" id="sync-est"></span></div>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><div><h3>Jobs</h3><p>Every sync, research, drafting and sending run, with its live log</p></div></div>
          <div class="table-wrap" style="border:0;border-radius:0;box-shadow:none"><table class="table"><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Started</th><th></th></tr></thead>
          <tbody>${runs.map((r) => `<tr data-run="${r.id}"><td><div style="font-weight:500">${esc(r.label || r.kind)}</div><div class="muted ellipsis" style="font-size:12px;max-width:380px">${esc(r.summary || "")}</div></td>
            <td>${statusBadge(r.status)}</td><td>${r.total ? `<div class="row"><div class="progress"><div style="width:${Math.round((r.progress / r.total) * 100)}%"></div></div><span class="faint" style="font-size:12px">${r.progress}/${r.total}</span></div>` : ""}</td>
            <td class="nowrap muted">${timeAgo(r.started_at)}</td><td class="right">${r.status === "running" ? `<button class="btn btn-sm" data-cancel="${r.id}">Cancel</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="5"><div class="empty">No jobs yet. Run your first sync above.</div></td></tr>`}</tbody></table></div>
        </div>
      </div>
      <div class="stack">
        <div class="card" id="log-card" hidden><div class="card-head"><div><h3 id="log-title">Log</h3><p id="log-sub"></p></div><button class="btn btn-sm btn-icon" id="log-close">${icon("close")}</button></div><div class="card-body"><div class="log" id="log"></div></div></div>
        <div class="card">
          <div class="card-head"><div><h3>Automation</h3><p>Runs while YC Scout is open</p></div></div>
          <div class="card-body">
            <div class="settings-row"><div><div class="t">Auto-sync new companies</div><div class="d">Re-pull the batches below on a schedule to catch new companies and job posts</div></div><label class="switch"><input type="checkbox" id="a-sync" ${settings.auto_sync_enabled ? "checked" : ""}><span></span></label></div>
            <div class="settings-row"><div class="t">Every</div><div class="row"><input class="input" id="a-hours" type="number" min="1" style="width:80px" value="${settings.auto_sync_hours}"><span class="muted">hours</span></div></div>
            <div class="settings-row"><div><div class="t">Batches</div><div class="d">Leave empty to always use the 2 newest</div></div>
            </div>
            <div class="row" style="flex-wrap:wrap;gap:6px;padding:0 0 12px;border-bottom:1px solid var(--border)">${batches.filter((b) => b.count >= 20).slice(0, 6).map((b) => `<span class="chip ${(settings.auto_sync_batches || []).includes(b.slug) ? "on" : ""}" data-ab="${b.slug}" style="height:28px">${esc(b.name)}</span>`).join("")}</div>
            <div class="settings-row"><div><div class="t">Research new companies with AI</div><div class="d">${ai ? "Runs during scheduled syncs" : "Needs GEMINI_API_KEY"}</div></div><label class="switch"><input type="checkbox" id="a-research" ${settings.auto_research_new ? "checked" : ""} ${ai ? "" : "disabled"}><span></span></label></div>
            <div class="settings-row"><div><div class="t">Auto-send follow-ups</div><div class="d">Follow-ups for unanswered emails after ${settings.followup_after_days} days. First emails always need your approval.</div></div><label class="switch"><input type="checkbox" id="a-follow" ${settings.auto_followups ? "checked" : ""}><span></span></label></div>
            <div class="settings-row"><div><div class="t">Update Google Sheet after each run</div><div class="d">${state.status?.integrations.sheets.ok ? "Connected" : "Configure in .env to enable"}</div></div><label class="switch"><input type="checkbox" id="a-sheet" ${settings.auto_sheet_sync ? "checked" : ""}><span></span></label></div>
            <div class="row" style="margin-top:12px"><button class="btn" id="a-save">Save automation</button></div>
          </div>
        </div>
      </div>
    </div>`;

  const est = () => {
    const n = batches.filter((b) => $(`[data-batch="${b.slug}"]`)?.checked).reduce((a, b) => a + b.count, 0);
    $("#sync-est").textContent = n ? `${fmt(n)} companies · about ${Math.max(1, Math.round(n / 75))}–${Math.max(2, Math.round(n / 45))} min` : "";
  };
  $$("[data-batch]").forEach((cb) => (cb.onchange = est));
  est();
  $("#run-sync").onclick = (e) => withLoading(e.currentTarget, async () => {
    const chosen = $$("[data-batch]").filter((x) => x.checked).map((x) => x.dataset.batch);
    if (!chosen.length) return toast("Pick at least one batch", "error");
    const r = await api("/api/runs/sync", { method: "POST", body: { batches: chosen, crawl: $("#opt-crawl").checked, research: $("#opt-research").checked, force: $("#opt-force").checked } });
    toast("Sync started");
    await renderPipeline(root);
    showLog(r.run_id);
    pollStatus();
  });
  $$("[data-ab]").forEach((chip) => (chip.onclick = () => chip.classList.toggle("on")));
  $$("[data-run]").forEach((tr) => (tr.onclick = (e) => { if (!e.target.closest("[data-cancel]")) showLog(+tr.dataset.run); }));
  $$("[data-cancel]").forEach((b) => (b.onclick = () => withLoading(b, async () => { await api(`/api/runs/${b.dataset.cancel}/cancel`, { method: "POST" }); toast("Cancelling…"); })));
  $("#log-close").onclick = () => { $("#log-card").hidden = true; clearInterval(state.runPoll); state.runPoll = null; };
  $("#a-save").onclick = (e) => withLoading(e.currentTarget, async () => {
    await api("/api/settings", { method: "PUT", body: {
      auto_sync_enabled: $("#a-sync").checked, auto_sync_hours: +$("#a-hours").value || 24,
      auto_sync_batches: $$("[data-ab].on").map((o) => o.dataset.ab),
      auto_research_new: $("#a-research").checked, auto_followups: $("#a-follow").checked, auto_sheet_sync: $("#a-sheet").checked,
    } });
    toast("Automation saved");
  });
  const running = runs.find((r) => r.status === "running");
  if (running) showLog(running.id);
}

function showLog(id) {
  const card = $("#log-card");
  if (!card) return;
  card.hidden = false;
  if (state.runPoll) clearInterval(state.runPoll);
  let lastStatus = null;
  const tick = async () => {
    try {
      const r = await api(`/api/runs/${id}`);
      if (!$("#log")) { clearInterval(state.runPoll); return; }
      $("#log-title").textContent = r.label || r.kind;
      $("#log-sub").innerHTML = `${statusBadge(r.status)} ${r.total ? `${r.progress}/${r.total}` : ""} ${r.summary ? "· " + esc(r.summary) : ""}`;
      const log = $("#log");
      const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
      log.textContent = r.log || "Starting…";
      if (atBottom) log.scrollTop = log.scrollHeight;
      if (r.status !== "running") {
        clearInterval(state.runPoll); state.runPoll = null;
        if (lastStatus === "running") { toast(`${r.label}: ${r.summary || r.status}`, r.status === "failed" ? "error" : ""); renderPipeline($("#content")); pollStatus(); }
      }
      lastStatus = r.status;
    } catch { /* ignore transient */ }
  };
  tick();
  state.runPoll = setInterval(tick, 1500);
}

// ---------------------------------------------------------------------------
// Agent (streamed chat with thinking + tool steps)
// ---------------------------------------------------------------------------
const SUGGESTIONS = [
  { icon: "spark", text: "Which companies fit me best and are hiring remotely?" },
  { icon: "mail", text: "Draft emails to my top 5 fits that haven't been contacted yet." },
  { icon: "search", text: "Find AI agent startups in Fall 2026 with teams under 5." },
  { icon: "refresh", text: "Research my 10 best-fit companies for funding and verified emails." },
];
const MARK = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5c.5 4.6 2.4 6.9 7 7.5-4.6.6-6.5 2.9-7 7.5-.5-4.6-2.4-6.9-7-7.5 4.6-.6 6.5-2.9 7-7.5Z"/><path d="M19 15.5c.2 1.8 1 2.7 2.8 3-1.8.3-2.6 1.2-2.8 3-.2-1.8-1-2.7-2.8-3 1.8-.3 2.6-1.2 2.8-3Z" opacity=".55"/></svg>`;
const STOP = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`;
const CHEVRON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>`;

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

async function renderAgent(root) {
  const a = state.agent;
  const ai = state.status?.integrations.ai;
  $("#page-actions").innerHTML = `<button class="btn" id="ag-new">${icon("plus")}New chat</button>`;
  $("#ag-new").onclick = () => newChat();
  if (!ai?.ok) {
    root.innerHTML = `<div class="card"><div class="empty" style="padding:56px 20px"><h3>The agent needs Gemini</h3><p>Add <span class="mono">GEMINI_API_KEY</span> to the <span class="mono">.env</span> file in the project folder and restart YC Scout.</p><a class="btn" href="#/settings">Open settings</a></div></div>`;
    return;
  }
  const name = state.status?.sender_first_name;
  root.innerHTML = `
    <div class="ag">
      <aside class="ag-side">
        <div class="ag-side-head">
          <div class="ag-search">${icon("search")}<input id="ag-filter" placeholder="Search chats" autocomplete="off"></div>
        </div>
        <div class="ag-list" id="ag-list"></div>
        <div class="ag-side-foot">
          <button class="ag-foot-btn" id="ag-memory">${icon("memory")}<span>Memory</span><span class="ag-count" id="ag-mem-count"></span></button>
          <button class="ag-foot-btn danger" id="ag-clear">${icon("trash")}<span>Delete all chats</span></button>
        </div>
      </aside>
      <div class="cx ${a.messages.length ? "" : "cx-empty"}" id="cx">
        <div class="cx-log" id="cx-log"><div class="cx-col" id="cx-col"></div></div>
        <div class="cx-dock">
          <div class="cx-hero"><span class="cx-mark">${MARK}</span><h2>${greeting()}${name ? ", " + esc(name) : ""}</h2></div>
          <form class="cx-composer" id="cx-form">
            <textarea id="cx-input" rows="1" placeholder="How can I help you today?" autocomplete="off"></textarea>
            <div class="cx-bar">
              <span class="cx-model" title="Model">${MARK}${esc(ai.model || "Gemini")}</span>
              <span class="grow"></span>
              <button type="submit" class="cx-send" id="cx-send" aria-label="Send" disabled>${icon("arrowUp")}</button>
            </div>
          </form>
          <div class="cx-chips">${SUGGESTIONS.map((s, i) => `<button class="cx-chip" data-s="${i}">${icon(s.icon)}${esc(s.text)}</button>`).join("")}</div>
          <p class="cx-note">The agent works on your YC Scout data and can make mistakes. Emails are only sent after you confirm.</p>
        </div>
      </div>
    </div>`;
  const input = $("#cx-input"), send = $("#cx-send");
  const sync = () => {
    input.style.height = "auto";
    input.style.height = Math.min(220, input.scrollHeight) + "px";
    if (!a.streaming) send.disabled = !input.value.trim();
  };
  input.oninput = sync;
  input.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#cx-form").requestSubmit(); } };
  $("#cx-form").onsubmit = (e) => {
    e.preventDefault();
    if (a.streaming) { a.ctrl?.abort(); return; }
    const t = input.value.trim();
    if (!t) return;
    input.value = ""; sync();
    sendAgent(t);
  };
  $$("[data-s]", root).forEach((b) => (b.onclick = () => sendAgent(SUGGESTIONS[+b.dataset.s].text)));
  $("#ag-filter").oninput = () => paintSide();
  $("#ag-memory").onclick = () => openMemory();
  $("#ag-clear").onclick = () => deleteAllChats();
  paintChat(true);
  setSendState();
  input.focus();
  await loadChats();
  refreshMemoryCount();
}

async function loadChats() {
  try { state.agent.chats = await api("/api/chats"); } catch { state.agent.chats = state.agent.chats || []; }
  paintSide();
}

function chatGroup(iso) {
  const d = new Date(iso), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  return diff <= 0 ? "Today" : diff === 1 ? "Yesterday" : diff <= 7 ? "Previous 7 days" : diff <= 30 ? "Previous 30 days" : "Older";
}

function paintSide() {
  const a = state.agent, list = $("#ag-list");
  if (!list) return;
  const q = ($("#ag-filter")?.value || "").trim().toLowerCase();
  const chats = (a.chats || []).filter((c) => !q || (c.title || "").toLowerCase().includes(q));
  if (!chats.length) {
    list.innerHTML = `<div class="ag-empty">${q ? "No chats match." : "Your chats will appear here."}</div>`;
    return;
  }
  let html = "", last = "";
  for (const c of chats) {
    const g = chatGroup(c.updated_at || c.created_at);
    if (g !== last) { html += `<div class="ag-group">${g}</div>`; last = g; }
    html += `<div class="ag-item ${c.id === a.session ? "active" : ""}" data-chat="${esc(c.id)}" title="${esc(c.title || "")}">
      <span class="ag-title">${esc(c.title || "Untitled chat")}</span>
      <span class="ag-acts"><button class="ag-act" data-rename="${esc(c.id)}" title="Rename">${icon("edit")}</button><button class="ag-act" data-del="${esc(c.id)}" title="Delete">${icon("trash")}</button></span>
    </div>`;
  }
  list.innerHTML = html;
  $$("[data-chat]", list).forEach((el) => (el.onclick = (e) => { if (!e.target.closest(".ag-act, input")) openChat(el.dataset.chat); }));
  $$("[data-rename]", list).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); renameChat(b.dataset.rename); }));
  $$("[data-del]", list).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); deleteChat(b.dataset.del); }));
}

function busyGuard() {
  if (state.agent.streaming) { toast("Wait for the answer to finish, or press Stop first."); return true; }
  return false;
}

function newChat() {
  if (busyGuard()) return;
  const a = state.agent;
  a.session = null; a.messages = [];
  paintChat(true); paintSide(); setSendState();
  $("#cx-input")?.focus();
}

async function openChat(id) {
  const a = state.agent;
  if (a.session === id || busyGuard()) return;
  try {
    const c = await api(`/api/chats/${encodeURIComponent(id)}`);
    a.session = c.id;
    a.messages = (c.messages || []).map((m) => (m.role === "user" ? m : { ...m, streaming: false }));
    paintChat(true); paintSide(); setSendState();
    $("#cx-input")?.focus();
  } catch (e) { toast(e.message, "error"); }
}

function renameChat(id) {
  const el = $(`[data-chat="${CSS.escape(id)}"] .ag-title`);
  const chat = (state.agent.chats || []).find((c) => c.id === id);
  if (!el || !chat) return;
  const inp = document.createElement("input");
  inp.className = "ag-rename"; inp.value = chat.title || ""; inp.maxLength = 120;
  el.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    const title = inp.value.trim();
    if (save && title && title !== chat.title) {
      try { await api(`/api/chats/${encodeURIComponent(id)}`, { method: "PATCH", body: { title } }); chat.title = title; } catch (e) { toast(e.message, "error"); }
    }
    paintSide();
  };
  inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); finish(true); } else if (e.key === "Escape") finish(false); };
  inp.onblur = () => finish(true);
  inp.onclick = (e) => e.stopPropagation();
}

async function deleteChat(id) {
  const a = state.agent;
  const chat = (a.chats || []).find((c) => c.id === id);
  if (a.streaming && a.session === id) return busyGuard();
  const ok = await confirmModal({ title: "Delete chat?", body: `<p>This permanently deletes <b>${esc(chat?.title || "this chat")}</b>. Memories it saved stay until you delete them in Memory.</p>`, confirm: "Delete", danger: true });
  if (!ok) return;
  try {
    await api(`/api/chats/${encodeURIComponent(id)}`, { method: "DELETE" });
    a.chats = (a.chats || []).filter((c) => c.id !== id);
    if (a.session === id) { a.session = null; a.messages = []; paintChat(true); setSendState(); }
    paintSide();
    toast("Chat deleted");
  } catch (e) { toast(e.message, "error"); }
}

async function deleteAllChats() {
  const a = state.agent;
  if (busyGuard()) return;
  if (!(a.chats || []).length) return toast("No chats to delete.");
  const ok = await confirmModal({ title: "Delete all chats?", body: `<p>This permanently deletes all ${plural(a.chats.length, "chat")}. Your memory is kept; clear it separately in Memory.</p>`, confirm: "Delete all", danger: true });
  if (!ok) return;
  try {
    await api("/api/chats", { method: "DELETE" });
    a.chats = []; a.session = null; a.messages = [];
    paintChat(true); paintSide(); setSendState();
    toast("All chats deleted");
  } catch (e) { toast(e.message, "error"); }
}

async function refreshMemoryCount() {
  try {
    const m = await api("/api/memories");
    const el = $("#ag-mem-count");
    if (el) { el.textContent = m.enabled ? (m.items.length || "") : "off"; el.classList.toggle("off", !m.enabled); }
  } catch { /* ignore */ }
}

async function openMemory() {
  let data;
  try { data = await api("/api/memories"); } catch (e) { return toast(e.message, "error"); }
  const paint = (m) => {
    const items = m.items.map((x) => `<div class="mem-row"><span class="grow">${esc(x.text)}</span><span class="badge ${x.source === "you" ? "b-blue" : ""}">${x.source === "you" ? "added by you" : "learned"}</span><button class="btn btn-ghost btn-sm btn-icon" data-mdel="${x.id}" title="Delete">${icon("trash")}</button></div>`).join("");
    return `
      <div class="modal-head"><h3>Memory</h3><p>What the agent remembers about you across chats. It uses these quietly to tailor answers and emails.</p></div>
      <div class="modal-body">
        <label class="mem-toggle"><span><b>Use memory</b><br><span class="muted">When off, the agent neither reads nor saves memories.</span></span><span class="switch"><input type="checkbox" id="mem-on" ${m.enabled ? "checked" : ""}><span></span></span></label>
        <div class="mem-list">${items || '<div class="ag-empty" style="padding:14px 4px">Nothing saved yet. Tell the agent things like "I only want remote roles open to India" and it will remember.</div>'}</div>
        <form class="row" id="mem-add"><input class="input grow" name="text" placeholder="Add something to remember" maxlength="400" autocomplete="off"><button class="btn" type="submit">${icon("plus")}Add</button></form>
      </div>
      <div class="modal-foot"><button class="btn btn-danger" id="mem-clear" ${m.items.length ? "" : "disabled"}>Clear all memory</button><span class="grow"></span><button class="btn btn-primary" id="mem-close">Done</button></div>`;
  };
  const mount = (modal) => {
    $("#mem-close", modal).onclick = () => { closeModal(); refreshMemoryCount(); };
    $("#mem-on", modal).onchange = async (e) => {
      try { data.enabled = (await api("/api/memories/enabled", { method: "PUT", body: { enabled: e.target.checked } })).enabled; } catch (err) { toast(err.message, "error"); }
      refreshMemoryCount();
    };
    $$("[data-mdel]", modal).forEach((b) => (b.onclick = async () => {
      await api(`/api/memories/${b.dataset.mdel}`, { method: "DELETE" });
      data = await api("/api/memories"); rerender();
    }));
    $("#mem-add", modal).onsubmit = async (e) => {
      e.preventDefault();
      const text = new FormData(e.target).get("text").trim();
      if (!text) return;
      try { await api("/api/memories", { method: "POST", body: { text } }); data = await api("/api/memories"); rerender(); } catch (err) { toast(err.message, "error"); }
    };
    $("#mem-clear", modal).onclick = async () => {
      if (!window.confirm("Delete every memory? This can't be undone.")) return;
      await api("/api/memories", { method: "DELETE" });
      data = await api("/api/memories"); rerender();
    };
  };
  const rerender = () => { $("#modal").innerHTML = paint(data); hydrateIcons($("#modal")); mount($("#modal")); refreshMemoryCount(); };
  openModal(paint(data), mount);
}

function setSendState() {
  const a = state.agent, send = $("#cx-send");
  if (!send) return;
  if (a.streaming) { send.innerHTML = STOP; send.disabled = false; send.classList.add("stop"); send.setAttribute("aria-label", "Stop"); }
  else { send.innerHTML = icon("arrowUp"); send.classList.remove("stop"); send.setAttribute("aria-label", "Send"); send.disabled = !$("#cx-input")?.value.trim(); }
}

function thinkTitle(text) {
  const heads = [...String(text || "").matchAll(/\*\*([^*\n]{3,80})\*\*/g)];
  return heads.length ? heads[heads.length - 1][1] : "";
}

function renderBlock(b, i, m) {
  if (b.kind === "thinking") {
    const live = !b.t1;
    const secs = Math.max(1, Math.round(((b.t1 || Date.now()) - b.t0) / 1000));
    const label = live ? `<span class="shimmer">${esc(thinkTitle(b.text) || "Thinking")}</span>` : `Thought for ${secs}s`;
    const open = live || b.open;
    return `<div class="cx-think ${open ? "open" : ""}">
      <button class="cx-think-head" data-think="${i}">${label}<span class="cx-chev">${CHEVRON}</span></button>
      ${open ? `<div class="cx-think-body">${md(b.text)}</div>` : ""}
    </div>`;
  }
  if (b.kind === "tool") {
    const st = !b.done ? "run" : b.ok ? "ok" : "err";
    const ic = st === "run" ? '<span class="spin"></span>' : st === "ok" ? icon("check") : icon("close");
    return `<div class="cx-tool ${st}" title="${esc(JSON.stringify(b.input || {}))}"><span class="cx-tool-ic">${ic}</span><span class="cx-tool-label">${esc(b.label)}</span>${b.summary ? `<span class="cx-tool-sum">${esc(b.summary)}</span>` : ""}</div>`;
  }
  const isLast = i === m.blocks.length - 1;
  return `<div class="cx-prose">${md(b.text)}${m.streaming && isLast ? '<span class="cx-caret"></span>' : ""}</div>`;
}

function botHtml(m, idx) {
  const blocks = m.blocks || [];
  const busy = m.streaming && (!blocks.length || (blocks[blocks.length - 1].kind === "tool" && blocks[blocks.length - 1].done));
  const textOut = blocks.filter((b) => b.kind === "text").map((b) => b.text).join("\n\n").trim();
  const drafted = blocks.some((b) => b.kind === "tool" && b.name === "draft_emails" && b.ok);
  const foot = !m.streaming ? `<div class="cx-actions">
      ${textOut ? `<button class="cx-act" data-copy="${idx}" title="Copy">${icon("copy")}</button>` : ""}
      ${(m.runs || []).length ? `<a class="btn btn-sm" href="#/pipeline">${icon("refresh")}Watch ${plural(m.runs.length, "job")}</a>` : ""}
      ${drafted ? `<a class="btn btn-sm" href="#/outreach">${icon("mail")}Review drafts</a>` : ""}
      ${m.stopped ? '<span class="faint" style="font-size:12px">Stopped</span>' : ""}
    </div>` : "";
  return `<div class="cx-msg cx-bot" data-msg="${idx}">
    <div class="cx-avatar ${m.streaming ? "live" : ""}">${MARK}</div>
    <div class="cx-body">
      ${blocks.map((b, i) => renderBlock(b, i, m)).join("")}
      ${busy ? `<div class="cx-pending"><span class="shimmer">${blocks.length ? "Working" : "Thinking"}</span></div>` : ""}
      ${m.error ? `<div class="cx-error">${esc(m.error)}</div>` : ""}
      ${m.confirm && m.confirm.count ? `<div class="callout" style="margin-top:4px"><div class="row"><span class="grow">Ready to send <b>${plural(m.confirm.count, "approved email")}</b>.</span><button class="btn btn-accent btn-sm" data-confirm-send>${icon("send")}Confirm and send</button></div></div>` : ""}
      ${foot}
    </div>
  </div>`;
}

function paintChat(full = false) {
  const a = state.agent;
  const col = $("#cx-col"), log = $("#cx-log");
  if (!col) return;
  $("#cx")?.classList.toggle("cx-empty", !a.messages.length);
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 140;
  if (full || col.children.length !== a.messages.length) {
    col.innerHTML = a.messages.map((m, i) => m.role === "user" ? `<div class="cx-msg cx-user"><div class="cx-bubble">${esc(m.text)}</div></div>` : botHtml(m, i)).join("");
  } else {
    const i = a.messages.length - 1, m = a.messages[i];
    if (m && m.role !== "user") col.lastElementChild.outerHTML = botHtml(m, i);
  }
  bindChat(col);
  if (full || nearBottom) log.scrollTop = log.scrollHeight;
}

function bindChat(col) {
  const a = state.agent;
  $$("[data-think]", col).forEach((b) => (b.onclick = () => {
    const m = a.messages[+b.closest("[data-msg]").dataset.msg];
    const blk = m.blocks[+b.dataset.think];
    if (blk.t1) { blk.open = !blk.open; paintChat(true); }
  }));
  $$("[data-copy]", col).forEach((b) => (b.onclick = async () => {
    const m = a.messages[+b.dataset.copy];
    const txt = m.blocks.filter((x) => x.kind === "text").map((x) => x.text).join("\n\n").trim();
    try { await navigator.clipboard.writeText(txt); b.innerHTML = icon("check"); setTimeout(() => (b.innerHTML = icon("copy")), 1400); } catch { toast("Couldn't copy", "error"); }
  }));
  $$("[data-confirm-send]", col).forEach((b) => (b.onclick = () => withLoading(b, async () => { await api("/api/runs/send", { method: "POST" }); toast("Sending started"); location.hash = "#/pipeline"; })));
}

let paintQueued = false;
function schedulePaint() {
  if (paintQueued) return;
  paintQueued = true;
  requestAnimationFrame(() => { paintQueued = false; paintChat(); });
}

async function sendAgent(text) {
  const a = state.agent;
  if (a.streaming) return;
  const m = { role: "bot", blocks: [], streaming: true };
  a.messages.push({ role: "user", text }, m);
  a.streaming = true;
  a.ctrl = new AbortController();
  paintChat(true);
  setSendState();
  const closeThinking = () => { const l = m.blocks[m.blocks.length - 1]; if (l && l.kind === "thinking" && !l.t1) l.t1 = Date.now(); };
  const handle = (ev) => {
    if (ev.type === "session") {
      a.session = ev.session_id;
      const now = new Date().toISOString();
      const ex = (a.chats || []).find((c) => c.id === ev.session_id);
      if (ex) { ex.updated_at = now; a.chats = [ex, ...a.chats.filter((c) => c !== ex)]; }
      else a.chats = [{ id: ev.session_id, title: ev.title, created_at: now, updated_at: now }, ...(a.chats || [])];
      paintSide();
    }
    else if (ev.type === "thinking") {
      const l = m.blocks[m.blocks.length - 1];
      if (l && l.kind === "thinking" && !l.t1) l.text += ev.text; else m.blocks.push({ kind: "thinking", text: ev.text, t0: Date.now() });
    } else if (ev.type === "text") {
      closeThinking();
      const l = m.blocks[m.blocks.length - 1];
      if (l && l.kind === "text") l.text += ev.text; else m.blocks.push({ kind: "text", text: ev.text });
    } else if (ev.type === "tool_start") {
      closeThinking();
      m.blocks.push({ kind: "tool", id: ev.id, name: ev.name, label: ev.label, input: ev.input });
    } else if (ev.type === "tool_end") {
      const t = m.blocks.find((b) => b.kind === "tool" && b.id === ev.id);
      if (t) Object.assign(t, { done: true, ok: ev.ok, summary: ev.summary });
    } else if (ev.type === "runs") { m.runs = ev.runs; pollStatus(); }
    else if (ev.type === "confirm") { m.confirm = ev; }
    else if (ev.type === "error") { m.error = ev.message; }
    else if (ev.type === "done") { if (ev.changed) pollStatus(); if (ev.memory_changed) refreshMemoryCount(); }
    schedulePaint();
  };
  try {
    const res = await fetch("/api/agent/stream", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: a.session, message: text }), signal: a.ctrl.signal,
    });
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      throw new Error(detail);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, cut); buf = buf.slice(cut + 2);
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) { try { handle(JSON.parse(line.slice(6))); } catch { /* partial line */ } }
        }
      }
    }
  } catch (e) {
    if (e.name === "AbortError") m.stopped = true;
    else m.error = e.message === "Failed to fetch" ? "Can't reach the YC Scout server. Is it still running?" : e.message;
  } finally {
    closeThinking();
    for (const b of m.blocks) if (b.kind === "tool" && !b.done) Object.assign(b, { done: true, ok: false, summary: "stopped" });
    if (!m.blocks.some((b) => b.kind === "text") && !m.error && !m.stopped) m.blocks.push({ kind: "text", text: "Done." });
    m.streaming = false;
    a.streaming = false;
    a.ctrl = null;
    paintChat();
    setSendState();
  }
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
async function renderSettings(root) {
  const [s, st, supp] = await Promise.all([api("/api/settings"), api("/api/status"), api("/api/suppression")]);
  const names = { ai: ["Gemini AI", "Research, personalized emails and the agent"], smtp: ["Email sending (SMTP)", "Sends approved emails from your mailbox"], imap: ["Reply tracking (IMAP)", "Detects replies and bounces, stops follow-ups"], sheets: ["Google Sheets", "Mirrors every table to your spreadsheet"] };
  const VARS = ["first_name", "full_name", "company", "one_liner", "batch", "batch_full", "website", "location", "job_title", "hiring_line", "proof_line", "open_roles", "sender_name"];
  root.innerHTML = `
    <div class="grid grid-2">
      <div class="stack">
        <div class="card"><div class="card-head"><div><h3>Integrations</h3><p>Keys live in the <span class="mono">.env</span> file. Restart after editing.</p></div></div>
          <div class="card-body">${Object.entries(st.integrations).map(([k, v]) => `
            <div class="settings-row"><div class="row" style="align-items:flex-start"><span class="dot ${v.ok ? "on" : "off"}" style="margin-top:6px"></span><div><div class="t">${names[k][0]}</div><div class="d">${esc(names[k][1])}</div><div class="d mono" style="font-size:11.5px">${esc(v.detail)}</div></div></div>
            ${k !== "imap" ? `<button class="btn btn-sm" data-test="${k}" ${v.ok ? "" : "disabled"}>${k === "sheets" ? "Sync now" : "Test"}</button>` : ""}</div>`).join("")}
          </div></div>

        <div class="card"><div class="card-head"><div><h3>About you</h3><p>The AI writes every email from this. Be specific: who you are, what you offer, proof.</p></div></div>
          <div class="card-body stack">
            <div class="field"><label>Sender profile</label><textarea class="textarea" id="s-profile" rows="8">${esc(s.sender_profile)}</textarea></div>
            <div class="field"><label>Goal of your outreach</label><input class="input" id="s-goal" value="${esc(s.outreach_goal)}"><span class="hint">e.g. "Get an interview for a founding engineer role" or "Book a 15-min demo of our design service"</span></div>
            <div class="field"><label>Tone</label><input class="input" id="s-tone" value="${esc(s.email_tone)}"></div>
          </div></div>

        <div class="card"><div class="card-head"><div><h3>Your strengths</h3><p>Scores every company 0–100 for fit and picks the proof line for each email</p></div></div>
          <div class="card-body stack">
            <div class="field"><label>Strengths <span class="faint">(one per line: keywords =&gt; proof line)</span></label><textarea class="textarea mono" id="s-strengths" rows="10" style="font-size:12px">${esc(s.fit_strengths)}</textarea><span class="hint">If a company's description, tags or job titles mention a keyword, it scores higher and <span class="mono">{{proof_line}}</span> becomes that line.</span></div>
            <div class="field"><label>Default proof line</label><input class="input" id="s-proof" value="${esc(s.default_proof_line)}"><span class="hint">Used when no strength matches</span></div>
          </div></div>

        <div class="card"><div class="card-head"><div><h3>Sending rules</h3><p>Protects your domain's reputation and keeps outreach respectful</p></div></div>
          <div class="card-body">
            <div class="settings-row"><div><div class="t">Daily send limit</div><div class="d">New Gmail accounts: stay under 50/day</div></div><input class="input" id="s-limit" type="number" style="width:90px" value="${s.daily_send_limit}"></div>
            <div class="settings-row"><div><div class="t">Delay between emails</div><div class="d">Seconds</div></div><input class="input" id="s-delay" type="number" style="width:90px" value="${s.send_delay_seconds}"></div>
            <div class="settings-row"><div><div class="t">Follow up after</div><div class="d">Days without a reply</div></div><input class="input" id="s-fdays" type="number" style="width:90px" value="${s.followup_after_days}"></div>
            <div class="settings-row"><div><div class="t">Max follow-ups</div><div class="d">Per recipient</div></div><input class="input" id="s-fmax" type="number" style="width:90px" value="${s.max_followups}"></div>
            <div class="field" style="margin-top:10px"><label>Footer line</label><input class="input" id="s-footer" value="${esc(s.signature_footer)}"><span class="hint">Appended to every email. Keep an easy opt-out.</span></div>
            <div class="field" style="margin-top:10px"><label>Mailing address <span class="faint">(required by CAN-SPAM for commercial email)</span></label><input class="input" id="s-address" value="${esc(s.physical_address)}"></div>
          </div></div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-head"><div><h3>First email template</h3><p>Used when you pick "My template" or when AI is off</p></div></div>
          <div class="card-body stack">
            <div class="field"><label>Subject</label><input class="input" id="s-tsub" value="${esc(s.template_subject)}"></div>
            <div class="field"><label>Body</label><textarea class="textarea" id="s-tbody" rows="10">${esc(s.template_body)}</textarea></div>
            <div class="field"><label>Variables <span class="faint">(click to insert)</span></label><div class="var-list">${VARS.map((v) => `<code data-var="${v}">{{${v}}}</code>`).join("")}</div></div>
          </div></div>
        <div class="card"><div class="card-head"><div><h3>Follow-up template</h3><p>Sent in the same thread. <span class="mono">{{original_subject}}</span> is available.</p></div></div>
          <div class="card-body stack">
            <div class="field"><label>Subject</label><input class="input" id="s-fsub" value="${esc(s.followup_subject)}"></div>
            <div class="field"><label>Body</label><textarea class="textarea" id="s-fbody" rows="6">${esc(s.followup_body)}</textarea></div>
          </div></div>
        <div class="card"><div class="card-head"><div><h3>Do-not-contact list</h3><p>Opt-outs and bounces. These addresses are never emailed.</p></div></div>
          <div class="card-body stack">
            <form class="row" id="supp-form"><input class="input grow mono" name="email" placeholder="name@company.com"><button class="btn" type="submit">${icon("plus")}Add</button></form>
            <div class="email-list">${supp.map((x) => `<div class="email-row"><span class="mono grow">${esc(x.email)}</span><span class="badge">${esc(x.reason)}</span><button class="btn btn-ghost btn-sm btn-icon" data-unsupp="${esc(x.email)}" title="Remove">${icon("trash")}</button></div>`).join("") || '<span class="faint">Empty</span>'}</div>
          </div></div>
      </div>
    </div>
    <div style="position:sticky;bottom:0;padding:14px 0;background:linear-gradient(transparent, var(--bg) 40%);display:flex;justify-content:flex-end"><button class="btn btn-primary" id="s-save">Save settings</button></div>`;

  let lastField = $("#s-tbody");
  ["#s-tsub", "#s-tbody", "#s-fsub", "#s-fbody"].forEach((id) => $(id).addEventListener("focus", (e) => (lastField = e.target)));
  $$("[data-var]").forEach((el) => (el.onclick = () => {
    const f = lastField, token = `{{${el.dataset.var}}}`;
    const at = f.selectionStart ?? f.value.length;
    f.value = f.value.slice(0, at) + token + f.value.slice(f.selectionEnd ?? at);
    f.focus(); f.selectionStart = f.selectionEnd = at + token.length;
  }));
  $$("[data-test]").forEach((b) => (b.onclick = () => withLoading(b, async () => { const r = await api(`/api/test/${b.dataset.test}`, { method: "POST" }); toast(r.detail); })));
  $("#s-save").onclick = (e) => withLoading(e.currentTarget, async () => {
    await api("/api/settings", { method: "PUT", body: {
      sender_profile: $("#s-profile").value, outreach_goal: $("#s-goal").value, email_tone: $("#s-tone").value,
      fit_strengths: $("#s-strengths").value, default_proof_line: $("#s-proof").value,
      daily_send_limit: +$("#s-limit").value, send_delay_seconds: +$("#s-delay").value, followup_after_days: +$("#s-fdays").value,
      max_followups: +$("#s-fmax").value, signature_footer: $("#s-footer").value, physical_address: $("#s-address").value,
      template_subject: $("#s-tsub").value, template_body: $("#s-tbody").value, followup_subject: $("#s-fsub").value, followup_body: $("#s-fbody").value,
    } });
    toast("Settings saved");
  });
  $("#supp-form").onsubmit = (e) => { e.preventDefault(); const em = new FormData(e.target).get("email"); withLoading(null, async () => { await api("/api/suppression", { method: "POST", body: { email: em } }); toast("Added to do-not-contact"); renderSettings(root); }); };
  $$("[data-unsupp]").forEach((b) => (b.onclick = () => withLoading(b, async () => { await api(`/api/suppression/${encodeURIComponent(b.dataset.unsupp)}`, { method: "DELETE" }); renderSettings(root); })));
}

// ---------------------------------------------------------------------------
// Theme (System / Light / Dark), remembered per browser
// ---------------------------------------------------------------------------
const THEME_KEY = "ycscout-theme";
function getTheme() { try { return localStorage.getItem(THEME_KEY) || "system"; } catch { return "system"; } }
function applyTheme(t) {
  const root = document.documentElement;
  if (t === "light" || t === "dark") root.dataset.theme = t; else delete root.dataset.theme;
  $$("#theme-switch [data-theme-set]").forEach((b) => b.classList.toggle("on", b.dataset.themeSet === t));
}
function setTheme(t) {
  try { localStorage.setItem(THEME_KEY, t); } catch { /* private mode: still applies for this visit */ }
  applyTheme(t);
}
function mountThemeSwitch() {
  const host = $("#theme-switch");
  if (!host) return;
  const opts = [["system", "monitor", "System"], ["light", "sun", "Light"], ["dark", "moon", "Dark"]];
  host.innerHTML = opts.map(([v, ic, label]) => `<button type="button" data-theme-set="${v}" title="${label}" aria-label="${label} theme">${icon(ic)}</button>`).join("");
  $$("[data-theme-set]", host).forEach((b) => (b.onclick = () => setTheme(b.dataset.themeSet)));
  applyTheme(getTheme());
}

// ---------------------------------------------------------------------------
// Dropdowns: every <select class="select"> gets a menu that matches the UI.
// The native <select> stays in the DOM as the source of truth, so forms,
// .value and change handlers keep working unchanged.
// ---------------------------------------------------------------------------
const DD_CHEV = `<svg class="dd-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>`;
const DD_CHECK = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>`;
let ddOpen = null;

function enhanceSelect(sel) {
  if (sel.dataset.dd) return;
  sel.dataset.dd = "1";
  const wrap = document.createElement("div");
  wrap.className = "dd";
  sel.parentNode.insertBefore(wrap, sel);
  wrap.appendChild(sel);
  sel.classList.add("dd-native");
  sel.tabIndex = -1;
  sel.setAttribute("aria-hidden", "true");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dd-btn";
  if (sel.getAttribute("style")) btn.setAttribute("style", sel.getAttribute("style"));
  btn.setAttribute("aria-haspopup", "listbox");
  btn.innerHTML = `<span class="dd-label"></span>${DD_CHEV}`;
  if (sel.title) btn.title = sel.title;
  wrap.appendChild(btn);
  const sync = () => {
    const o = sel.options[sel.selectedIndex];
    btn.querySelector(".dd-label").textContent = o ? o.textContent : "";
    btn.disabled = sel.disabled;
    btn.classList.toggle("is-placeholder", !!o && !o.value && /…$/.test(o.textContent));
  };
  sync();
  sel.addEventListener("change", sync);
  new MutationObserver(sync).observe(sel, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["disabled"] });
  btn.addEventListener("click", (e) => { e.stopPropagation(); ddOpen && ddOpen.sel === sel ? closeDD() : openDD(sel, btn); });
  btn.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); openDD(sel, btn); }
  });
}

function openDD(sel, btn) {
  closeDD();
  const opts = [...sel.options].map((o, i) => ({ i, label: o.textContent, value: o.value, disabled: o.disabled }));
  const menu = document.createElement("div");
  menu.className = "dd-menu";
  menu.setAttribute("role", "listbox");
  const searchable = opts.length > 10;
  menu.innerHTML = `${searchable ? `<div class="dd-search"><input type="text" placeholder="Search…" aria-label="Search options"></div>` : ""}<div class="dd-list"></div>`;
  document.body.appendChild(menu);
  const list = $(".dd-list", menu);
  const state = { sel, btn, menu, active: Math.max(0, sel.selectedIndex), shown: opts };
  ddOpen = state;
  btn.classList.add("open");
  btn.setAttribute("aria-expanded", "true");

  const paint = () => {
    list.innerHTML = state.shown.length ? state.shown.map((o, k) => `<div class="dd-opt ${o.i === sel.selectedIndex ? "sel" : ""} ${k === state.activeK ? "active" : ""} ${o.disabled ? "disabled" : ""}" role="option" data-k="${k}" aria-selected="${o.i === sel.selectedIndex}"><span class="dd-opt-label">${esc(o.label)}</span><span class="dd-tick">${o.i === sel.selectedIndex ? DD_CHECK : ""}</span></div>`).join("")
      : `<div class="dd-empty">No matches</div>`;
    const act = list.querySelector(".dd-opt.active");
    if (act) act.scrollIntoView({ block: "nearest" });
  };
  state.activeK = Math.max(0, state.shown.findIndex((o) => o.i === sel.selectedIndex));
  paint();

  const place = () => {
    const r = btn.getBoundingClientRect();
    const w = Math.max(r.width, 180);
    menu.style.minWidth = w + "px";
    const h = menu.offsetHeight;
    const below = window.innerHeight - r.bottom - 8;
    const top = below >= Math.min(h, 220) || r.top < h ? r.bottom + 4 : r.top - h - 4;
    menu.style.top = Math.max(8, top) + "px";
    menu.style.left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8) + "px";
  };
  place();
  requestAnimationFrame(() => menu.classList.add("in"));

  const choose = (k) => {
    const o = state.shown[k];
    if (!o || o.disabled) return;
    const changed = sel.selectedIndex !== o.i;
    sel.selectedIndex = o.i;
    closeDD();
    btn.focus();
    if (changed) sel.dispatchEvent(new Event("change", { bubbles: true }));
  };
  list.addEventListener("mousedown", (e) => e.preventDefault());
  list.addEventListener("click", (e) => { const el = e.target.closest(".dd-opt"); if (el) choose(+el.dataset.k); });
  list.addEventListener("mousemove", (e) => {
    const el = e.target.closest(".dd-opt");
    if (el && +el.dataset.k !== state.activeK) { state.activeK = +el.dataset.k; $$(".dd-opt", list).forEach((x) => x.classList.toggle("active", +x.dataset.k === state.activeK)); }
  });
  let typed = "", typedAt = 0;
  state.onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); closeDD(); btn.focus(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = state.shown.length;
      if (!n) return;
      state.activeK = (state.activeK + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
      paint();
      return;
    }
    if (e.key === "Enter") { e.preventDefault(); choose(state.activeK); return; }
    if (e.key === "Tab") { closeDD(); return; }
    if (!searchable && e.key.length === 1) {
      const now = Date.now();
      typed = (now - typedAt > 700 ? "" : typed) + e.key.toLowerCase();
      typedAt = now;
      const k = state.shown.findIndex((o) => o.label.toLowerCase().startsWith(typed));
      if (k >= 0) { state.activeK = k; paint(); }
    }
  };
  document.addEventListener("keydown", state.onKey, true);
  if (searchable) {
    const inp = $(".dd-search input", menu);
    inp.addEventListener("input", () => {
      const q = inp.value.trim().toLowerCase();
      state.shown = opts.filter((o) => o.label.toLowerCase().includes(q));
      state.activeK = 0;
      paint();
    });
    setTimeout(() => inp.focus(), 0);
  }
}

function closeDD() {
  if (!ddOpen) return;
  const { menu, btn, onKey } = ddOpen;
  document.removeEventListener("keydown", onKey, true);
  btn.classList.remove("open");
  btn.setAttribute("aria-expanded", "false");
  menu.remove();
  ddOpen = null;
}

function enhanceAll(root = document) {
  $$("select.select:not([data-dd])", root).forEach(enhanceSelect);
}

document.addEventListener("mousedown", (e) => { if (ddOpen && !ddOpen.menu.contains(e.target) && !ddOpen.btn.contains(e.target)) closeDD(); });
window.addEventListener("resize", closeDD);
document.addEventListener("scroll", (e) => { if (ddOpen && !ddOpen.menu.contains(e.target)) closeDD(); }, true);
window.addEventListener("hashchange", closeDD);
new MutationObserver((muts) => {
  for (const m of muts) for (const n of m.addedNodes) {
    if (n.nodeType !== 1) continue;
    if (n.matches?.("select.select")) enhanceSelect(n); else if (n.querySelector?.("select.select")) enhanceAll(n);
  }
}).observe(document.documentElement, { childList: true, subtree: true });

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
hydrateIcons();
mountThemeSwitch();
enhanceAll();
pollStatus().then(route);
setInterval(pollStatus, 6000);
