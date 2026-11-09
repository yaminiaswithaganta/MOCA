// First sign-in: a new account fills in its details and becomes a patient.
// Examiners don't come through here: an administrator adds them.

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { homeOf } from "../components/Layout";
import { PatientForm, type PatientDetails } from "../components/ProfileForms";
import { FormError, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { Me } from "../lib/types";
import { AuthShell } from "./auth/AuthPages";

export function Onboarding() {
  const { session, me, loading, signOut } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const queries = useQueryClient();
  const navigate = useNavigate();

  if (loading) return <Spinner />;
  if (!session) return <Navigate to="/login" replace />;
  if (me?.role) return <Navigate to={homeOf(me.role)} replace />;

  const finish = async (details: PatientDetails) => {
    setBusy(true);
    setError(null);
    try {
      const done = await api<Me>("/api/me/onboard", { method: "POST", body: details });
      queries.setQueryData(["me", session.user.id], done);
      navigate(homeOf(done.role!), { replace: true });
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <h2>Your details</h2>
      <p className="muted" style={{ margin: 0 }}>Your examiner uses these to score your test fairly.</p>
      <PatientForm submitLabel="Finish" busy={busy} onSubmit={finish}>
        <FormError error={error} />
      </PatientForm>
      <p className="hint">Are you an examiner? Your administrator creates your account and gives you your sign-in details.</p>
      <div className="auth-links"><span /><button className="link-btn" onClick={signOut}>Sign out</button></div>
    </AuthShell>
  );
}
