// One task's result for the examiner: score, what was heard, evidence, and correcting it.

import { useState, type FormEvent, type ReactNode } from "react";
import { fileUrl } from "../lib/api";
import type { TaskResult } from "../lib/types";
import { FormError } from "./ui";

const LABELS: Record<string, string> = {
  contour: "Contour", numbers: "Numbers", hands: "Hands", lion: "Lion", rhino: "Rhino", camel: "Camel",
  digits_forward: "Forward", digits_backward: "Backward", letters_a: "Letters", serial7: "Serial 7s",
  sentence_1: "Sentence 1", sentence_2: "Sentence 2", fluency: "F words",
  train_bicycle: "Train – bicycle", watch_ruler: "Watch – ruler",
  face: "Face", velvet: "Velvet", church: "Church", daisy: "Daisy", red: "Red",
  date: "Date", month: "Month", year: "Year", day: "Day", place: "Place", city: "City",
};
const CRITERION_MAX: Record<string, number> = { serial7: 3 };
const criterionMax = (k: string) => CRITERION_MAX[k] ?? 1;

function Chips({ criteria }: { criteria: Record<string, number> }) {
  return (
    <div className="chips">
      {Object.entries(criteria).map(([k, v]) => {
        const mx = criterionMax(k);
        return <span key={k} className={`chip ${v >= mx ? "ok" : v > 0 ? "part" : "no"}`}>{LABELS[k] ?? k} <b>{v}{mx > 1 ? `/${mx}` : ""}</b></span>;
      })}
    </div>
  );
}

const Quoted = ({ text }: { text?: string }) => (text ? <>“{text}”</> : <i>nothing</i>);

function Lines({ rows }: { rows: ReactNode[] }) {
  return <>{rows.map((r, i) => <div key={i}>{r}</div>)}</>;
}

/** Short human summary of what was heard / recalled for a task result. */
function HeardSummary({ r }: { r: TaskResult }) {
  const d = r.details ?? {};
  switch (r.task) {
    case "task1_trail_making":
      return <Lines rows={[<>Path said: <b>{(d.spoken_sequence ?? []).join(" → ") || "—"}</b></>, <>Heard: <Quoted text={d.final_transcript} /></>]} />;
    case "task4_naming":
      return <Lines rows={["lion", "rhino", "camel"].filter((k) => d[k]).map((k) => <>{LABELS[k]}: <Quoted text={d[k].heard_as || d[k].final_transcript} /></>)} />;
    case "task5_memory":
      return <Lines rows={(d.trials ?? []).map((t: any) => <>Trial {t.trial}: <b>{t.recalled.join(", ") || "none"}</b> ({t.n_recalled}/5)</>)} />;
    case "task6_digit_span":
      return <Lines rows={["digits_forward", "digits_backward"].filter((k) => d[k]).map((k) => <>{LABELS[k]}: said {(d[k].said ?? []).join(" ") || "nothing"}</>)} />;
    case "task7_letters":
      return d.letters_a ? <>{d.letters_a.errors} error(s) · {d.letters_a.mode === "camera" ? "camera" : "patient key press"}</> : null;
    case "task8_serial7s":
      return d.serial7 ? <>Answers: <b>{(d.serial7.answers ?? []).join(", ") || "none"}</b></> : null;
    case "task9_sentence_repetition":
      return <Lines rows={(d.sentences ?? []).map((s: any, i: number) => <>Sentence {i + 1}: <Quoted text={s.heard} /> ({Math.round(s.match * 100)}% match)</>)} />;
    case "task10_fluency":
      return <>{d.words_counted ?? 0} F-words: {(d.words ?? []).join(", ")}</>;
    case "task11_abstraction":
      return <Lines rows={["train_bicycle", "watch_ruler"].filter((k) => d[k]).map((k) => <>{LABELS[k]}: <Quoted text={d[k].heard} /></>)} />;
    case "task12_delayed_recall":
      return <>Recalled: <b>{(d.recalled ?? []).join(", ") || "none"}</b>{d.missed?.length ? ` · missed ${d.missed.join(", ")}` : ""}</>;
    case "task13_orientation":
      return <Lines rows={Object.entries<any>(d.items ?? {}).map(([k, v]) => <>{LABELS[k] ?? k}: <Quoted text={v.heard} /></>)} />;
    default:
      return null;
  }
}

