// Pages: home, patients, one patient, new test, test results, device check.

import { camera, mic, speak, stopCamera, stopSpeaking } from "./media.js";
import { abortTest, resultCardHtml, runTest } from "./runner.js";
import { age, api, avatar, band, config, esc, fmtDate, fmtDateTime, icon } from "./ui.js";

const view = document.getElementById("view");
const navigate = (hash) => { location.hash = hash; };

const routes = [
  [/^#?\/?$/, home],
  [/^#\/patients$/, patients],
  [/^#\/patient\/(\d+)$/, patientPage],
  [/^#\/new(?:\?patient=(\d+))?$/, newTest],
  [/^#\/run\/(\d+)$/, (id) => { document.body.classList.add("running"); return runTest(view, +id, navigate); }],
  [/^#\/session\/(\d+)$/, sessionPage],
  [/^#\/check$/, deviceCheck],
];

async function route() {
  abortTest();
  stopSpeaking();
  stopCamera();
  document.body.classList.remove("running");
  const hash = location.hash || "#/";
  document.querySelectorAll(".nav a").forEach((a) => {
    const target = a.getAttribute("href");
    const on = target === "#/" ? hash === "#/" || hash === "#"
      : target === "#/patients" ? /^#\/(patients|patient\/|session\/)/.test(hash)
      : hash.startsWith(target);
    a.classList.toggle("active", on);
  });
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      view.innerHTML = `<div class="loading"><div class="spinner"></div></div>`;
      try {
        await fn(...m.slice(1));
      } catch (e) {
        view.innerHTML = `<div class="page"><div class="card"><h2>Could not load this page</h2><p class="error-text">${esc(e.message)}</p></div></div>`;
      }
      window.scrollTo(0, 0);
      return;
    }
  }
  navigate("#/");
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- status pill
async function pollStatus() {
  const el = document.getElementById("speech-status");
  const set = (cls, text, title = "") => {
    el.className = "pill " + cls;
    el.querySelector("span").textContent = text;
    el.title = title;
  };
  try {
    const s = await api("/api/status");
    if (s.speech_ready) set("ok", "Speech ready");
    else if (s.speech_error) set("bad", "Speech error", s.speech_error);
    else { set("wait", "Loading speech…"); setTimeout(pollStatus, 2000); }
  } catch {
    set("bad", "App not running");
    setTimeout(pollStatus, 3000);
  }
}

// ---------------------------------------------------------------- pieces
function scoreBadge(s) {
  if (s.status !== "finished") return `<span class="tag brand">In progress</span>`;
  const b = band(s.adjusted_total, s.max_total);
  return `<span class="score-pill ${b ? b.cls : ""}">${s.adjusted_total}<small>/${s.max_total}</small></span>`;
}

function patientLine(p) {
  const a = age(p.date_of_birth);
  return [a != null ? `${a} yrs` : null, p.sex, p.education_years != null ? `${p.education_years} yrs education` : null]
    .filter(Boolean).map(esc).join(" · ");
}

function emptyState(ic, text) {
  return `<div class="empty"><div class="empty-icon">${icon(ic)}</div>${text}</div>`;
}

function searchBox(placeholder) {
  return `<div class="search-wrap">${icon("search")}<input class="search" placeholder="${esc(placeholder)}"></div>`;
}

function patientForm(p = {}) {
  return `<form class="form-grid" autocomplete="off">
      <label class="span2">Full name *<input name="name" required value="${esc(p.name || "")}" placeholder="e.g. Yamini Rao"></label>
      <label>Date of birth<input name="date_of_birth" type="date" value="${esc(p.date_of_birth || "")}"></label>
      <label>Sex<select name="sex">
        ${["", "Female", "Male", "Other"].map((o) => `<option ${p.sex === o ? "selected" : ""} value="${o}">${o || "—"}</option>`).join("")}
      </select></label>
      <label>Years of education<input name="education_years" type="number" min="0" max="40" value="${p.education_years ?? ""}" placeholder="e.g. 12"></label>
      <label class="span2">Notes<textarea name="notes" rows="2" placeholder="Optional">${esc(p.notes || "")}</textarea></label>
      <p class="hint span2">12 years of education or less adds 1 point to the final MoCA score.</p>
    </form>`;
}

function readPatientForm(form) {
  const f = new FormData(form);
  const edu = f.get("education_years");
  return { name: f.get("name").trim(), date_of_birth: f.get("date_of_birth") || null, sex: f.get("sex") || null,
           education_years: edu === "" ? null : parseInt(edu, 10), notes: f.get("notes") || null };
}

function modal(title, bodyHtml, okLabel) {
  return new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "modal-back";
    wrap.innerHTML = `<div class="modal"><h2>${esc(title)}</h2>${bodyHtml}
      <div class="row-end"><button class="btn ghost" data-act="cancel">Cancel</button><button class="btn primary" data-act="ok">${esc(okLabel)}</button></div></div>`;
    document.body.appendChild(wrap);
    const close = (v) => { wrap.remove(); resolve(v); };
    wrap.querySelector('[data-act="cancel"]').onclick = () => close(null);
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(null); });
    wrap.querySelector('[data-act="ok"]').onclick = () => close(wrap);
    const first = wrap.querySelector("input");
    if (first) first.focus();
  });
}

async function editPatient(p) {
  for (;;) {
    const m = await modal(p ? "Edit patient" : "New patient", patientForm(p || {}), p ? "Save changes" : "Add patient");
    if (!m) return null;
    const data = readPatientForm(m.querySelector("form"));
    try {
      if (!data.name) throw new Error("Please enter the patient's name.");
      return p ? await api(`/api/patients/${p.id}`, { method: "PUT", body: data })
               : await api("/api/patients", { method: "POST", body: data });
    } catch (e) {
      toast(e.message);
    }
  }
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function wireRows() {
  view.querySelectorAll("tr[data-href]").forEach((tr) => { tr.onclick = () => navigate(tr.dataset.href); });
}

// decorative score dial for the home banner
const HERO_ART = `<svg viewBox="0 0 200 200" aria-hidden="true">
  <defs><linearGradient id="heroG" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#14b8a6"/><stop offset="1" stop-color="#0ea5e9"/></linearGradient></defs>
  <circle cx="100" cy="100" r="82" fill="#fff"/>
  <circle cx="100" cy="100" r="62" fill="none" stroke="#e2eeec" stroke-width="14"/>
  <circle cx="100" cy="100" r="62" fill="none" stroke="url(#heroG)" stroke-width="14" stroke-linecap="round"
          stroke-dasharray="335 390" transform="rotate(-90 100 100)"/>
  <circle cx="168" cy="44" r="9" fill="#ff7a59" opacity=".85"/>
  <circle cx="34" cy="160" r="6" fill="#0ea5e9" opacity=".5"/>
  <text x="100" y="106" text-anchor="middle" font-size="44" font-weight="800" fill="#12292a" font-family="inherit">26</text>
  <text x="100" y="129" text-anchor="middle" font-size="13" font-weight="600" fill="#5a7170" font-family="inherit">out of 30</text>
</svg>`;

// ---------------------------------------------------------------- home
async function home() {
  const [stats, recent] = await Promise.all([api("/api/stats"), api("/api/sessions?limit=8")]);
  const avg = stats.average_full != null ? stats.average_full.toFixed(1) : "—";
  view.innerHTML = `<div class="page">
    <section class="hero">
      <div>
        <span class="hero-badge">${icon("sparkle")} Automatic cognitive screening</span>
        <h1>Montreal Cognitive Assessment</h1>
        <p>All 13 MoCA tasks with voice and camera. Every answer is scored the moment it's given, and saved with the recordings and photos.</p>
        <div class="row"><a class="btn primary lg" href="#/new">${icon("play")} Start a new test</a><a class="btn lg" href="#/patients">${icon("users")} Patients &amp; results</a></div>
      </div>
      <div class="hero-art">${HERO_ART}</div>
    </section>
    <div class="stat-grid">
      <div class="stat"><div class="stat-ico c1">${icon("users")}</div><div><div class="stat-n">${stats.patients}</div><div class="stat-l">Patients</div></div></div>
      <div class="stat"><div class="stat-ico c2">${icon("check")}</div><div><div class="stat-n">${stats.finished}</div><div class="stat-l">Tests completed</div></div></div>
      <div class="stat"><div class="stat-ico c3">${icon("clock")}</div><div><div class="stat-n">${stats.in_progress}</div><div class="stat-l">In progress</div></div></div>
      <div class="stat"><div class="stat-ico c4">${icon("chart")}</div><div><div class="stat-n">${avg}</div><div class="stat-l">Average full score</div></div></div>
    </div>
    <section class="card">
      <div class="card-head"><h2>Recent tests</h2><a href="#/patients" class="link">All patients ${icon("arrow")}</a></div>
      ${recent.length ? `<table class="table clickable"><thead><tr><th>Patient</th><th>Date</th><th>Tasks</th><th class="r">Score</th></tr></thead><tbody>
        ${recent.map((s) => `<tr data-href="#/session/${s.id}"><td><span class="person">${avatar(s.patient.name)}${esc(s.patient.name)}</span></td>
          <td class="muted">${fmtDateTime(s.started_at)}</td>
          <td>${s.tasks.length === 13 ? `<span class="tag brand">Full test</span>` : `<span class="tag">${s.tasks.length} task${s.tasks.length > 1 ? "s" : ""}</span>`}</td>
          <td class="r">${scoreBadge(s)}</td></tr>`).join("")}
      </tbody></table>` : emptyState("file", `No tests yet. Press <b>Start a new test</b> to begin.`)}
    </section></div>`;
  wireRows();
}

// ---------------------------------------------------------------- patients
async function patients() {
  view.innerHTML = `<div class="page">
    <div class="page-head"><div><h1>Patients</h1><p class="muted">Everyone tested, with their latest score.</p></div>
      <button class="btn primary" data-act="add">${icon("plus")} Add patient</button></div>
    <div class="card">${searchBox("Search by name…")}<div class="list" style="margin-top:1rem"></div></div></div>`;
  const list = view.querySelector(".list"), search = view.querySelector(".search");
  search.focus();
  const load = async () => {
    const rows = await api(`/api/patients?q=${encodeURIComponent(search.value)}`);
    list.innerHTML = rows.length ? `<table class="table clickable"><thead><tr><th>Name</th><th>Details</th><th>Tests</th><th>Last test</th><th class="r">Last score</th></tr></thead><tbody>
      ${rows.map((p) => `<tr data-href="#/patient/${p.id}"><td><span class="person">${avatar(p.name)}${esc(p.name)}</span></td><td class="muted">${patientLine(p)}</td><td>${p.tests}</td>
        <td class="muted">${p.last_test ? fmtDate(p.last_test.started_at) : "—"}</td><td class="r">${p.last_test ? scoreBadge(p.last_test) : ""}</td></tr>`).join("")}
      </tbody></table>` : emptyState("users", search.value ? "No patient with that name." : "No patients yet. Add the first one.");
    wireRows();
  };
  let timer;
  search.oninput = () => { clearTimeout(timer); timer = setTimeout(load, 200); };
  view.querySelector('[data-act="add"]').onclick = async () => {
    const p = await editPatient(null);
    if (p) navigate(`#/patient/${p.id}`);
  };
  await load();
}

async function patientPage(id) {
  const p = await api(`/api/patients/${id}`);
  const finished = p.sessions.filter((s) => s.status === "finished" && s.max_total === 30).reverse();
  view.innerHTML = `<div class="page">
    <a class="back" href="#/patients">${icon("back")} All patients</a>
    <div class="page-head">
      <div class="who">${avatar(p.name, "lg")}<div><h1>${esc(p.name)}</h1><p class="muted">${patientLine(p) || "No details yet"}${p.date_of_birth ? ` · born ${fmtDate(p.date_of_birth)}` : ""}</p></div></div>
      <div class="row"><button class="btn" data-act="edit">${icon("edit")} Edit details</button><a class="btn primary" href="#/new?patient=${p.id}">${icon("play")} Start a new test</a></div></div>
    ${p.notes ? `<div class="card note">${esc(p.notes)}</div>` : ""}
    ${finished.length >= 2 ? `<div class="card"><h2>Score over time</h2>${trendChart(finished)}</div>` : ""}
    <div class="card"><h2>Tests</h2>
      ${p.sessions.length ? `<table class="table clickable"><thead><tr><th>Date</th><th>Tasks</th><th>Status</th><th class="r">Score</th></tr></thead><tbody>
        ${p.sessions.map((s) => `<tr data-href="#/session/${s.id}"><td>${fmtDateTime(s.started_at)}</td>
          <td>${s.tasks.length === 13 ? `<span class="tag brand">Full test</span>` : `<span class="tag">${s.tasks.length} tasks</span>`}</td>
          <td class="muted">${s.status === "finished" ? "Finished" : "In progress"}</td><td class="r">${scoreBadge(s)}</td></tr>`).join("")}
        </tbody></table>` : emptyState("file", "No tests yet for this patient.")}
    </div></div>`;
  wireRows();
  view.querySelector('[data-act="edit"]').onclick = async () => { if (await editPatient(p)) route(); };
}

function trendChart(sessions) {
  const W = 680, H = 200, pl = 36, pr = 18, pt = 16, pb = 30;
  const xs = (i) => pl + (i * (W - pl - pr)) / (sessions.length - 1);
  const ys = (v) => pt + (1 - v / 30) * (H - pt - pb);
  const pts = sessions.map((s, i) => [xs(i), ys(s.adjusted_total)]);
  const line = pts.map((p) => p.join(",")).join(" ");
  const area = `${pl},${ys(0)} ${line} ${pts[pts.length - 1][0]},${ys(0)}`;
  return `<svg class="trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="MoCA score over time">
    <defs><linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#14b8a6" stop-opacity=".25"/><stop offset="1" stop-color="#14b8a6" stop-opacity="0"/></linearGradient></defs>
    ${[0, 10, 20, 30].map((v) => `<line x1="${pl}" x2="${W - pr}" y1="${ys(v)}" y2="${ys(v)}" class="grid"/><text x="${pl - 8}" y="${ys(v) + 4}" class="axis r">${v}</text>`).join("")}
    <line x1="${pl}" x2="${W - pr}" y1="${ys(26)}" y2="${ys(26)}" class="cut"/><text x="${W - pr}" y="${ys(26) - 6}" class="axis r">26 · normal</text>
    <polygon points="${area}" class="area"/>
    <polyline points="${line}" class="line"/>
    ${pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="5" class="dot"><title>${fmtDate(sessions[i].started_at)}: ${sessions[i].adjusted_total}/30</title></circle>
      <text x="${p[0]}" y="${H - 8}" class="axis c">${fmtDate(sessions[i].started_at)}</text>`).join("")}
  </svg>`;
}

// ---------------------------------------------------------------- new test
async function newTest(patientId) {
  const cfg = await config();
  let chosen = patientId ? await api(`/api/patients/${patientId}`) : null;
  const sections = [...new Set(cfg.tasks.map((t) => t.section))];
  view.innerHTML = `<div class="page narrow">
    <div><h1>New test</h1><p class="muted" style="margin-top:.3rem">Pick the patient and the tasks, then start.</p></div>
    <div class="card"><h2><span class="step">1</span>Patient</h2><div class="patient-pick"></div></div>
    <div class="card"><div class="card-head"><h2><span class="step">2</span>Tasks</h2>
      <div class="row"><button class="btn sm" data-act="all">Select all</button><button class="btn sm ghost" data-act="none">Clear</button></div></div>
      <div class="task-groups">${sections.map((sec) => `<div class="task-group"><div class="eyebrow">${esc(sec)}</div>
        ${cfg.tasks.filter((t) => t.section === sec).map((t) => `<label class="task-check"><input type="checkbox" value="${t.number}" checked>
          <span><b>${t.number}. ${esc(t.title)}</b>${t.camera ? ` <span class="tag">camera</span>` : ""}<small>${esc(t.description)}</small></span>
          <span class="pts">${t.max ? `${t.max} pt${t.max > 1 ? "s" : ""}` : "0 pts"}</span></label>`).join("")}</div>`).join("")}</div>
    </div>
    <div class="start-bar"><span class="total-pts"></span><button class="btn primary lg" data-act="start">${icon("play")} Start test</button></div>
    </div>`;
  const pick = view.querySelector(".patient-pick");
  const totalEl = view.querySelector(".total-pts");
  const boxes = [...view.querySelectorAll(".task-check input")];
  const updateTotal = () => {
    const n = boxes.filter((b) => b.checked).map((b) => +b.value);
    totalEl.textContent = `${n.length} task${n.length === 1 ? "" : "s"} · out of ${cfg.tasks.filter((t) => n.includes(t.number)).reduce((a, t) => a + t.max, 0)} points`;
  };
  boxes.forEach((b) => (b.onchange = updateTotal));
  view.querySelector('[data-act="all"]').onclick = () => { boxes.forEach((b) => (b.checked = true)); updateTotal(); };
  view.querySelector('[data-act="none"]').onclick = () => { boxes.forEach((b) => (b.checked = false)); updateTotal(); };
  updateTotal();

  const renderPick = async () => {
    if (chosen) {
      pick.innerHTML = `<div class="chosen"><span class="person">${avatar(chosen.name)}<span><b>${esc(chosen.name)}</b><br><small class="muted">${patientLine(chosen) || "No details"}</small></span></span>
        <button class="btn sm" data-act="change">Change</button></div>
        ${chosen.education_years == null ? `<p class="hint warn-text">Years of education is empty, so the education point can't be added. <a href="#" data-act="edit">Add it</a></p>` : ""}`;
      pick.querySelector('[data-act="change"]').onclick = () => { chosen = null; renderPick(); };
      const ed = pick.querySelector('[data-act="edit"]');
      if (ed) ed.onclick = async (e) => { e.preventDefault(); const p = await editPatient(chosen); if (p) { chosen = p; renderPick(); } };
      return;
    }
    pick.innerHTML = `<div class="row">${searchBox("Search existing patients…")}<button class="btn primary" data-act="new">${icon("plus")} New patient</button></div><div class="pick-list"></div>`;
    const s = pick.querySelector(".search"), list = pick.querySelector(".pick-list");
    const load = async () => {
      const rows = await api(`/api/patients?q=${encodeURIComponent(s.value)}`);
      list.innerHTML = rows.slice(0, 8).map((p) => `<button class="pick-item" data-id="${p.id}">${avatar(p.name)}<span><b>${esc(p.name)}</b><small>${patientLine(p) || "No details"}</small></span></button>`).join("")
        || `<div class="empty sm">${s.value ? "No match. Add a new patient." : "No patients yet. Add one."}</div>`;
      list.querySelectorAll(".pick-item").forEach((b) => { b.onclick = async () => { chosen = await api(`/api/patients/${b.dataset.id}`); renderPick(); }; });
    };
    let t;
    s.oninput = () => { clearTimeout(t); t = setTimeout(load, 200); };
    pick.querySelector('[data-act="new"]').onclick = async () => { const p = await editPatient(null); if (p) { chosen = p; renderPick(); } };
    await load();
  };
  await renderPick();

  view.querySelector('[data-act="start"]').onclick = async () => {
    const tasks = boxes.filter((b) => b.checked).map((b) => +b.value);
    if (!chosen) return toast("Choose or add a patient first.");
    if (!tasks.length) return toast("Choose at least one task.");
    try {
      const s = await api("/api/sessions", { method: "POST", body: { patient_id: chosen.id, tasks } });
      navigate(`#/run/${s.id}`);
    } catch (e) { toast(e.message); }
  };
}

