// Small shared pieces: icons, avatars, empty states, spinners, score badges.

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { band } from "../lib/format";
import type { Stage } from "../lib/types";

const ICONS: Record<string, string> = {
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c1.9.8 3.1 2.5 3.5 5.2"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16.5 9.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  print: '<path d="M7 9V3h10v6M7 17H4v-7h16v7h-3"/><rect x="7" y="14" width="10" height="7"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
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
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1-4 4-6 7.5-6s6.5 2 7.5 6"/>',
  signout: '<path d="M10 4H5v16h5M15 8l4 4-4 4M19 12H10"/>',
  more: '<circle cx="5.5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/>',
  mail: '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="m3.5 7 8.5 6 8.5-6"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M4 4l16 16M10 5.800A9.7 9.7 0 0 1 12 5.500C18 5.5 21.5 12 21.5 12a17 17 0 0 1-3.2 4M6.2 7.500A16.8 16.8 0 0 0 2.5 12S6 18.5 12 18.500c1.3 0 2.5-.3 3.6-.8"/>',
  ban: '<circle cx="12" cy="12" r="9"/><path d="M5.7 5.700l12.6 12.6"/>',
  shield: '<path d="M12 3l8 3v6c0 4.6-3.2 7.7-8 9-4.8-1.3-8-4.4-8-9V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
};

export function Icon({ name }: { name: string }) {
  return <svg className="i" viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={{ __html: ICONS[name] ?? "" }} />;
}

export function Avatar({ name, large = false }: { name: string; large?: boolean }) {
  const parts = (name || "?").trim().split(/\s+/);
  const initials = (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return <span className={`avatar ${large ? "lg" : ""}`} style={{ "--h": 185 + (h % 40) } as React.CSSProperties}>{initials}</span>;
}

export const Spinner = () => <div className="loading" role="status" aria-label="Loading"><div className="spinner" /></div>;

export function Empty({ icon, children }: { icon: string; children: ReactNode }) {
  return <div className="empty"><div className="empty-icon"><Icon name={icon} /></div>{children}</div>;
}

export function ErrorCard({ error }: { error: unknown }) {
  return (
    <div className="page"><div className="card">
      <h2>Could not load this page</h2>
      <p className="error-text">{error instanceof Error ? error.message : String(error)}</p>
    </div></div>
  );
}

export function FormError({ error }: { error: string | null }) {
  return error ? <p className="form-error" role="alert">{error}</p> : null;
}

export function ScoreBadge({ score, max }: { score: number | null; max: number | null }) {
  const b = band(score, max);
  return <span className={`score-pill ${b?.cls ?? ""}`}>{score}<small>/{max}</small></span>;
}

const STAGE_LABEL: Record<Stage, [string, string]> = {
  in_progress: ["In progress", "brand"],
  awaiting_review: ["Awaiting review", "warn"],
  released: ["Results ready", "ok"],
};

export function StageTag({ stage, examiner = false }: { stage: Stage; examiner?: boolean }) {
  const [label, cls] = STAGE_LABEL[stage];
  return <span className={`tag ${cls}`}>{examiner && stage === "released" ? "Released" : label}</span>;
}

export function StatCard({ icon, value, label, tone = "" }: { icon: string; value: ReactNode; label: string; tone?: string }) {
  return (
    <div className={`stat-card ${tone}`}>
      <span className="stat-ico"><Icon name={icon} /></span>
      <div><div className="stat-n">{value}</div><div className="stat-l">{label}</div></div>
    </div>
  );
}

/** A row's actions, tucked behind a "more" button. */
export function Menu({ label, children }: { label: string; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [open]);
  return (
    <div className="menu" ref={root}>
      <button className="menu-btn" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}><Icon name="more" /></button>
      {open && <div className="menu-list" role="menu">{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function Ring({ score, max, cls }: { score: number; max: number; cls?: string }) {
  const r = 70, c = 2 * Math.PI * r, f = max ? Math.max(0, Math.min(1, score / max)) : 0;
  return (
    <div className={`ring-wrap ${cls ?? ""}`}>
      <svg className="ring" viewBox="0 0 170 170" aria-hidden="true">
        <circle cx="85" cy="85" r={r} className="ring-bg" />
        <circle cx="85" cy="85" r={r} className="ring-fg" strokeDasharray={`${(c * f).toFixed(1)} ${c.toFixed(1)}`} />
      </svg>
      <div className="ring-center"><div className="total-n">{score}</div><div className="total-of">of {max}</div></div>
    </div>
  );
}

export function Logo() {
  return (
    <span className="logo">
      <svg viewBox="0 0 40 40" aria-hidden="true">
        <defs><linearGradient id="logoBg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#1b7aaf" /><stop offset="1" stopColor="#0d4466" /></linearGradient></defs>
        <rect width="40" height="40" rx="12" fill="url(#logoBg)" />
        <polyline points="10,29 14,12 20,23 26,12 30,29" fill="none" stroke="#fff" strokeOpacity=".9" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="10" cy="29" r="2.9" fill="#fff" /><circle cx="14" cy="12" r="2.9" fill="#fff" /><circle cx="20" cy="23" r="2.9" fill="#fff" />
        <circle cx="26" cy="12" r="2.9" fill="#fff" /><circle cx="30" cy="29" r="3.6" fill="#f5b841" />
      </svg>
    </span>
  );
}

/** A password box with a show/hide button. The button sits outside the label, so the box is
 *  announced simply by its label. */
export function PasswordField({ label, value, onChange, autoComplete, minLength, className = "" }: {
  label: string; value: string; onChange: (v: string) => void; autoComplete: string; minLength?: number; className?: string;
}) {
  const [shown, setShown] = useState(false);
  const id = useId();
  return (
    <div className={`pw-field ${className}`}>
      <label htmlFor={id}>{label}</label>
      <span className="pw">
        <input id={id} type={shown ? "text" : "password"} required minLength={minLength} autoComplete={autoComplete} value={value} onChange={(e) => onChange(e.target.value)} />
        <button type="button" aria-label={shown ? "Hide password" : "Show password"} aria-pressed={shown} onClick={() => setShown(!shown)}><Icon name={shown ? "eyeoff" : "eye"} /></button>
      </span>
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

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