function Evidence({ urls }: { urls: string[] }) {
  const [loaded, setLoaded] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = async (url: string) => {
    setError(null);
    try {
      const local = await fileUrl(url);
      setLoaded((l) => ({ ...l, [url]: local }));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const nameOf = (u: string) => u.split("/").pop()!;
  const images = urls.filter((u) => /\.(png|jpe?g)$/i.test(u));
  const audio = urls.filter((u) => /\.wav$/i.test(u));
  return (
    <>
      {images.length > 0 && (
        <div className="evidence-imgs">
          {images.map((u) => loaded[u]
            ? <a key={u} href={loaded[u]} target="_blank" rel="noreferrer"><img src={loaded[u]} alt={nameOf(u)} /></a>
            : <button key={u} className="btn sm" onClick={() => load(u)}>Show {nameOf(u).replace(/\.\w+$/, "").replace(/_/g, " ")}</button>)}
        </div>
      )}
      {audio.length > 0 && (
        <div className="evidence-audio">
          {audio.map((u) => (
            <div key={u}>
              <span>{nameOf(u).replace(/\.wav$/, "").replace(/^task\d+_/, "").replace(/_/g, " ")}</span>
              {loaded[u] ? <audio controls autoPlay src={loaded[u]} /> : <button className="btn sm" onClick={() => load(u)}>Play</button>}
            </div>
          ))}
        </div>
      )}
      <FormError error={error} />
    </>
  );
}

interface Correction {
  score?: number;
  criteria?: Record<string, number>;
  note: string;
}

function CorrectForm({ r, onSave, onCancel }: { r: TaskResult; onSave: (c: Correction) => Promise<void>; onCancel: () => void }) {
  const [criteria, setCriteria] = useState(r.criteria);
  const [score, setScore] = useState(r.score);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSave(criteria ? { criteria, note } : { score, note });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };
  const options = (max: number) => Array.from({ length: max + 1 }, (_, i) => <option key={i} value={i}>{i}</option>);

  return (
    <form className="correct-form" onSubmit={submit}>
      <div className="correct-grid">
        {criteria ? Object.entries(criteria).map(([k, v]) => (
          <label key={k}>{LABELS[k] ?? k}
            <select value={v} onChange={(e) => setCriteria({ ...criteria, [k]: +e.target.value })}>{options(criterionMax(k))}</select>
          </label>
        )) : (
          <label>Score<select value={score} onChange={(e) => setScore(+e.target.value)}>{options(r.max_score)}</select></label>
        )}
      </div>
      <label>Reason for the correction
        <input required maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Kept with the record" />
      </label>
      <FormError error={error} />
      <div className="row">
        <button className="btn primary sm" disabled={busy}>Save correction</button>
        <button type="button" className="btn ghost sm" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

interface Props {
  r: TaskResult;
  title: string;
  canCorrect: boolean;
  onCorrect: (c: Correction) => Promise<void>;
}

export function TaskResultCard({ r, title, canCorrect, onCorrect }: Props) {
  const [editing, setEditing] = useState(false);
  const scored = r.max_score > 0;
  const tone = !r.completed ? "skipped" : !scored ? "" : r.score === r.max_score ? "full" : r.score === 0 ? "zero" : "";
  return (
    <div className={`result-card ${tone}`}>
      <div className="result-top">
        <div>
          <div className="eyebrow">{title}</div>
          <div className="score-big">{scored ? <>{r.score}<span>/ {r.max_score}</span></> : "Recorded"}</div>
        </div>
        <div className="result-tags">
          {!r.completed && <span className="tag warn">Not completed</span>}
          {r.corrected_at && <span className="tag brand">Corrected</span>}
        </div>
      </div>
      {r.criteria && <Chips criteria={r.criteria} />}
      <p className="reason">{r.reason}</p>
      {r.corrected_at && <p className="reason">Automatic score {r.auto_score}. Correction: {r.correction_note}</p>}
      <div className="heard-summary"><HeardSummary r={r} /></div>
      <Evidence urls={r.evidence_urls} />
      {editing
        ? <CorrectForm r={r} onCancel={() => setEditing(false)} onSave={async (c) => { await onCorrect(c); setEditing(false); }} />
        : canCorrect && scored && <div className="no-print"><button className="btn sm" onClick={() => setEditing(true)}>Correct score</button></div>}
    </div>
  );
}
