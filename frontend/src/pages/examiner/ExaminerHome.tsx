import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import { Avatar, Empty, ErrorCard, Icon, ScoreBadge, Spinner, StageTag, StatCard } from "../../components/ui";
import { api } from "../../lib/api";
import { examinerProfile, useAuth } from "../../lib/auth";
import { fmtDateTime, greeting } from "../../lib/format";
import type { ExaminerSession, Stats } from "../../lib/types";

function SessionTable({ rows }: { rows: ExaminerSession[] }) {
  const navigate = useNavigate();
  return (
    <table className="table clickable">
      <thead><tr><th>Patient</th><th>Test</th><th>Date</th><th>Status</th><th className="r">Score</th></tr></thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.id} onClick={() => navigate(`/examiner/review/${s.id}`)}>
            <td><span className="person"><Avatar name={s.patient.name} /><Link to={`/examiner/review/${s.id}`} className="row-link" onClick={(e) => e.stopPropagation()}>{s.patient.name}</Link></span></td>
            <td className="muted">{s.template_name}</td>
            <td className="muted">{fmtDateTime(s.started_at)}</td>
            <td><StageTag stage={s.stage} examiner /></td>
            <td className="r">{s.stage === "in_progress" ? "—" : <ScoreBadge score={s.adjusted_total} max={s.max_total} />}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ExaminerHome() {
  const { me } = useAuth();
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/api/stats") });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api<ExaminerSession[]>("/api/sessions") });
  if (stats.error || sessions.error) return <ErrorCard error={stats.error ?? sessions.error} />;
  if (!stats.data || !sessions.data) return <Spinner />;

  const s = stats.data;
  const waiting = sessions.data.filter((x) => x.stage === "awaiting_review");
  const other = sessions.data.filter((x) => x.stage !== "awaiting_review").slice(0, 8);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>{greeting()}, {examinerProfile(me)?.name}</h1><p className="muted">Here's what needs your attention.</p></div>
        <Link className="btn primary" to="/examiner/tests/new"><Icon name="plus" /> Design a test</Link>
      </div>
      <section className="stat-grid">
        <StatCard icon="clock" value={s.awaiting_review} label="Awaiting review" tone={s.awaiting_review ? "warn" : ""} />
        <StatCard icon="play" value={s.in_progress} label="In progress" />
        <StatCard icon="users" value={s.patients} label="Patients" />
        <StatCard icon="check" value={s.average_full != null ? s.average_full.toFixed(1) : "—"} label="Average score /30" tone="ok" />
      </section>
      <div className="card">
        <h2>Awaiting your review</h2>
        {waiting.length ? <SessionTable rows={waiting} /> : <Empty icon="check">Nothing to review right now.</Empty>}
      </div>
      {other.length > 0 && <div className="card"><h2>Recent tests</h2><SessionTable rows={other} /></div>}
    </div>
  );
}
