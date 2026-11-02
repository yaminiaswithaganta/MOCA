import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate } from "react-router";
import { ExaminerForm, PatientForm } from "../components/ProfileForms";
import { FormError } from "../components/ui";
import { api } from "../lib/api";
import { examinerProfile, patientProfile, useAuth } from "../lib/auth";
import type { Me } from "../lib/types";

export function Profile() {
  const { me, session } = useAuth();
  const queries = useQueryClient();
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: (body: object) => api<Me>("/api/me/profile", { method: "PUT", body }),
    onMutate: () => setSaved(false),
    onSuccess: (data) => {
      queries.setQueryData(["me", session!.user.id], data);
      setSaved(true);
    },
  });
  const feedback = (
    <>
      <FormError error={save.error?.message ?? null} />
      {saved && <p className="form-note span2" role="status">Saved.</p>}
    </>
  );

  if (me?.role === "admin") return <Navigate to="/admin" replace />;

  return (
    <div className="page narrow">
      <div><h1>My details</h1><p className="muted">{me?.email}</p></div>
      <div className="card">
        {me?.role === "patient"
          ? <PatientForm initial={patientProfile(me)} submitLabel="Save changes" busy={save.isPending} onSubmit={(d) => save.mutate(d)}>{feedback}</PatientForm>
          : <ExaminerForm initial={examinerProfile(me)} submitLabel="Save changes" busy={save.isPending} onSubmit={(d) => save.mutate(d)}>{feedback}</ExaminerForm>}
      </div>
    </div>
  );
}
