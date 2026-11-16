// Ask the manual: examiners ask how to give or score a task and get an answer from the MoCA manuals.

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { FormError, Icon } from "../../components/ui";
import { api } from "../../lib/api";

interface Source { n: number; source: string; page: number; text: string }
interface Answer { answer: string; sources: Source[] }
interface Turn { question: string; reply: Answer }

const EXAMPLES = [
  "How do I score the clock drawing?",
  "When does a patient get the extra point for education?",
  "How are serial 7s scored?",
  "What counts as a correct answer in delayed recall?",
];

function Reply({ turn }: { turn: Turn }) {
  return (
    <div className="card ask-turn">
      <p className="ask-q"><Icon name="user" /> {turn.question}</p>
      <div className="ask-a">{turn.reply.answer}</div>
      {turn.reply.sources.length > 0 && (
        <details className="ask-sources">
          <summary>Passages it read ({turn.reply.sources.length})</summary>
          {turn.reply.sources.map((s) => (
            <div key={s.n} className="ask-source">
              <b>[{s.n}] {s.source}, page {s.page}</b>
              <p>{s.text}</p>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

export function AskManual() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const ask = useMutation({
    mutationFn: (q: string) => api<Answer>("/api/manual/ask", { method: "POST", body: { question: q } }),
    onSuccess: (reply, q) => { setTurns((t) => [{ question: q, reply }, ...t]); setQuestion(""); },
  });

  const send = (q: string) => { if (q.trim().length >= 3 && !ask.isPending) ask.mutate(q.trim()); };

  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Ask the manual</h1>
          <p className="muted">Questions about giving and scoring the MoCA, answered from the official instruction manuals.</p>
        </div>
      </div>
      <div className="card">
        <form onSubmit={(e) => { e.preventDefault(); send(question); }}>
          <textarea rows={3} value={question} maxLength={1000} placeholder="e.g. How do I score the cube copy?"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(question); } }} />
          <FormError error={ask.error ? (ask.error as Error).message : null} />
          <div className="row-end">
            <button className="btn primary" disabled={ask.isPending || question.trim().length < 3}>
              {ask.isPending ? "Looking it up…" : <><Icon name="search" /> Ask</>}
            </button>
          </div>
        </form>
        {turns.length === 0 && (
          <div className="ask-examples">
            <p className="hint">Try one of these:</p>
            <div className="row">
              {EXAMPLES.map((q) => <button key={q} className="btn ghost sm" disabled={ask.isPending} onClick={() => send(q)}>{q}</button>)}
            </div>
          </div>
        )}
      </div>
      {turns.map((t, i) => <Reply key={turns.length - i} turn={t} />)}
      <p className="hint">Answers come only from the manuals and can still be wrong. Check the passages it quotes when it matters.</p>
    </div>
  );
}
