// Choosing an examiner and a test, then agreeing to the recording.

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Avatar, Empty, ErrorCard, FormError, Icon, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { patientProfile, useAuth } from "../../lib/auth";
import type { ExaminerChoice, PatientSession, Template } from "../../lib/types";

const minutes = (t: Template) => Math.max(5, Math.round(t.tasks.length * 1.5));

export function StartTest() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [examiner, setExaminer] = useState<ExaminerChoice | null>(null);
  const [test, setTest] = useState<Template | null>(null);
  const [consent, setConsent] = useState(false);
  const { data: examiners, error } = useQuery({
    queryKey: ["examiners"],
    queryFn: () => api<ExaminerChoice[]>("/api/examiners"),
  });
  const start = useMutation({
    mutationFn: () => api<PatientSession>("/api/sessions", {
      method: "POST",
      body: { template_id: test!.id, consent, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
    }),
    onSuccess: (s) => navigate(`/patient/test/${s.id}`),
  });

  useEffect(() => {
    if (examiners?.length === 1 && !examiner) {        // invited by one examiner: nothing to choose
      setExaminer(examiners[0]);
      setTest(examiners[0].tests.length === 1 ? examiners[0].tests[0] : null);
    }
  }, [examiners, examiner]);

  if (error) return <ErrorCard error={error} />;
  if (!examiners) return <Spinner />;

  const chooseExaminer = (e: ExaminerChoice) => {
    setExaminer(e);
    setTest(e.tests.length === 1 ? e.tests[0] : null);
  };

  if (patientProfile(me)?.education_years == null) {
    return (
      <div className="page narrow"><div className="notice warn">
        <h2>One detail is missing</h2>
        <p>Please add your years of education first. It's needed to work out your score fairly.</p>
        <p style={{ marginTop: ".7rem" }}><Link to="/profile">Update my details</Link></p>
      </div></div>
    );
  }

  return (
    <div className="page narrow">
      <div><h1>Start a test</h1><p className="muted">Choose your examiner. They'll review your answers and share your result with you.</p></div>

      <div className="card">
        <h2><span className="step">1</span>Your examiner</h2>
        {examiners.length ? (
          <div className="choice-list">
            {examiners.map((e) => (
              <button key={e.id} className={`choice ${examiner?.id === e.id ? "on" : ""}`} aria-pressed={examiner?.id === e.id} onClick={() => chooseExaminer(e)}>
                <span className="choice-row"><Avatar name={e.name} />
                  <span><b>{e.name}</b><br /><small>{[e.title, e.organization].filter(Boolean).join(" · ") || "Examiner"}</small></span>
                </span>
              </button>
            ))}
          </div>
        ) : <Empty icon="users">No examiners are available yet. Please check back soon.</Empty>}
      </div>

      {examiner && (
        <div className="card">
          <h2><span className="step">2</span>Your test</h2>
          <div className="choice-list">
            {examiner.tests.map((t) => (
              <button key={t.id} className={`choice ${test?.id === t.id ? "on" : ""}`} aria-pressed={test?.id === t.id} onClick={() => setTest(t)}>
                <b>{t.name}</b>
                <small>{t.description ?? `${t.tasks.length} tasks`} · about {minutes(t)} minutes</small>
              </button>
            ))}
          </div>
        </div>
      )}

      {test && (
        <div className="card checklist">
          <h2><span className="step">3</span>Before you begin</h2>
          <ul>
            <li><span className="check-ico"><Icon name="quiet" /></span><span><b>A quiet room</b><small>No TV or radio, and only you talking.</small></span></li>
            <li><span className="check-ico"><Icon name="sun" /></span><span><b>Good light</b><small>Light on the paper, not behind it, for the drawings.</small></span></li>
            <li><span className="check-ico"><Icon name="pen" /></span><span><b>Paper and a dark pen</b><small>For drawing the cube and the clock.</small></span></li>
          </ul>
          <Link className="btn" to="/check"><Icon name="mic" /> Check microphone &amp; camera</Link>
          <label className="consent" style={{ marginTop: "1.2rem" }}>
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>I agree that my voice and the photos of my drawings are recorded, stored securely and shared with {examiner?.name} to assess this test. I understand this is a screening, not a diagnosis.</span>
          </label>
          <FormError error={start.error?.message ?? null} />
          <div className="row-end">
            <button className="btn primary lg" disabled={!consent || start.isPending} onClick={() => start.mutate()}><Icon name="play" /> Begin test</button>
          </div>
        </div>
      )}
    </div>
  );
}
