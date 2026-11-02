// One patient's test: everything the examiner needs to check, correct and release it.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { TaskResultCard } from "../../components/TaskResultCard";
import { Avatar, DOMAIN_OF, ErrorCard, FormError, Icon, Modal, Ring, Spinner, StageTag } from "../../components/ui";
import { api, config } from "../../lib/api";
import { band, fmtDateTime, patientLine } from "../../lib/format";
import type { ExaminerSession, TaskInfo } from "../../lib/types";

// which task each score-sheet row belongs to (same order as moca_score_sheet.PAPER_SECTIONS)
const SHEET_TASKS: Record<string, string[]> = {
  visuospatial_executive: ["task1_trail_making", "task2_cube_copy", "task3_clock_draw", "task3_clock_draw", "task3_clock_draw"],
  naming: ["task4_naming", "task4_naming", "task4_naming"],
  attention: ["task6_digit_span", "task6_digit_span", "task7_letters", "task8_serial7s"],
  language: ["task9_sentence_repetition", "task9_sentence_repetition", "task10_fluency"],
  abstraction: ["task11_abstraction", "task11_abstraction"],
  delayed_recall: Array(5).fill("task12_delayed_recall"),
  orientation: Array(6).fill("task13_orientation"),
};

function ReleaseDialog({ onClose, onRelease, busy, error }: { onClose: () => void; onRelease: (note: string) => void; busy: boolean; error: string | null }) {
  const [note, setNote] = useState("");
  return (
    <Modal title="Release this result?" onClose={onClose}>
      <p className="muted">The patient will see their total and the score for each area. After this the score can't be changed.</p>
      <div className="stack">
        <label>Note for the patient (optional)
          <textarea rows={4} maxLength={2000} value={note} placeholder="What this means and what happens next" onChange={(e) => setNote(e.target.value)} />
        </label>
      </div>
      <FormError error={error} />
      <div className="row-end">
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy} onClick={() => onRelease(note)}>Release to patient</button>
      </div>
    </Modal>
  );
}

