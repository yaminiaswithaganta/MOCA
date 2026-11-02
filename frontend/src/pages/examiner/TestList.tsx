import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { Empty, ErrorCard, FormError, Icon, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import type { Template } from "../../lib/types";

export function TestList() {
  const queries = useQueryClient();
  const { data: tests, error } = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/api/templates") });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/templates/${id}`, { method: "DELETE" }),
    onSuccess: () => queries.invalidateQueries({ queryKey: ["templates"] }),
  });
  if (error) return <ErrorCard error={error} />;
  if (!tests) return <Spinner />;

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Test designs</h1><p className="muted">Patients who choose you can take any published test.</p></div>
        <Link className="btn primary" to="/examiner/tests/new"><Icon name="plus" /> Design a test</Link>
      </div>
      <FormError error={remove.error?.message ?? null} />
      {tests.length ? (
        <div className="template-list">
          {tests.map((t) => (
            <div className="card template-card" key={t.id}>
              <div className="row">
                <span className={`tag ${t.published ? "ok" : ""}`}>{t.published ? "Published" : "Draft"}</span>
                {t.standard && <span className="tag brand">Standard order</span>}
              </div>
              <h2>{t.name}</h2>
              {t.description && <p className="muted">{t.description}</p>}
              <p className="small">{t.tasks.length} task{t.tasks.length === 1 ? "" : "s"} · out of {t.max_points} points</p>
              <div className="row">
                <Link className="btn sm" to={`/examiner/tests/${t.id}`}><Icon name="edit" /> Edit</Link>
                <button className="btn ghost sm danger" onClick={() => { if (window.confirm(`Delete "${t.name}"? Past results are kept.`)) remove.mutate(t.id); }}><Icon name="trash" /> Delete</button>
              </div>
            </div>
          ))}
        </div>
      ) : <div className="card"><Empty icon="file">No tests yet. <Link to="/examiner/tests/new">Design your first test.</Link></Empty></div>}
    </div>
  );
}
