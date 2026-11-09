import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Avatar, Empty, ErrorCard, FormError, Icon, Modal, ScoreBadge, Spinner, StageTag } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtDate, fmtDateTime, patientLine } from "../../lib/format";
import type { ExaminerSession, Invite, PatientProfile } from "../../lib/types";

interface PatientRow extends PatientProfile {
  tests: number;
  last_test: ExaminerSession | null;
}

const linkOf = (inv: Invite) => `${location.origin}/join/${inv.token}`;

function CopyLink({ inv }: { inv: Invite }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(linkOf(inv)).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return <button className="btn sm" onClick={copy}><Icon name="link" /> {copied ? "Copied" : "Copy link"}</button>;
}

function AddPatient({ onClose }: { onClose: () => void }) {
  const queries = useQueryClient();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [dob, setDob] = useState("");
  const add = useMutation({
    mutationFn: () => api<Invite>("/api/invites", { method: "POST", body: { name, email, date_of_birth: dob } }),
    onSuccess: () => queries.invalidateQueries({ queryKey: ["invites"] }),
  });
  const inv = add.data;
  return (
    <Modal title={inv ? "Share this link" : "Add a patient"} onClose={onClose}>
      {inv ? (
        <div className="stack">
          <p className="muted" style={{ margin: 0 }}>Send this link to <b>{inv.name}</b> by email or message. They open it, confirm their details and can start their test. The same link lets them come back later.</p>
          <input readOnly value={linkOf(inv)} onFocus={(e) => e.target.select()} aria-label="Patient link" />
          <div className="row-end flush"><button className="btn ghost" onClick={onClose}>Done</button><CopyLink inv={inv} /></div>
        </div>
      ) : (
        <form className="form-grid" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <label className="span2">Full name<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Date of birth<input type="date" required value={dob} onChange={(e) => setDob(e.target.value)} /></label>
          <p className="hint span2">The patient must enter the same email and date of birth to open the link.</p>
          <FormError error={add.error?.message ?? null} />
          <div className="span2 row-end flush"><button className="btn primary" disabled={add.isPending}>Add and get link</button></div>
        </form>
      )}
    </Modal>
  );
}

function Invitations() {
  const queries = useQueryClient();
  const { data: invites } = useQuery({ queryKey: ["invites"], queryFn: () => api<Invite[]>("/api/invites") });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/invites/${id}`, { method: "DELETE" }),
    onSuccess: () => queries.invalidateQueries({ queryKey: ["invites"] }),
  });
  if (!invites?.length) return null;
  return (
    <div className="card">
      <h2>Patient links</h2>
      <table className="table hover">
        <thead><tr><th>Patient</th><th>Email</th><th>Status</th><th className="r"><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {invites.map((inv) => (
            <tr key={inv.id}>
              <td><span className="person"><Avatar name={inv.name} />{inv.name}</span></td>
              <td className="muted">{inv.email}</td>
              <td>{inv.joined_at ? <span className="tag ok">Joined</span> : <span className="tag warn">Waiting</span>}</td>
              <td className="r"><div className="page-actions end">
                <CopyLink inv={inv} />
                <button className="btn ghost sm danger" aria-label={`Delete link for ${inv.name}`} onClick={() => { if (window.confirm(`Delete the link for ${inv.name}? It stops working. Any results are kept.`)) remove.mutate(inv.id); }}><Icon name="trash" /></button>
              </div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Patients() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const closeAdd = useCallback(() => setAdding(false), []);
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
      <div className="page-head"><div><h1>Patients</h1><p className="muted">Add a patient to get a link you can send them.</p></div>
        <button className="btn primary" onClick={() => setAdding(true)}><Icon name="plus" /> Add patient</button></div>
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
                    <td className="muted">{p.last_test ? fmtDate(p.last_test.started_at) : "No test yet"}</td>
                    <td className="r">{!p.last_test ? "—" : p.last_test.stage === "in_progress" ? <StageTag stage="in_progress" /> : <ScoreBadge score={p.last_test.adjusted_total} max={p.last_test.max_total} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty icon="users">{search ? "No patient with that name." : "No patients yet. Press Add patient to invite one."}</Empty>}
        </div>
      </div>
      <Invitations />
      {adding && <AddPatient onClose={closeAdd} />}
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
        {p.sessions.length === 0 ? <Empty icon="file">No tests yet. Once {p.name} opens your link, they can start a test.</Empty> : <table className="table clickable">
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
        </table>}
      </div>
    </div>
  );
}