// ---------------------------------------------------------------- results
function ring(score, max, cls) {
  const r = 70, c = 2 * Math.PI * r, f = max ? Math.max(0, Math.min(1, score / max)) : 0;
  return `<div class="ring-wrap ${cls || ""}">
    <svg class="ring" viewBox="0 0 170 170"><defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#14b8a6"/><stop offset="1" stop-color="#0ea5e9"/></linearGradient></defs>
      <circle cx="85" cy="85" r="${r}" class="ring-bg"/>
      <circle cx="85" cy="85" r="${r}" class="ring-fg" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}"/></svg>
    <div class="ring-center"><div class="total-n">${score}</div><div class="total-of">of ${max}</div></div></div>`;
}

async function sessionPage(id) {
  const [s, cfg] = await Promise.all([api(`/api/sessions/${id}`), config()]);
  const sheet = s.sheet, report = s.report;
  const titleOf = Object.fromEntries(cfg.tasks.map((t) => [t.id, `Task ${t.number} · ${t.title}`]));
  const remaining = s.tasks.filter((n) => !s.done_tasks.includes(n));
  const fullTest = report.max_total === 30;
  const total = s.status === "finished" ? s.total : report.total;
  const adjusted = Math.min(report.max_total, total + (fullTest ? sheet.education_bonus : 0));
  const b = band(adjusted, report.max_total);
  const shown = sheet.sections.filter((sec) => sec.key in report.sections && report.sections[sec.key].max > 0);
  const tasksIn = new Set(Object.keys(report.tasks));
  view.innerHTML = `<div class="page">
    <a class="back" href="#/patient/${s.patient.id}">${icon("back")} ${esc(s.patient.name)}</a>
    <div class="page-head">
      <div class="who">${avatar(s.patient.name, "lg")}<div><h1>MoCA results</h1><p class="muted">${esc(s.patient.name)} · ${fmtDateTime(s.started_at)}${s.status !== "finished" ? ` · <span class="tag brand">In progress</span>` : ""}</p></div></div>
      <div class="row no-print">
        ${remaining.length ? `<a class="btn primary" href="#/run/${s.id}">${icon("play")} Continue test (${remaining.length} left)</a>` : ""}
        <button class="btn" data-act="print">${icon("print")} Print</button>
        <button class="btn ghost danger" data-act="delete">${icon("trash")} Delete</button></div></div>

    <div class="summary-grid">
      <div class="card total-card">
        <div class="eyebrow">Total score</div>
        ${ring(adjusted, report.max_total, b ? b.cls : "")}
        ${b ? `<span class="band ${b.cls}">${b.label}</span>` : `<span class="muted small">${fullTest ? "" : "Partial test: only the chosen tasks"}</span>`}
        ${fullTest && sheet.education_bonus ? `<span class="muted small">${total} + 1 for 12 years of education or less</span>` : ""}
      </div>
      <div class="card sections-card">
        <h2 style="margin:0">By section</h2>
        ${shown.map((sec) => {
          const r = report.sections[sec.key];
          return `<div class="sec-row"><span>${esc(sec.title.charAt(0) + sec.title.slice(1).toLowerCase())}</span>
            <div class="bar ${r.score === r.max ? "full" : ""}"><div style="width:${(r.score / r.max) * 100}%"></div></div><b>${r.score} / ${r.max}</b></div>`;
        }).join("")}
      </div>
    </div>

    <div class="card">
      <h2>Score sheet</h2>
      <div class="sheet">${shown.map((sec) => `<div class="sheet-sec"><div class="sheet-title"><span>${esc(sec.title)}</span><b>${report.sections[sec.key].score} / ${report.sections[sec.key].max}</b></div>
          ${sec.rows.filter((_, i) => tasksIn.has(sheetTaskOf(sec.key, i))).map((r) => `<div class="sheet-row"><span>${esc(r.label)}</span><span class="${r.score >= r.max ? "ok" : r.score ? "part" : "no"}">${r.score} / ${r.max}</span></div>`).join("")}</div>`).join("")}
      ${sheet.memory_recall && Object.keys(sheet.memory_recall).length ? `<div class="sheet-sec"><div class="sheet-title"><span>MEMORY (NOT SCORED)</span></div>
        ${Object.entries(sheet.memory_recall).map(([k, v]) => `<div class="sheet-row"><span>Learning ${esc(k.replace("trial", "trial "))}</span><span>${esc(v.join(", ") || "none")} (${v.length}/5)</span></div>`).join("")}</div>` : ""}
      </div>
    </div>

    <h2 class="section-title">Task details</h2>
    <div class="task-cards">${Object.entries(report.tasks).map(([tid, r]) => resultCardHtml(r, titleOf[tid] || tid)).join("")}</div>
    <p class="muted small">Files for this test are saved in <code>${esc(s.folder)}</code></p>
  </div>`;
  view.querySelector('[data-act="print"]').onclick = () => window.print();
  view.querySelector('[data-act="delete"]').onclick = async () => {
    if (!confirm("Delete this test from the database? (Recordings and photos stay in the results folder.)")) return;
    await api(`/api/sessions/${id}`, { method: "DELETE" });
    navigate(`#/patient/${s.patient.id}`);
  };
}

