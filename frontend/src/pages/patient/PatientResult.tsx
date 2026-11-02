// After a test: "being reviewed", or the result the examiner released.

import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router";
import { Avatar, DOMAIN_OF, ErrorCard, Icon, Ring, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { band, fmtDate, fmtDateTime } from "../../lib/format";
import type { PatientSession } from "../../lib/types";

export function PatientResult() {
  const { id } = useParams();
  const { data: s, error } = useQuery({
    queryKey: ["session", id],
    queryFn: () => api<PatientSession>(`/api/sessions/${id}`),
  });
  if (error) return <ErrorCard error={error} />;
  if (!s) return <Spinner />;
  if (s.stage === "in_progress") return <Navigate to={`/patient/test/${s.id}`} replace />;

  const back = <Link className="back" to="/patient"><Icon name="back" /> My tests</Link>;
  const r = s.result;
  if (!r) {
    return (
      <div className="page narrow">
        {back}
        <div className="card center-block saved-card">
          <div className="saved-tick">✓</div>
          <h1>Thank you. Your test is complete.</h1>
          <p className="lead">{s.examiner.name} will review your answers. Your result will appear here when it's ready.</p>
          <p className="muted small">{s.template_name} · finished {fmtDateTime(s.finished_at)}</p>
        </div>
      </div>
    );
  }

  const b = band(r.adjusted_total, r.max_total);
  const shown = r.sheet_sections.filter((sec) => r.sections[sec.key]?.max > 0);
  return (
    <div className="page">
      {back}
      <div className="page-head"><div><h1>Your result</h1><p className="muted">{s.template_name} · reviewed {fmtDate(r.released_at)}</p></div>
        <button className="btn no-print" onClick={() => window.print()}><Icon name="print" /> Print</button></div>

      {r.note && (
        <div className="notice">
          <div className="person"><Avatar name={s.examiner.name} /><span>Note from {s.examiner.name}</span></div>
          <p style={{ marginTop: ".6rem", whiteSpace: "pre-wrap" }}>{r.note}</p>
        </div>
      )}

      <div className="summary-grid">
        <div className="card total-card">
          <div className="eyebrow">Total score</div>
          <Ring score={r.adjusted_total} max={r.max_total} cls={b?.cls} />
          {b ? <span className={`band ${b.cls}`}>{b.label}</span> : <span className="muted small">Partial test: only the chosen tasks</span>}
          {r.education_bonus > 0 && <span className="muted small">{r.total} + 1 for 12 years of education or less</span>}
        </div>
        <div className="card sections-card">
          <h2 style={{ margin: 0 }}>By area</h2>
          {shown.map((sec) => {
            const v = r.sections[sec.key], d = DOMAIN_OF[sec.key];
            return (
              <div className="sec-row" key={sec.key} style={{ "--c": d.color } as React.CSSProperties}>
                <span><i className="dot" />{d.label}</span>
                <div className="bar"><div style={{ width: `${(v.score / v.max) * 100}%` }} /></div>
                <b>{v.score} / {v.max}</b>
              </div>
            );
          })}
        </div>
      </div>
      <p className="muted small">The MoCA is a screening test, not a diagnosis. Please talk through this result with {s.examiner.name} or your doctor.</p>
    </div>
  );
}
