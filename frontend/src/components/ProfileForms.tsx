// The details forms used in first-time setup and on the "My details" page.

import { useState, type FormEvent, type ReactNode } from "react";

export interface PatientDetails {
  name: string;
  date_of_birth: string | null;
  sex: string | null;
  education_years: number | null;
}

export interface ExaminerDetails {
  name: string;
  title: string | null;
  organization: string | null;
}

interface FormProps<T> {
  initial?: Partial<T>;
  submitLabel: string;
  busy?: boolean;
  onSubmit: (data: T) => void;
  children?: ReactNode;
}

export function PatientForm({ initial = {}, submitLabel, busy, onSubmit, children }: FormProps<PatientDetails>) {
  const [name, setName] = useState(initial.name ?? "");
  const [dob, setDob] = useState(initial.date_of_birth ?? "");
  const [sex, setSex] = useState(initial.sex ?? "");
  const [edu, setEdu] = useState(initial.education_years?.toString() ?? "");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ name: name.trim(), date_of_birth: dob || null, sex: sex || null, education_years: edu === "" ? null : parseInt(edu, 10) });
  };

  return (
    <form className="form-grid" onSubmit={submit}>
      <label className="span2">Full name<input required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Date of birth<input required type="date" autoComplete="bday" value={dob} onChange={(e) => setDob(e.target.value)} /></label>
      <label>Sex
        <select value={sex} onChange={(e) => setSex(e.target.value)}>
          <option value="">Prefer not to say</option>
          {["Female", "Male", "Other"].map((o) => <option key={o}>{o}</option>)}
        </select>
      </label>
      <label className="span2">Years of education
        <input required type="number" min="0" max="40" inputMode="numeric" value={edu} onChange={(e) => setEdu(e.target.value)} />
      </label>
      <p className="hint span2">Count every year of school and study after it. It's used to adjust the score fairly: 12 years or less adds 1 point.</p>
      {children}
      <div className="span2 row-end flush"><button className="btn primary" disabled={busy}>{busy ? "Saving…" : submitLabel}</button></div>
    </form>
  );
}

export function ExaminerForm({ initial = {}, submitLabel, busy, onSubmit, children }: FormProps<ExaminerDetails>) {
  const [name, setName] = useState(initial.name ?? "");
  const [title, setTitle] = useState(initial.title ?? "");
  const [org, setOrg] = useState(initial.organization ?? "");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ name: name.trim(), title: title.trim() || null, organization: org.trim() || null });
  };

  return (
    <form className="form-grid" onSubmit={submit}>
      <label className="span2">Full name<input required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Title<input value={title} placeholder="e.g. Neuropsychologist" onChange={(e) => setTitle(e.target.value)} /></label>
      <label>Organisation<input autoComplete="organization" value={org} onChange={(e) => setOrg(e.target.value)} /></label>
      <p className="hint span2">Patients see these details when they choose an examiner.</p>
      {children}
      <div className="span2 row-end flush"><button className="btn primary" disabled={busy}>{busy ? "Saving…" : submitLabel}</button></div>
    </form>
  );
}