// which task each score-sheet row belongs to (same order as moca_score_sheet.PAPER_SECTIONS)
const SHEET_TASKS = {
  visuospatial_executive: ["task1_trail_making", "task2_cube_copy", "task3_clock_draw", "task3_clock_draw", "task3_clock_draw"],
  naming: ["task4_naming", "task4_naming", "task4_naming"],
  attention: ["task6_digit_span", "task6_digit_span", "task7_letters", "task8_serial7s"],
  language: ["task9_sentence_repetition", "task9_sentence_repetition", "task10_fluency"],
  abstraction: ["task11_abstraction", "task11_abstraction"],
  delayed_recall: Array(5).fill("task12_delayed_recall"),
  orientation: Array(6).fill("task13_orientation"),
};
const sheetTaskOf = (key, i) => (SHEET_TASKS[key] || [])[i];

// ---------------------------------------------------------------- device check
async function deviceCheck() {
  view.innerHTML = `<div class="page narrow">
    <div><h1>Microphone &amp; camera</h1><p class="muted" style="margin-top:.3rem">Check everything works before a test.</p></div>
    <div class="card"><h2>Microphone</h2><p class="muted">Speak and the bar should move.</p><div class="meter"><div></div></div><p class="error-text" data-mic-err></p></div>
    <div class="card"><h2>Voice</h2><p class="muted">Instructions are read aloud by the browser.</p><button class="btn" data-act="voice">${icon("play")} Play a test sentence</button></div>
    <div class="card"><h2>Camera</h2><div class="cam"><video autoplay muted playsinline></video></div><p class="error-text" data-cam-err></p></div></div>`;
  const bar = view.querySelector(".meter div");
  try {
    await mic.init();
    const iv = setInterval(() => {
      if (!document.body.contains(bar)) return clearInterval(iv);
      bar.style.width = Math.min(100, mic.level * 300) + "%";
    }, 60);
  } catch (e) { view.querySelector("[data-mic-err]").textContent = e.message; }
  view.querySelector('[data-act="voice"]').onclick = () => speak("This is the MoCA voice test. If you can hear this, the voice works.");
  try { await camera(view.querySelector("video")); } catch (e) { view.querySelector("[data-cam-err]").textContent = e.message; }
}

pollStatus();
route();
