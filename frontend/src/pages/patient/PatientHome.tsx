import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import { Empty, ErrorCard, Icon, ScoreBadge, Spinner, StageTag } from "../../components/ui";
import { api } from "../../lib/api";
import { patientProfile, useAuth } from "../../lib/auth";
import { fmtDateTime, greeting } from "../../lib/format";
import type { PatientSession } from "../../lib/types";

export function PatientHome() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { data: tests, error } = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api<PatientSession[]>("/api/sessions"),
  });
  if (error) return <ErrorCard error={error} />;
  if (!tests) return <Spinner />;

  const name = patientProfile(me)?.name.split(" ")[0];
  const unfinished = tests.find((t) => t.stage === "in_progress");
  const open = (t: PatientSession) => navigate(t.stage === "in_progress" ? `/patient/test/${t.id}` : `/patient/results/${t.id}`);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>{greeting()}, {name}</h1><p className="muted">Your cognitive assessments, all in one place.</p></div>
        {!unfinished && <Link className="btn primary lg" to="/patient/start"><Icon name="play" /> Start a test</Link>}
      </div>

      {unfinished && (
        <div className="notice resume">
          <div><h2>Your test isn't finished</h2>
            <p>{unfinished.done_tasks.length} of {unfinished.tasks.length} tasks done. You can carry on where you left off.</p></div>
          <Link className="btn primary" to={`/patient/test/${unfinished.id}`}><Icon name="play" /> Continue</Link>
        </div>
      )}

      <div className="card">
        <h2>My tests</h2>
        {tests.length ? (
          <table className="table clickable">
            <thead><tr><th>Test</th><th>Examiner</th><th>Status</th><th className="r">Result</th></tr></thead>
            <tbody>
              {tests.map((t) => (
                <tr key={t.id} onClick={() => open(t)}>
                  <td><Link to={t.stage === "in_progress" ? `/patient/test/${t.id}` : `/patient/results/${t.id}`} className="row-link" onClick={(e) => e.stopPropagation()}>{t.template_name}</Link><br /><small className="muted">{fmtDateTime(t.started_at)}</small></td>
                  <td className="muted">{t.examiner.name}</td>
                  <td><StageTag stage={t.stage} /></td>
                  <td className="r">{t.result ? <ScoreBadge score={t.result.adjusted_total} max={t.result.max_total} /> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty icon="file">No tests yet. <Link to="/patient/start">Start your first test.</Link></Empty>}
      </div>
    </div>
  );
}
