// The admin portal: adding people, deactivating them, and sending new sign-in links.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { ExaminerForm, PatientForm } from "../../components/ProfileForms";
import { Avatar, Empty, ErrorCard, FormError, Icon, Menu, Modal, Spinner, StatCard } from "../../components/ui";
import { api } from "../../lib/api";
import type { AdminUser } from "../../lib/types";

type Kind = "examiner" | "patient";

function AddPerson({ kind, onClose, onAdded }: { kind: Kind; onClose: () => void; onAdded: (u: AdminUser) => void }) {
  const [email, setEmail] = useState("");
  const add = useMutation({
    mutationFn: (details: object) => api<AdminUser>(`/api/admin/${kind}s`, { method: "POST", body: { ...details, email } }),
    onSuccess: onAdded,
  });
  const extras = (
    <>
      <label className="span2">Email<input type="email" required autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <p className="hint span2">They'll get an email with a link to choose a password.</p>
      <FormError error={add.error?.message ?? null} />
    </>
  );
  const submit = (details: object) => add.mutate(details);
  return (
    <Modal title={`Add ${kind === "examiner" ? "an examiner" : "a patient"}`} onClose={onClose}>
      {kind === "examiner"
        ? <ExaminerForm submitLabel="Add and send invitation" busy={add.isPending} onSubmit={submit}>{extras}</ExaminerForm>
        : <PatientForm submitLabel="Add and send invitation" busy={add.isPending} onSubmit={submit}>{extras}</PatientForm>}
    </Modal>
  );
}

export function AdminHome() {
  const queries = useQueryClient();
  const [kind, setKind] = useState<Kind>("examiner");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const closeAdd = useCallback(() => setAdding(false), []);

  useEffect(() => {
    const t = setTimeout(() => setQuery(search), 200);
    return () => clearTimeout(t);
  }, [search]);

  const stats = useQuery({
    queryKey: ["admin-stats"],
    queryFn: () => api<{ examiners: number; patients: number; deactivated: number }>("/api/admin/stats"),
  });
  const people = useQuery({
    queryKey: ["admin-users", kind, query],
    queryFn: () => api<AdminUser[]>(`/api/admin/users?role=${kind}&q=${encodeURIComponent(query)}`),
    placeholderData: keepPreviousData,       // the list stays put while a search loads
  });
  const refresh = () => {
    queries.invalidateQueries({ queryKey: ["admin-users"] });
    queries.invalidateQueries({ queryKey: ["admin-stats"] });
  };
  const act = useMutation({
    mutationFn: ({ u, action }: { u: AdminUser; action: string }) => api(`/api/admin/users/${u.id}/${action}`, { method: "POST" }),
    onMutate: () => setNotice(null),
    onSuccess: (_, { u, action }) => {
      refresh();
      setNotice(action === "send-link" ? `Sign-in link sent to ${u.email}.` : `${u.name} ${action === "deactivate" ? "deactivated" : "reactivated"}.`);
    },
  });

  if (stats.error) return <ErrorCard error={stats.error} />;

  const deactivate = (u: AdminUser) => {
    const waiting = u.awaiting_review ? ` ${u.awaiting_review} test(s) are waiting for their review and will stay unreviewed.` : "";
    if (window.confirm(`Deactivate ${u.name}? They lose access straight away. Their records are kept.${waiting}`)) act.mutate({ u, action: "deactivate" });
  };

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>People</h1><p className="muted">Add and manage accounts. Test results stay private to examiners and patients.</p></div>
        <button className="btn primary" onClick={() => setAdding(true)}><Icon name="plus" /> Add {kind}</button>
      </div>

      <section className="stat-grid three">
        <StatCard icon="shield" value={stats.data?.examiners ?? "—"} label="Active examiners" />
        <StatCard icon="users" value={stats.data?.patients ?? "—"} label="Active patients" tone="ok" />
        <StatCard icon="ban" value={stats.data?.deactivated ?? "—"} label="Deactivated" tone="quiet" />
      </section>

      {notice && <p className="form-note" role="status">{notice}</p>}
      <FormError error={act.error?.message ?? null} />

      <div className="card">
        <div className="card-head">
          <div className="tabs" role="tablist">
            {(["examiner", "patient"] as Kind[]).map((k) => (
              <button key={k} role="tab" aria-selected={kind === k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{k === "examiner" ? "Examiners" : "Patients"}</button>
            ))}
          </div>
          <div className="search-wrap"><Icon name="search" />
            <input className="search" aria-label="Search by name or email" placeholder="Search by name or email…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
        {people.error ? <p className="error-text">{people.error.message}</p> : !people.data ? <Spinner /> : people.data.length ? (
          <table className="table hover">
            <thead><tr><th>Name</th><th>Email</th><th>Tests</th><th>Status</th><th className="r"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {people.data.map((u) => (
                <tr key={u.id}>
                  <td><span className="person"><Avatar name={u.name} /><span>{u.name}{u.details && <><br /><small className="muted">{u.details}</small></>}</span></span></td>
                  <td className="muted">{u.email}</td>
                  <td>{u.tests}</td>
                  <td><span className={`tag ${u.active ? "ok" : "off"}`}>{u.active ? "Active" : "Deactivated"}</span></td>
                  <td className="r">
                    <Menu label={`Actions for ${u.name}`}>
                      {(close) => u.active ? (
                        <>
                          <button role="menuitem" className="menu-item" onClick={() => { close(); act.mutate({ u, action: "send-link" }); }}><Icon name="mail" /> Send sign-in link</button>
                          <button role="menuitem" className="menu-item danger" onClick={() => { close(); deactivate(u); }}><Icon name="ban" /> Deactivate</button>
                        </>
                      ) : <button role="menuitem" className="menu-item" onClick={() => { close(); act.mutate({ u, action: "reactivate" }); }}><Icon name="check" /> Reactivate</button>}
                    </Menu>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty icon="users">{search ? "Nobody matches that search." : `No ${kind}s yet.`}</Empty>}
      </div>
      {adding && (
        <AddPerson kind={kind} onClose={closeAdd} onAdded={(u) => {
          closeAdd();
          refresh();
          setNotice(`${u.name} added. An invitation is on its way to ${u.email}.`);
        }} />
      )}
    </div>
  );
}