export function Review() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queries = useQueryClient();
  const [releasing, setReleasing] = useState(false);
  const closeRelease = useCallback(() => setReleasing(false), []);
  const key = ["session", id];
  const session = useQuery({ queryKey: key, queryFn: () => api<ExaminerSession>(`/api/sessions/${id}`) });
  const cfg = useQuery({ queryKey: ["config"], queryFn: config, staleTime: Infinity });

  const refresh = (s: ExaminerSession) => {
    queries.setQueryData(key, s);
    queries.invalidateQueries({ queryKey: ["sessions"] });
    queries.invalidateQueries({ queryKey: ["stats"] });
  };
  const release = useMutation({
    mutationFn: (note: string) => api<ExaminerSession>(`/api/sessions/${id}/release`, { method: "POST", body: { note } }),
    onSuccess: (s) => { refresh(s); setReleasing(false); },
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queries.invalidateQueries({ queryKey: ["sessions"] });
      queries.invalidateQueries({ queryKey: ["stats"] });
      navigate(`/examiner/patients/${session.data?.patient.id}`);
    },
  });

  if (session.error || cfg.error) return <ErrorCard error={session.error ?? cfg.error} />;
  const s = session.data;
  if (!s || !cfg.data) return <Spinner />;

  const { report, sheet } = s;
  const tasks: TaskInfo[] = cfg.data.tasks;
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const fullTest = report!.max_total === 30;
  const total = report!.total;
  const adjusted = Math.min(report!.max_total, total + (fullTest ? sheet!.education_bonus : 0));
  const b = band(adjusted, report!.max_total);
  const shown = sheet!.sections.filter((sec) => report!.sections[sec.key]?.max > 0);
  const inTest = new Set(Object.keys(report!.tasks));
  const canCorrect = s.stage === "awaiting_review";

  const correct = async (number: number, body: object) => {
    refresh(await api<ExaminerSession>(`/api/sessions/${id}/tasks/${number}`, { method: "PATCH", body }));
  };

  return (
    <div className="page">
      <Link className="back" to={`/examiner/patients/${s.patient.id}`}><Icon name="back" /> {s.patient.name}</Link>
      <div className="page-head">
        <div className="who"><Avatar name={s.patient.name} large />
          <div><h1>{s.patient.name}</h1>
            <p className="muted">{s.template_name} · {fmtDateTime(s.started_at)} · {patientLine(s.patient)}</p>
            <StageTag stage={s.stage} examiner /></div></div>
        <div className="page-actions no-print">
          <button className="btn" onClick={() => window.print()}><Icon name="print" /> Print</button>
          <button className="btn ghost danger" disabled={remove.isPending} onClick={() => { if (window.confirm("Permanently delete this test, with its recordings and photos? This can't be undone.")) remove.mutate(); }}><Icon name="trash" /> Delete</button>
        </div>
      </div>
      <FormError error={remove.error?.message ?? null} />

      {s.stage === "in_progress" && <div className="notice"><p>{s.patient.name} is still taking this test: {s.done_tasks.length} of {s.tasks.length} tasks done. The score below is provisional.</p></div>}
      {s.review_note && <div className="notice"><b>Your note to the patient</b><p style={{ whiteSpace: "pre-wrap" }}>{s.review_note}</p></div>}

      <div className="summary-grid">
        <div className="card total-card">
          <div className="eyebrow">Total score</div>
          <Ring score={adjusted} max={report!.max_total} cls={b?.cls} />
          {b ? <span className={`band ${b.cls}`}>{b.label}</span> : <span className="muted small">Partial test: only the chosen tasks</span>}
          {fullTest && sheet!.education_bonus > 0 && <span className="muted small">{total} + 1 for 12 years of education or less</span>}
        </div>
        <div className="card sections-card">
          <h2 style={{ margin: 0 }}>By section</h2>
          {shown.map((sec) => {
            const r = report!.sections[sec.key], d = DOMAIN_OF[sec.key];
            return (
              <div className="sec-row" key={sec.key} style={{ "--c": d.color } as React.CSSProperties}>
                <span><i className="dot" />{d.label}</span>
                <div className="bar"><div style={{ width: `${(r.score / r.max) * 100}%` }} /></div>
                <b>{r.score} / {r.max}</b>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card">
        <h2>Score sheet</h2>
        <div className="sheet">
          {shown.map((sec) => (
            <div className="sheet-sec" key={sec.key} style={{ "--c": DOMAIN_OF[sec.key].color } as React.CSSProperties}>
              <div className="sheet-title"><span>{sec.title}</span><b>{report!.sections[sec.key].score} / {report!.sections[sec.key].max}</b></div>
              {sec.rows.filter((_, i) => inTest.has(SHEET_TASKS[sec.key]?.[i])).map((r) => (
                <div className="sheet-row" key={r.label}><span>{r.label}</span><span className={r.score >= r.max ? "ok" : r.score ? "part" : "no"}>{r.score} / {r.max}</span></div>
              ))}
            </div>
          ))}
          {Object.keys(sheet!.memory_recall).length > 0 && (
            <div className="sheet-sec">
              <div className="sheet-title"><span>MEMORY (NOT SCORED)</span></div>
              {Object.entries(sheet!.memory_recall).map(([k, v]) => (
                <div className="sheet-row" key={k}><span>Learning {k.replace("trial", "trial ")}</span><span>{v.join(", ") || "none"} ({v.length}/5)</span></div>
              ))}
            </div>
          )}
        </div>
      </div>

      <h2 className="section-title">Task details</h2>
      <div className="task-cards">
        {s.tasks.map((n) => {
          const t = tasks.find((x) => x.number === n)!, r = report!.tasks[t.id];
          return <TaskResultCard key={t.id} r={r} title={`Task ${n} · ${byId[t.id].title}`} canCorrect={canCorrect} onCorrect={(c) => correct(n, c)} />;
        })}
      </div>

      {canCorrect && (
        <div className="review-bar no-print">
          <span>Check the scores above, then release the result to {s.patient.name}.</span>
          <button className="btn white" onClick={() => setReleasing(true)}>Release result</button>
        </div>
      )}
      {releasing && <ReleaseDialog onClose={closeRelease} onRelease={(note) => release.mutate(note)} busy={release.isPending} error={release.error?.message ?? null} />}
    </div>
  );
}
