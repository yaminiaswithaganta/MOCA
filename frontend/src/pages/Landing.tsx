// The public front page.

import { useState } from "react";
import { Link } from "react-router";
import { Brand } from "../components/Layout";
import { DOMAINS, DOMAIN_OF, Icon } from "../components/ui";

// The trail-making path (Task 1), drawing itself in the product preview
const TRAIL: [string, number, number][] = [["1", 1, 6], ["A", 3, 8.5], ["2", 2, 3.5], ["B", 4.5, 6.5], ["3", 3.5, 1],
  ["C", 6.5, 3], ["4", 5.5, 8.5], ["D", 8, 5.5], ["5", 7.5, 1.5], ["E", 9, 8]];

function TrailPreview() {
  const X = (x: number) => 20 + x * 44, Y = (y: number) => 380 - y * 40;
  return (
    <svg viewBox="0 0 440 400" aria-hidden="true">
      <polyline points={TRAIL.map(([, x, y]) => `${X(x)},${Y(y)}`).join(" ")} className="trail-draw" pathLength={1} />
      {TRAIL.map(([k, x, y], i) => (
        <g key={k} className={`trail-node${k === "E" ? " last" : ""}`} style={{ animationDelay: `${0.2 + i * 0.32}s` }}>
          <circle cx={X(x)} cy={Y(y)} r="19" /><text x={X(x)} y={Y(y) + 6}>{k}</text>
        </g>
      ))}
    </svg>
  );
}

// "30 points across 7 areas": donut + list, hovering one highlights the other
function Areas() {
  const [active, setActive] = useState<string | null>(null);
  const d = active ? DOMAIN_OF[active] : null;
  const r = 78, C = 2 * Math.PI * r, gap = 3;
  let at = 0;
  return (
    <div className={`areas ${d ? "has-active" : ""}`}>
      <div className="areas-left">
        <div className="donut-wrap">
          <svg className="donut" viewBox="0 0 200 200" aria-hidden="true">
            {DOMAINS.map((x) => {
              const len = (C * x.max) / 30;
              const offset = -at;
              at += len;
              return <circle key={x.key} className={`seg ${active === x.key ? "on" : ""}`} cx="100" cy="100" r={r} stroke={x.color}
                strokeDasharray={`${(len - gap).toFixed(2)} ${(C - len + gap).toFixed(2)}`} strokeDashoffset={offset.toFixed(2)}
                onMouseEnter={() => setActive(x.key)} onMouseLeave={() => setActive(null)} />;
            })}
          </svg>
          <div className="donut-center">
            <b style={{ color: d?.color }}>{d ? d.max : 30}</b>
            <span>{d ? `${d.short} · ${Math.round((d.max / 30) * 100)}%` : "points in total"}</span>
          </div>
        </div>
        <div className="normal-chip"><i />26 or more is in the normal range</div>
      </div>
      <ul className="area-list">
        {DOMAINS.map((x) => (
          <li key={x.key} className={`area-row ${active === x.key ? "on" : ""}`} style={{ "--c": x.color } as React.CSSProperties} tabIndex={0}
            onMouseEnter={() => setActive(x.key)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(x.key)} onBlur={() => setActive(null)}>
            <span className="area-ico"><Icon name={x.icon} /></span>
            <span className="area-text"><b>{x.label}</b><small>{x.what}</small></span>
            <span className="pips" aria-hidden="true">{Array.from({ length: x.max }, (_, i) => <i key={i} />)}</span>
            <span className="area-pts">{x.max}<small>pts</small></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const ROLES = [
  ["mic", "For patients", "Choose your examiner and answer out loud from home. Instructions are read to you, and drawings are shown to your camera."],
  ["edit", "For examiners", "Design the test you need, review each answer with its recording, correct scores where needed and release the result."],
  ["shield", "For clinics", "Administrators add and manage accounts. Results stay private to the patient and their examiner."],
];

export function Landing() {
  return (
    <div className="public">
      <header className="public-nav">
        <div>
          <Brand to="/" />
          <div className="row">
            <Link className="btn ghost" to="/login">Sign in</Link>
            <Link className="btn primary" to="/signup">Create account</Link>
          </div>
        </div>
      </header>
      <main style={{ padding: 0 }}>
        <div className="public-wrap lp-hero">
          <div>
            <span className="eyebrow">Montreal Cognitive Assessment</span>
            <h1 style={{ marginTop: ".6rem" }}>Cognitive screening, reviewed by a real examiner.</h1>
            <p>Patients take the MoCA by voice and camera. Answers are scored automatically, then checked by a qualified examiner before any result is shared.</p>
            <div className="row">
              <Link className="btn primary lg" to="/signup">Get started <Icon name="arrow" /></Link>
              <Link className="btn lg" to="/login">Sign in</Link>
            </div>
          </div>
          <div className="lp-sheet" aria-hidden="true">
            <div className="lp-sheet-top">
              <div><div className="eyebrow">Task 1 of 13</div><b>Trail making</b></div>
              <span className="tag brand"><Icon name="mic" /> Listening</span>
            </div>
            <div className="lp-trail"><TrailPreview /></div>
            <div className="lp-steps"><span>Speak</span><span>Show</span><span>Review</span></div>
          </div>
        </div>

        <section className="lp-section">
          <div className="public-wrap">
            <h2>Built around the people using it</h2>
            <p>Three roles, each seeing only what they need.</p>
            <div className="lp-roles">
              {ROLES.map(([ic, title, text]) => (
                <div className="lp-role" key={title}>
                  <span className="stat-ico"><Icon name={ic} /></span>
                  <h3>{title}</h3><p>{text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section">
          <div className="public-wrap">
            <h2>30 points across 7 areas</h2>
            <p>The MoCA looks at memory, attention, language and more. Point at an area to see how much it counts.</p>
            <Areas />
          </div>
        </section>
      </main>
      <footer className="public-foot"><div className="public-wrap">A screening tool, not a diagnosis. Results are reviewed by a qualified examiner.</div></footer>
    </div>
  );
}
