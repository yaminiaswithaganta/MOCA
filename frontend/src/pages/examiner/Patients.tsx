import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Avatar, Empty, ErrorCard, Icon, ScoreBadge, Spinner, StageTag } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtDate, fmtDateTime, patientLine } from "../../lib/format";
import type { ExaminerSession, PatientProfile } from "../../lib/types";

interface PatientRow extends PatientProfile {
  tests: number;
  last_test: ExaminerSession;
}

export function Patients() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  useEffect(() => {
    const t = setTimeout(() => setQuery(search), 200);
    return () => clearTimeout(t);
  }, [search]);
  const { data: rows, error } = useQuery({
    queryKey: ["patients", query],
    queryFn: () => api<PatientRow[]>(`/api/patients?q=${encodeURIComponent(query)}`),
    placeholderData: keepPreviousData,       // the list stays put while a search loads
  });
  if (error) return <ErrorCard error={error} />;

  return (
    <div className="page">
      <div className="page-head"><div><h1>Patients</h1><p className="muted">Everyone who has taken a test with you.</p></div></div>
      <div className="card">
        <div className="search-wrap"><Icon name="search" />
          <input className="search" aria-label="Search by name" placeholder="Search by name…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div style={{ marginTop: "1rem" }}>
          {!rows ? <Spinner /> : rows.length ? (
            <table className="table clickable">
              <thead><tr><th>Name</th><th>Details</th><th>Tests</th><th>Last test</th><th className="r">Last score</th></tr></thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} onClick={() => navigate(`/examiner/patients/${p.id}`)}>
                    <td><span className="person"><Avatar name={p.name} /><Link to={`/examiner/patients/${p.id}`} className="row-link" onClick={(e) => e.stopPropagation()}>{p.name}</Link></span></td>
                    <td className="muted">{patientLine(p)}</td>
                    <td>{p.tests}</td>
                    <td className="muted">{fmtDate(p.last_test.started_at)}</td>
                    <td className="r">{p.last_test.stage === "in_progress" ? <StageTag stage="in_progress" /> : <ScoreBadge score={p.last_test.adjusted_total} max={p.last_test.max_total} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty icon="users">{search ? "No patient with that name." : "No patients yet. They appear here after starting a test with you."}</Empty>}
        </div>
      </div>
    </div>
  );
}

function TrendChart({ sessions }: { sessions: ExaminerSession[] }) {
  const W = 680, H = 200, pl = 36, pr = 18, pt = 16, pb = 30;
  const xs = (i: number) => pl + (i * (W - pl - pr)) / (sessions.length - 1);
  const ys = (v: number) => pt + (1 - v / 30) * (H - pt - pb);
  const pts = sessions.map((s, i) => [xs(i), ys(s.adjusted_total!)]);
  const line = pts.map((p) => p.join(",")).join(" ");
  return (
    <svg className="trend" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="MoCA score over time">
      <defs><linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#1b7aaf" stopOpacity=".22" /><stop offset="1" stopColor="#1b7aaf" stopOpacity="0" /></linearGradient></defs>
      {[0, 10, 20, 30].map((v) => <g key={v}><line x1={pl} x2={W - pr} y1={ys(v)} y2={ys(v)} className="grid" /><text x={pl - 8} y={ys(v) + 4} className="axis r">{v}</text></g>)}
      <line x1={pl} x2={W - pr} y1={ys(26)} y2={ys(26)} className="cut" /><text x={W - pr} y={ys(26) - 6} className="axis r">26 · normal</text>
      <polygon points={`${pl},${ys(0)} ${line} ${pts[pts.length - 1][0]},${ys(0)}`} className="area" />
      <polyline points={line} className="line" />
      {pts.map((p, i) => (
        <g key={sessions[i].id}>
          <circle cx={p[0]} cy={p[1]} r="5" className="dot"><title>{fmtDate(sessions[i].started_at)}: {sessions[i].adjusted_total}/30</title></circle>
          <text x={p[0]} y={H - 8} className="axis c">{fmtDate(sessions[i].started_at)}</text>
        </g>
      ))}
    </svg>
  );
}

export function PatientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: p, error } = useQuery({
    queryKey: ["patient", id],
    queryFn: () => api<PatientProfile & { sessions: ExaminerSession[] }>(`/api/patients/${id}`),
  });
  if (error) return <ErrorCard error={error} />;
  if (!p) return <Spinner />;
  const full = p.sessions.filter((s) => s.stage !== "in_progress" && s.max_total === 30).reverse();

  return (
    <div className="page">
      <Link className="back" to="/examiner/patients"><Icon name="back" /> All patients</Link>
      <div className="page-head">
        <div className="who"><Avatar name={p.name} large /><div><h1>{p.name}</h1>
          <p className="muted">{patientLine(p) || "No details yet"}{p.date_of_birth ? ` · born ${fmtDate(p.date_of_birth)}` : ""}</p></div></div>
      </div>
      {full.length >= 2 && <div className="card"><h2>Score over time</h2><TrendChart sessions={full} /></div>}
      <div className="card"><h2>Tests</h2>
        <table className="table clickable">
          <thead><tr><th>Date</th><th>Test</th><th>Status</th><th className="r">Score</th></tr></thead>
          <tbody>
            {p.sessions.map((s) => (
              <tr key={s.id} onClick={() => navigate(`/examiner/review/${s.id}`)}>
                <td><Link to={`/examiner/review/${s.id}`} className="row-link" onClick={(e) => e.stopPropagation()}>{fmtDateTime(s.started_at)}</Link></td>
                <td className="muted">{s.template_name}</td>
                <td><StageTag stage={s.stage} examiner /></td>
                <td className="r">{s.stage === "in_progress" ? "—" : <ScoreBadge score={s.adjusted_total} max={s.max_total} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
