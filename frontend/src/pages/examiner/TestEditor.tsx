// Designing a test: which tasks, in which order, and how it runs.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ErrorCard, FormError, Icon, Spinner } from "../../components/ui";
import { api, config } from "../../lib/api";
import { isStandardOrder, orderProblem } from "../../lib/format";
import type { TaskInfo, Template, TestSettings } from "../../lib/types";

const ALL = Array.from({ length: 13 }, (_, i) => i + 1);
const DEFAULTS: TestSettings = { voice_speed: "normal", extra_answer_seconds: 0, allow_skip: true, intro: "" };

export function TestEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queries = useQueryClient();
  const cfg = useQuery({ queryKey: ["config"], queryFn: config, staleTime: Infinity });
  const existing = useQuery({
    queryKey: ["template", id],
    queryFn: () => api<Template>(`/api/templates/${id}`),
    enabled: !!id,
  });

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tasks, setTasks] = useState<number[]>(ALL);
  const [settings, setSettings] = useState<TestSettings>(DEFAULTS);
  const [published, setPublished] = useState(false);

  useEffect(() => {
    const t = existing.data;
    if (!t) return;
    setName(t.name);
    setDescription(t.description ?? "");
    setTasks(t.tasks);
    setSettings({ ...DEFAULTS, ...t.settings });
    setPublished(t.published);
  }, [existing.data]);

  const save = useMutation({
    mutationFn: () => api<Template>(id ? `/api/templates/${id}` : "/api/templates", {
      method: id ? "PUT" : "POST",
      body: { name, description, tasks, settings, published },
    }),
    onSuccess: () => {
      queries.invalidateQueries({ queryKey: ["templates"] });
      queries.invalidateQueries({ queryKey: ["template", id] });
      navigate("/examiner/tests");
    },
  });

  if (cfg.error || existing.error) return <ErrorCard error={cfg.error ?? existing.error} />;
  if (!cfg.data || (id && !existing.data)) return <Spinner />;

  const info: Record<number, TaskInfo> = Object.fromEntries(cfg.data.tasks.map((t: TaskInfo) => [t.number, t]));
  const points = tasks.reduce((sum, n) => sum + info[n].max, 0);
  const count = `${tasks.length} task${tasks.length === 1 ? "" : "s"}`;
  const left = ALL.filter((n) => !tasks.includes(n));
  const problem = orderProblem(tasks);
  const usesCamera = tasks.some((n) => info[n].camera);

  const move = (i: number, by: number) => {
    const next = [...tasks];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setTasks(next);
  };
  const set = <K extends keyof TestSettings>(key: K, value: TestSettings[K]) => setSettings({ ...settings, [key]: value });

  return (
    <div className="page">
      <Link className="back" to="/examiner/tests"><Icon name="back" /> Test designs</Link>
      <div className="page-head"><div><h1>{id ? "Edit test" : "Design a test"}</h1>
        <p className="muted">Changes apply to new tests only. Tests already started keep their design.</p></div></div>

      <div className="builder">
        <div className="stack">
          <div className="card stack">
            <h2 style={{ margin: 0 }}>Details</h2>
            <label>Name<input required maxLength={200} value={name} placeholder="e.g. Memory follow-up" onChange={(e) => setName(e.target.value)} /></label>
            <label>Description<textarea rows={2} maxLength={1000} value={description} placeholder="Shown to the patient when choosing a test" onChange={(e) => setDescription(e.target.value)} /></label>
          </div>
          <div className="card stack">
            <h2 style={{ margin: 0 }}>Settings</h2>
            <label>Voice speed
              <select value={settings.voice_speed} onChange={(e) => set("voice_speed", e.target.value as TestSettings["voice_speed"])}>
                <option value="normal">Normal</option><option value="slow">Slow</option>
              </select>
            </label>
            <label>Extra seconds to start answering
              <input type="number" min={0} max={60} value={settings.extra_answer_seconds} onChange={(e) => set("extra_answer_seconds", Math.max(0, Math.min(60, +e.target.value)))} />
            </label>
            <label>Message before the test starts
              <textarea rows={3} maxLength={1000} value={settings.intro} placeholder="Optional" onChange={(e) => set("intro", e.target.value)} />
            </label>
            <label className="toggle"><input type="checkbox" checked={settings.allow_skip} onChange={(e) => set("allow_skip", e.target.checked)} />
              <span>Patients can skip tasks<small>A skipped task counts as 0.</small></span></label>
          </div>
          <div className="card">
            <label className="toggle"><input type="checkbox" checked={published} onChange={(e) => setPublished(e.target.checked)} />
              <span>Published<small>Patients who choose you can take this test.</small></span></label>
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head"><h2>Tasks in this test</h2><span className="tag brand">{count} · {points} point{points === 1 ? "" : "s"}</span></div>
            <ol className="order-list">
              {tasks.map((n, i) => (
                <li key={n}>
                  <span className="order-n">{i + 1}</span>
                  <span><b>{info[n].title}</b>{info[n].camera && <> <span className="tag">camera</span></>}<br /><small className="muted">{info[n].section} · {info[n].max} pt{info[n].max === 1 ? "" : "s"}</small></span>
                  <span className="order-actions">
                    <button className="icon-btn" aria-label={`Move ${info[n].title} up`} disabled={i === 0} onClick={() => move(i, -1)}><Icon name="up" /></button>
                    <button className="icon-btn" aria-label={`Move ${info[n].title} down`} disabled={i === tasks.length - 1} onClick={() => move(i, 1)}><Icon name="down" /></button>
                    <button className="icon-btn" aria-label={`Remove ${info[n].title}`} onClick={() => setTasks(tasks.filter((t) => t !== n))}><Icon name="trash" /></button>
                  </span>
                </li>
              ))}
            </ol>
          </div>
          {left.length > 0 && (
            <div className="card">
              <div className="card-head"><h2>Add tasks</h2><button className="btn sm" onClick={() => setTasks(ALL)}>Reset to standard</button></div>
              <ul className="order-list">
                {left.map((n) => (
                  <li key={n} style={{ gridTemplateColumns: "1fr auto" }}>
                    <span><b>{info[n].title}</b><br /><small className="muted">{info[n].description}</small></span>
                    <button className="icon-btn" aria-label={`Add ${info[n].title}`} onClick={() => setTasks([...tasks, n])}><Icon name="plus" /></button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!problem && !isStandardOrder(tasks) && (
            <div className="notice warn"><p>{tasks.length === 13
              ? "These tasks are in a different order from the standard MoCA, so the score may not compare directly with published norms."
              : `This is a partial test, scored out of ${points}. The 26-point cut-off and education point only apply to the full test.`}</p></div>
          )}
          {usesCamera && <p className="hint">Tasks marked camera need a webcam on the patient's device.</p>}
        </div>
      </div>

      <div className="review-bar">
        <span>{problem ?? `${count} · out of ${points} point${points === 1 ? "" : "s"}`}</span>
        <button className="btn white" disabled={!!problem || !name.trim() || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save test"}</button>
      </div>
      <FormError error={save.error?.message ?? null} />
    </div>
  );
}
