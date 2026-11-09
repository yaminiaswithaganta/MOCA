// The page a patient opens from their examiner's link: confirm details, get signed in.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Avatar, FormError, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import { supabase } from "../lib/supabase";
import type { ExaminerProfile } from "../lib/types";
import { AuthShell } from "./auth/AuthPages";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : `request failed (${res.status})`, res.status);
  return data;
}

export function Join() {
  const { token } = useParams();
  const navigate = useNavigate();
  const queries = useQueryClient();
  const info = useQuery({
    queryKey: ["join", token],
    queryFn: async () => {
      const res = await fetch(`/api/join/${token}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "This link isn't valid.");
      return data as { examiner: ExaminerProfile; joined: boolean };
    },
    retry: false,
  });
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [dob, setDob] = useState("");
  const [edu, setEdu] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ownAccount, setOwnAccount] = useState<string | null>(null);

  if (info.isLoading) return <Spinner />;
  if (info.error) {
    return (
      <AuthShell>
        <h2>This link isn't working</h2>
        <p className="muted" style={{ margin: 0 }}>{info.error.message}</p>
        <Link to="/login">Go to sign in</Link>
      </AuthShell>
    );
  }
  const examiner = info.data!.examiner;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ email: string; password?: string; sign_in?: boolean }>(`/api/join/${token}`, {
        name: name.trim(), email, date_of_birth: dob, education_years: edu === "" ? null : parseInt(edu, 10),
      });
      await supabase.auth.signOut();                     // never stay signed in as someone else
      queries.clear();
      if (r.sign_in) {
        setOwnAccount(r.email);
        setBusy(false);
        return;
      }
      const { error } = await supabase.auth.signInWithPassword({ email: r.email, password: r.password! });
      if (error) throw new Error(error.message);
      navigate("/patient/start", { replace: true });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  if (ownAccount) {
    return (
      <AuthShell>
        <h2>You already have an account</h2>
        <p className="muted" style={{ margin: 0 }}>You're now connected to {examiner.name}. Sign in with <b>{ownAccount}</b> and your own password to start your test.</p>
        <Link className="btn primary" to="/login">Sign in</Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <div className="person"><Avatar name={examiner.name} /><span><b>{examiner.name}</b><br /><small className="muted">{[examiner.title, examiner.organization].filter(Boolean).join(" · ") || "Examiner"}</small></span></div>
      <h2>{info.data!.joined ? "Welcome back" : "You're invited to a test"}</h2>
      <p className="muted" style={{ margin: 0 }}>Enter your details exactly as you gave them to {examiner.name}. You don't need a password: this link signs you in.</p>
      <form onSubmit={submit}>
        <label>Full name<input required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Date of birth<input type="date" required autoComplete="bday" value={dob} onChange={(e) => setDob(e.target.value)} /></label>
        <label>Years of education<input type="number" min="0" max="40" required inputMode="numeric" value={edu} onChange={(e) => setEdu(e.target.value)} /></label>
        <p className="hint">Count every year of school and study after it. It's used to score the test fairly.</p>
        <FormError error={error} />
        <button className="btn primary" disabled={busy}>{busy ? "Checking…" : "Continue"}</button>
      </form>
    </AuthShell>
  );
}
