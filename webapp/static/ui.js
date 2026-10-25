// Small shared helpers for the pages.

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : `request failed (${res.status})`);
  return data;
}

let _config = null;
export async function config() {
  if (!_config) _config = await api("/api/config");
  return _config;
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function fmtDateTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function age(dob) {
  if (!dob) return null;
  const d = new Date(dob + "T00:00:00"), n = new Date();
  let a = n.getFullYear() - d.getFullYear();
  if (n.getMonth() < d.getMonth() || (n.getMonth() === d.getMonth() && n.getDate() < d.getDate())) a--;
  return a;
}

/** MoCA: 26 or more out of 30 is in the normal range. */
export function band(score, max) {
  if (score == null || max !== 30) return null;
  return score >= 26 ? { cls: "good", label: "Normal range (26+)" } : { cls: "warn", label: "Below 26" };
}

const LABELS = {
  contour: "Contour", numbers: "Numbers", hands: "Hands", lion: "Lion", rhino: "Rhino", camel: "Camel",
  digits_forward: "Forward", digits_backward: "Backward", letters_a: "Letters", serial7: "Serial 7s",
  sentence_1: "Sentence 1", sentence_2: "Sentence 2", fluency: "F words",
  train_bicycle: "Train – bicycle", watch_ruler: "Watch – ruler",
  face: "Face", velvet: "Velvet", church: "Church", daisy: "Daisy", red: "Red",
  date: "Date", month: "Month", year: "Year", day: "Day", place: "Place", city: "City",
};
const CRIT_MAX = { serial7: 3 };

export function criteriaChips(criteria) {
  if (!criteria) return "";
  return `<div class="chips">${Object.entries(criteria).map(([k, v]) => {
    const mx = CRIT_MAX[k] || 1;
    const cls = v >= mx ? "ok" : v > 0 ? "part" : "no";
    return `<span class="chip ${cls}">${esc(LABELS[k] || k)} <b>${v}${mx > 1 ? "/" + mx : ""}</b></span>`;
  }).join("")}</div>`;
}

/** Short human summary of what was heard / recalled for a task result. */
export function heardSummary(r) {
  const d = r.details || {};
  const q = (t) => (t ? `“${esc(t)}”` : "<i>nothing</i>");
  switch (r.task) {
    case "task1_trail_making":
      return `Path said: <b>${esc((d.spoken_sequence || []).join(" → ") || "—")}</b><br>Heard: ${q(d.final_transcript)}`;
    case "task4_naming":
      return ["lion", "rhino", "camel"].filter((k) => d[k]).map((k) => `${LABELS[k]}: ${q(d[k].heard_as || d[k].final_transcript)}`).join("<br>");
    case "task5_memory":
      return (d.trials || []).map((t) => `Trial ${t.trial}: <b>${t.recalled.join(", ") || "none"}</b> (${t.n_recalled}/5)`).join("<br>");
    case "task6_digit_span":
      return ["digits_forward", "digits_backward"].filter((k) => d[k]).map((k) => `${LABELS[k]}: said ${esc((d[k].said || []).join(" ") || "nothing")}`).join("<br>");
    case "task7_letters":
      return d.letters_a ? `${d.letters_a.errors} error(s) · ${d.letters_a.mode === "camera" ? "camera" : "examiner key"}` : "";
    case "task8_serial7s":
      return d.serial7 ? `Answers: <b>${esc((d.serial7.answers || []).join(", ") || "none")}</b>` : "";
    case "task9_sentence_repetition":
      return (d.sentences || []).map((s, i) => `Sentence ${i + 1}: ${q(s.heard)} (${Math.round(s.match * 100)}% match)`).join("<br>");
    case "task10_fluency":
      return `${d.words_counted ?? 0} F-words: ${esc((d.words || []).join(", "))}`;
    case "task11_abstraction":
      return ["train_bicycle", "watch_ruler"].filter((k) => d[k]).map((k) => `${LABELS[k]}: ${q(d[k].heard)}`).join("<br>");
    case "task12_delayed_recall":
      return `Recalled: <b>${esc((d.recalled || []).join(", ") || "none")}</b>${d.missed && d.missed.length ? ` · missed ${esc(d.missed.join(", "))}` : ""}`;
    case "task13_orientation":
      return Object.entries(d.items || {}).map(([k, v]) => `${LABELS[k]}: ${q(v.heard)}`).join("<br>");
    default:
      return "";
  }
}

export function evidenceHtml(r) {
  const urls = r.evidence_urls || [];
  const imgs = urls.filter((u) => /\.(png|jpe?g)$/i.test(u));
  const wavs = urls.filter((u) => /\.wav$/i.test(u));
  let out = "";
  if (imgs.length) out += `<div class="evidence-imgs">${imgs.map((u) => `<a href="${u}" target="_blank"><img src="${u}" alt="" loading="lazy"></a>`).join("")}</div>`;
  if (wavs.length) out += `<div class="evidence-audio">${wavs.map((u) => `<div><span>${esc(u.split("/").pop().replace(/\.wav$/, "").replace(/^task\d+_/, "").replace(/_/g, " "))}</span><audio controls preload="none" src="${u}"></audio></div>`).join("")}</div>`;
  return out;
}

// ---------------------------------------------------------------- icons + avatars
const ICONS = {
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c1.9.8 3.1 2.5 3.5 5.2"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16.5 9.5"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  print: '<path d="M7 9V3h10v6M7 17H4v-7h16v7h-3"/><rect x="7" y="14" width="10" height="7"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  camera: '<path d="M3 8a2 2 0 0 1 2-2h2.5l1.5-2h6l1.5 2H19a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="3.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  pen: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
  quiet: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M17 9l4 6M21 9l-4 6"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',
  paw: '<circle cx="6.5" cy="10" r="1.9"/><circle cx="10" cy="6" r="1.9"/><circle cx="14.5" cy="6" r="1.9"/><circle cx="18" cy="10" r="1.9"/><path d="M8 17.5c0-3 1.8-5.5 4.2-5.5s4.2 2.5 4.2 5.5c0 1.8-1.6 2.5-2.6 2.1-1-.4-2.2-.4-3.2 0-1 .4-2.6-.3-2.6-2.1z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
  chat: '<path d="M4 5.5h16v10.5H10l-5 4v-4H4z"/><path d="M8 10h8M8 13h5"/>',
  link: '<circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5"/>',
  repeat: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4v4h4"/><path d="M12 8.5V12l2.5 1.8"/>',
  compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
};

export function icon(name) {
  return `<svg class="i" viewBox="0 0 24 24">${ICONS[name] || ""}</svg>`;
}

export function avatar(name, cls = "") {
  const parts = String(name || "?").trim().split(/\s+/);
  const ini = ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  let h = 0;
  for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `<span class="avatar ${cls}" style="--h:${h}">${esc(ini)}</span>`;
}

// ---------------------------------------------------------------- the 7 MoCA areas, each with its own colour
export const DOMAINS = [
  { key: "visuospatial_executive", icon: "cube", label: "Visuospatial / executive", short: "Visuospatial", what: "Trail making, cube, clock", max: 5, color: "#1b7aaf" },
  { key: "naming", icon: "paw", label: "Naming", short: "Naming", what: "Lion, rhino, camel", max: 3, color: "#22a699" },
  { key: "attention", icon: "target", label: "Attention", short: "Attention", what: "Digits, letters, serial 7s", max: 6, color: "#f5b841" },
  { key: "language", icon: "chat", label: "Language", short: "Language", what: "Sentences, F-word fluency", max: 3, color: "#ef7d5b" },
  { key: "abstraction", icon: "link", label: "Abstraction", short: "Abstraction", what: "Train–bicycle, watch–ruler", max: 2, color: "#8b7fd1" },
  { key: "delayed_recall", icon: "repeat", label: "Delayed recall", short: "Recall", what: "The five words, no cues", max: 5, color: "#5bb8e6" },
  { key: "orientation", icon: "compass", label: "Orientation", short: "Orientation", what: "Date, day, place, city", max: 6, color: "#3f9b6b" },
];
export const DOMAIN_OF = Object.fromEntries(DOMAINS.map((d) => [d.key, d]));
