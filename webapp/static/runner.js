// Runs a MoCA test in the browser: one screen per task, voice instructions,
// microphone / camera, and the score as soon as each task is done.

import { HandRaiseDetector } from "./hand.js";
import { camera, listen, mic, sleep, snapshot, speak, stopCamera, stopSpeaking } from "./media.js";
import { api, config, criteriaChips, esc, evidenceHtml, heardSummary } from "./ui.js";

class Skipped extends Error {}

// ---------------------------------------------------------------- stage
// One task's screen: header, main area, status line, buttons. Every wait goes
// through the stage so "Skip task" can interrupt it.
class Stage {
  constructor(root, info) {
    this.root = root;
    this.info = info;
    this.cleanups = [];
    this.currentListen = null;
    this._skip = null;
    this.skipped = new Promise((_, rej) => { this._skip = rej; });
    this.skipped.catch(() => {});
    root.innerHTML = `
      <div class="stage">
        <div class="stage-head">
          <div>
            <div class="eyebrow">Task ${info.index} of ${info.count} · ${esc(info.section)}</div>
            <h1>${esc(info.title)}</h1>
          </div>
          <div class="stage-actions">
            <button class="btn ghost" data-act="skip">Skip task</button>
            <button class="btn ghost" data-act="end">End test</button>
          </div>
        </div>
        <div class="progress"><div style="width:${((info.index - 1) / info.count) * 100}%"></div></div>
        <div class="stage-main"></div>
        <div class="stage-foot">
          <div class="listen-box" hidden>
            <div class="mic-dot"><span></span></div>
            <div class="listen-text"><div class="listen-label">Listening…</div><div class="heard"></div></div>
            <button class="btn" data-act="done">Done answering</button>
          </div>
          <div class="status"></div>
        </div>
      </div>`;
    this.main = root.querySelector(".stage-main");
    this.statusEl = root.querySelector(".status");
    this.listenBox = root.querySelector(".listen-box");
    this.heardEl = root.querySelector(".heard");
    root.querySelector('[data-act="skip"]').onclick = () => this.skip();
    root.querySelector('[data-act="end"]').onclick = () => {
      if (confirmInline(root, "End the test now? Tasks not done count as 0.")) this.skip("end");
    };
    root.querySelector('[data-act="done"]').onclick = () => this.currentListen && this.currentListen.stop();
  }

  skip(kind = "skip") {
    stopSpeaking();
    if (this.currentListen) this.currentListen.cancel();
    this._skip(new Skipped(kind));
  }

  onCleanup(fn) { this.cleanups.push(fn); }
  cleanup() { this.cleanups.forEach((f) => { try { f(); } catch {} }); this.cleanups = []; }

  race(p) { return Promise.race([p, this.skipped]); }
  wait(ms) { return this.race(sleep(ms)); }

  show(html) { this.main.innerHTML = html; }
  status(text, kind = "") {
    this.statusEl.textContent = text || "";
    this.statusEl.className = "status " + kind;
  }

  /** Show `text` as the instruction and read it aloud. */
  async say(text, { show = true } = {}) {
    if (show) this.status("");
    await this.race(speak(text));
  }

  /** Record one spoken answer for (task, step). Resolves with the server's "done" message. */
  async listen(task, step, { onToken, label = "Listening…" } = {}) {
    this.heardEl.textContent = "";
    this.listenBox.querySelector(".listen-label").textContent = "Getting ready…";
    this.listenBox.hidden = false;
    const meter = this.listenBox.querySelector(".mic-dot span");
    const anim = setInterval(() => { meter.style.transform = `scale(${1 + Math.min(1.5, mic.level * 6)})`; }, 60);
    const heard = [];
    const h = listen(this.info.sessionId, task, step, {
      onReady: () => { this.listenBox.querySelector(".listen-label").textContent = label; },
      onHeard: (t) => { heard.push(t); this.heardEl.textContent = `“${heard.join(" ")}”`; },
      onStatus: (t, type) => this.status(t, type === "reminder" ? "warn" : ""),
      onToken,
    });
    this.currentListen = h;
    try {
      return await this.race(h.promise);
    } finally {
      clearInterval(anim);
      this.currentListen = null;
      this.listenBox.hidden = true;
      this.status("");
    }
  }

  async finishSpoken(task) {
    this.status("Scoring…");
    return this.race(api(`/api/sessions/${this.info.sessionId}/tasks/${task}/finish`, { method: "POST" }));
  }
}

function confirmInline(_root, msg) {
  return window.confirm(msg);
}

function big(text, sub = "") {
  return `<div class="center-block"><div class="big-word">${esc(text)}</div>${sub ? `<p class="lead">${esc(sub)}</p>` : ""}</div>`;
}
function lead(text, extra = "") {
  return `<div class="center-block"><p class="instruction">${esc(text)}</p>${extra}</div>`;
}

// ---------------------------------------------------------------- tasks
const FLOWS = {};

// Task 1 — trail making: the path appears on the diagram while it is spoken
FLOWS[1] = async (st, cfg) => {
  const nodes = cfg.t1.nodes, correct = cfg.t1.correct;
  const X = (x) => 40 + x * 52, Y = (y) => 40 + (10 - y) * 40;
  const circles = Object.entries(nodes).map(([k, [x, y]]) =>
    `<g class="node" data-k="${k}"><circle cx="${X(x)}" cy="${Y(y)}" r="22"/><text x="${X(x)}" y="${Y(y) + 7}">${k}</text></g>`).join("");
  st.show(`<div class="trail-wrap">
      <svg class="trail" viewBox="0 0 600 480"><defs>
        <marker id="ah-ok" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="ah ok"/></marker>
        <marker id="ah-no" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="ah no"/></marker>
      </defs><g class="arrows"></g>${circles}</svg>
      <p class="lead">Say the path out loud: 1 → A → 2 → … keep alternating to the end.</p></div>`);
  const svg = st.main.querySelector("svg"), arrows = svg.querySelector(".arrows");
  let path = [];
  const draw = (seq) => {
    arrows.innerHTML = "";
    svg.querySelectorAll(".node").forEach((n) => n.classList.remove("ok", "no"));
    seq.forEach((tok, i) => {
      const ok = tok === correct[i];
      const n = svg.querySelector(`.node[data-k="${tok}"]`);
      if (n) n.classList.add(ok ? "ok" : "no");
      if (i === 0 || !nodes[tok] || !nodes[seq[i - 1]]) return;
      const [x1, y1] = nodes[seq[i - 1]], [x2, y2] = nodes[tok];
      const ax = X(x1), ay = Y(y1), bx = X(x2), by = Y(y2), d = Math.hypot(bx - ax, by - ay) || 1;
      const ux = (bx - ax) / d, uy = (by - ay) / d;
      arrows.insertAdjacentHTML("beforeend",
        `<line x1="${ax + ux * 24}" y1="${ay + uy * 24}" x2="${bx - ux * 26}" y2="${by - uy * 26}" class="${ok ? "ok" : "no"}" marker-end="url(#ah-${ok ? "ok" : "no"})"/>`);
    });
  };
  await st.say(cfg.speech[1]);
  const done = await st.listen(1, "path", {
    label: "Listening — say the path",
    onToken: (tok) => { if (path[path.length - 1] !== tok) { path.push(tok); draw(path); } },
  });
  if (done.spoken_sequence) draw(done.spoken_sequence);
  return st.finishSpoken(1);
};

// Tasks 2 and 3 — drawing held up to the camera, photo after a 10 s countdown
async function photoTask(st, cfg, number) {
  const isCube = number === 2;
  st.show(`<div class="photo-task">
      ${isCube ? `<figure class="ref"><img src="/api/reference-cube.png" alt="Cube to copy"><figcaption>Copy this cube</figcaption></figure>` :
                 `<div class="ref clock-ref"><div class="clock-time">11:10</div><p>Draw a clock with all the numbers.<br>Set the hands to <b>ten past eleven</b>.</p></div>`}
      <div class="cam">
        <video autoplay muted playsinline></video>
        <div class="countdown" hidden></div>
        <img class="still" hidden alt="">
      </div>
    </div>
    <div class="photo-controls">
      <button class="btn primary" data-act="count">Start 10-second countdown</button>
      <button class="btn" data-act="now">Take photo now</button>
      <button class="btn primary" data-act="use" hidden>Use this photo</button>
      <button class="btn" data-act="retake" hidden>Retake</button>
      <span class="hint">Space bar also starts the countdown.</span>
    </div>`);
  const video = st.main.querySelector("video"), still = st.main.querySelector(".still");
  const cd = st.main.querySelector(".countdown");
  const btn = (a) => st.main.querySelector(`[data-act="${a}"]`);
  try {
    await camera(video);
  } catch (e) {
    st.status("Camera not available: " + e.message, "error");
    await st.skipped;
  }
  st.onCleanup(stopCamera);
  await st.say(cfg.speech[number]);

  for (;;) {
    // wait for the countdown or "take photo now"
    const how = await st.race(new Promise((resolve) => {
      btn("count").onclick = () => resolve("count");
      btn("now").onclick = () => resolve("now");
      const key = (e) => { if (e.code === "Space") { e.preventDefault(); document.removeEventListener("keydown", key); resolve("count"); } };
      document.addEventListener("keydown", key);
      st.onCleanup(() => document.removeEventListener("keydown", key));
    }));
    btn("count").disabled = btn("now").disabled = true;
    if (how === "count") {
      speak("Hold the drawing still.");
      cd.hidden = false;
      for (let s = 10; s > 0; s--) { cd.textContent = s; await st.wait(1000); }
      cd.hidden = true;
    }
    const blob = await snapshot(video);
    still.src = URL.createObjectURL(blob);
    still.hidden = false;
    btn("count").hidden = btn("now").hidden = true;
    btn("use").hidden = btn("retake").hidden = false;
    const choice = await st.race(new Promise((resolve) => {
      btn("use").onclick = () => resolve("use");
      btn("retake").onclick = () => resolve("retake");
    }));
    if (choice === "use") {
      btn("use").disabled = btn("retake").disabled = true;
      st.status("Scoring the drawing…");
      const fd = new FormData();
      fd.append("file", blob, "capture.png");
      return st.race(api(`/api/sessions/${st.info.sessionId}/tasks/${number}/photo`, { method: "POST", form: fd }));
    }
    still.hidden = true;
    btn("use").hidden = btn("retake").hidden = true;
    btn("count").hidden = btn("now").hidden = false;
    btn("count").disabled = btn("now").disabled = false;
  }
}
FLOWS[2] = (st, cfg) => photoTask(st, cfg, 2);
FLOWS[3] = (st, cfg) => photoTask(st, cfg, 3);

// Task 4 — naming
FLOWS[4] = async (st, cfg) => {
  st.show(lead(cfg.speech[4]));
  await st.say(cfg.speech[4]);
  const animals = cfg.t4.animals;
  for (let i = 0; i < animals.length; i++) {
    st.show(`<div class="center-block"><img class="animal" src="/images/${esc(animals[i].image)}" alt="">
             <p class="lead">Picture ${i + 1} of ${animals.length} — what is this animal?</p></div>`);
    const done = await st.listen(4, animals[i].key);
    st.status(done.heard ? `Answer recorded: “${done.heard}”` : "No answer recorded.");
    await st.wait(1500);
  }
  return st.finishSpoken(4);
};

// Task 5 — memory (two learning trials)
FLOWS[5] = async (st, cfg) => {
  const { words, trials, seconds_per_word } = cfg.t5;
  for (let t = 1; t <= trials; t++) {
    const intro = t === 1
      ? "Listen carefully. I will read you a list of words to remember. When I am done, say back as many words as you can remember, in any order."
      : "I am going to read the same list again. Say back as many words as you can remember, including words you said the first time.";
    st.show(lead(intro, `<p class="eyebrow">Trial ${t} of ${trials}</p>`));
    await st.say(intro);
    await st.wait(1000);
    for (const w of words) {
      const t0 = performance.now();
      st.show(big(w));
      await st.race(speak(w.toLowerCase()));
      await st.wait(Math.max(100, seconds_per_word * 1000 - (performance.now() - t0)));
    }
    st.show(lead("Now say ALL the words you remember, in any order."));
    await st.say("Now say all the words you remember.");
    const done = await st.listen(5, `trial${t}`);
    st.status(done.heard ? `Recorded: “${done.heard}”` : "Nothing recorded.");
    await st.wait(2000);
  }
  st.show(lead("Please remember these words. You will be asked to recall them later."));
  await st.say("Please remember these words. You will be asked to recall them later.");
  return st.finishSpoken(5);
};

// Task 6 — digit span forward and backward
FLOWS[6] = async (st, cfg) => {
  for (const step of ["forward", "backward"]) {
    const text = cfg.speech[6][step];
    st.show(lead(text, `<p class="eyebrow">Numbers ${step}</p>`));
    await st.say(text);
    await st.wait(500);
    st.show(big("Listen…"));
    for (const d of cfg.t6[step]) {                 // one digit per second
      const t0 = performance.now();
      await st.race(speak(String(d)));
      await st.wait(Math.max(50, 1000 - (performance.now() - t0)));
    }
    st.show(big("Now say the numbers"));
    const done = await st.listen(6, step);
    st.status(done.heard ? `Heard: “${done.heard}”` : "No answer recorded.");
    await st.wait(1500);
  }
  return st.finishSpoken(6);
};

// Task 7 — raise a hand at every A (camera), or the examiner presses Space
FLOWS[7] = async (st, cfg) => {
  const { letters, interval_s } = cfg.t7;
  const sp = cfg.speech[7];
  st.show(`<div class="letters-task">
      <div class="cam small"><video autoplay muted playsinline></video><div class="hand-flag">hand down</div></div>
      <div class="letters-side"><p class="instruction"></p><div class="big-letter"></div>
        <button class="btn primary big-btn" data-act="raise" hidden>Hand raised (Space)</button></div>
    </div>`);
  const video = st.main.querySelector("video"), flag = st.main.querySelector(".hand-flag");
  const instr = st.main.querySelector(".instruction"), raiseBtn = st.main.querySelector('[data-act="raise"]');
  let mode = "camera", det = null, calibration = {};
  try {
    await camera(video);
    await sleep(500);
    det = new HandRaiseDetector(video);
  } catch (e) {
    mode = "keyboard";
    calibration = { reason: "camera could not be opened: " + e.message };
  }
  st.onCleanup(stopCamera);

  if (mode === "camera") {
    let ok = false;
    for (let attempt = 0; attempt < 2 && !ok; attempt++) {
      instr.textContent = attempt ? sp.retry : sp.sit;
      await st.say(attempt ? sp.retry : sp.sit);
      if (attempt) await st.say(sp.sit);
      const res = await st.race(det.calibrate());
      ok = res.ok;
      calibration = res.info;
    }
    if (!ok) mode = "keyboard";
  }
  if (mode === "keyboard") {
    st.main.querySelector(".cam").hidden = true;
    instr.textContent = "Examiner: press Space (or the button) every time the patient raises their hand.";
    st.status("The camera cannot see the hand clearly — examiner mode.", "warn");
    await st.wait(3000);
  }
  raiseBtn.hidden = false;
  instr.textContent = sp.task;
  await st.say(sp.task);
  await st.wait(1000);
  instr.textContent = "Listen… raise your hand at every A.";

  const letterTimes = [], raiseTimes = [], upSamples = [], trace = [];
  const t = () => performance.now() / 1000;
  const start = t() + 0.5;
  const manual = () => raiseTimes.push(t() - start);
  raiseBtn.onclick = manual;
  const key = (e) => { if (e.code === "Space") { e.preventDefault(); manual(); } };
  document.addEventListener("keydown", key);
  st.onCleanup(() => document.removeEventListener("keydown", key));

  let prevUp = false, i = 0;
  const end = start + letters.length * interval_s + 0.5;
  const bigLetter = st.main.querySelector(".big-letter");
  while (t() < end) {
    if (i < letters.length && t() >= start + i * interval_s) {
      const k = i;
      letterTimes[k] = t() - start + 0.25;            // updated when the voice really starts
      speak(letters[k], { rate: 0.9, onStart: (ms) => { letterTimes[k] = ms / 1000 - start; } });
      bigLetter.textContent = `${k + 1} / ${letters.length}`;
      i++;
    }
    if (mode === "camera") {
      const f = det.read();
      if (f) {
        const { up, value } = det.update(f);
        const ts = t() - start;
        upSamples.push([ts, up ? 1 : 0]);
        trace.push([+ts.toFixed(2), +value.toFixed(4), up ? 1 : 0]);
        if (up && !prevUp) raiseTimes.push(ts);
        prevUp = up;
        flag.textContent = up ? "HAND UP" : "hand down";
        flag.classList.toggle("up", up);
      }
    }
    await st.wait(40);
  }
  st.status("Scoring…");
  return st.race(api(`/api/sessions/${st.info.sessionId}/tasks/7/letters`, {
    method: "POST",
    body: { letter_times: letterTimes, raise_times: raiseTimes.sort((a, b) => a - b),
            up_samples: upSamples, mode, calibration, trace },
  }));
};

// Task 8 — serial 7s
FLOWS[8] = async (st, cfg) => {
  st.show(lead(cfg.speech[8]));
  await st.say(cfg.speech[8]);
  st.show(big("100 − 7 …", "Keep subtracting 7"));
  await st.listen(8, "serial7");
  speak("Thank you. You can stop.");
  return st.finishSpoken(8);
};

// Task 9 — sentence repetition
FLOWS[9] = async (st, cfg) => {
  st.show(lead(cfg.t9.intro));
  await st.say(cfg.t9.intro);
  await st.wait(800);
  for (let i = 0; i < cfg.t9.sentences.length; i++) {
    st.show(lead("Listen to the sentence.", `<p class="eyebrow">Sentence ${i + 1} of ${cfg.t9.sentences.length}</p>`));
    await st.say(cfg.t9.sentences[i]);
    st.show(lead("Now repeat the sentence."));
    await st.say("Now repeat the sentence.");
    const done = await st.listen(9, `sentence${i + 1}`);
    st.status(done.heard ? `Recorded: “${done.heard}”` : "Nothing recorded.");
    await st.wait(1500);
  }
  return st.finishSpoken(9);
};

// Task 10 — F-word fluency, one minute
FLOWS[10] = async (st, cfg) => {
  st.show(lead(cfg.t10.instruction));
  await st.say(cfg.t10.instruction);
  st.show(`<div class="center-block"><div class="big-word">F</div><div class="timer">${cfg.t10.seconds}</div>
           <p class="lead">Say as many words starting with F as you can.</p></div>`);
  const timer = st.main.querySelector(".timer");
  const t0 = performance.now();
  const iv = setInterval(() => { timer.textContent = Math.max(0, Math.ceil(cfg.t10.seconds - (performance.now() - t0) / 1000)); }, 250);
  st.onCleanup(() => clearInterval(iv));
  try {
    await st.listen(10, "fluency", { label: "Listening — one minute" });
  } finally {
    clearInterval(iv);
  }
  return st.finishSpoken(10);
};

// Task 11 — abstraction
FLOWS[11] = async (st, cfg) => {
  for (const item of cfg.t11.items) {
    st.show(lead(item.question, `<p class="eyebrow">${esc(item.label)}</p>`));
    await st.say(item.question);
    const done = await st.listen(11, item.key);
    st.status(done.heard ? `Recorded: “${done.heard}”` : "Nothing recorded.");
    await st.wait(1500);
  }
  return st.finishSpoken(11);
};

// Task 12 — delayed recall
FLOWS[12] = async (st, cfg) => {
  st.show(lead(cfg.t12.question));
  await st.say(cfg.t12.question);
  st.show(lead("Say the words you remember, out loud."));
  await st.listen(12, "recall");
  return st.finishSpoken(12);
};

// Task 13 — orientation
FLOWS[13] = async (st, cfg) => {
  for (let i = 0; i < cfg.t13.items.length; i++) {
    const item = cfg.t13.items[i];
    st.show(lead(item.question, `<p class="eyebrow">Question ${i + 1} of ${cfg.t13.items.length}</p>`));
    await st.say(item.question);
    const done = await st.listen(13, item.key);
    st.status(done.heard ? `Recorded: “${done.heard}”` : "Nothing recorded.");
    await st.wait(1200);
  }
  return st.finishSpoken(13);
};

// ---------------------------------------------------------------- result card
export function resultCardHtml(r, title) {
  const scored = r.max_score > 0;
  const tone = !r.completed ? "skipped" : !scored ? "" : r.score === r.max_score ? "full" : r.score === 0 ? "zero" : "";
  return `<div class="result-card ${tone}">
      <div class="result-top">
        <div><div class="eyebrow">${esc(title)}</div>
          <div class="score-big">${scored ? `${r.score}<span>/ ${r.max_score}</span>` : "Recorded"}</div></div>
        ${!r.completed ? `<span class="tag warn">Not completed</span>` : ""}
      </div>
      ${criteriaChips(r.criteria)}
      <p class="reason">${esc(r.reason)}</p>
      <div class="heard-summary">${heardSummary(r)}</div>
      ${evidenceHtml(r)}
    </div>`;
}

// ---------------------------------------------------------------- the test
let activeStage = null;
let abandoned = false;

/** Leaving the test page: stop the task in progress (it is not scored). */
export function abortTest() {
  abandoned = true;
  if (activeStage) activeStage.skip("abandon");
}

export async function runTest(root, sessionId, navigate) {
  abandoned = false;
  const cfg = await config();
  const session = await api(`/api/sessions/${sessionId}`);
  const byNum = Object.fromEntries(cfg.tasks.map((t) => [t.number, t]));
  const todo = session.tasks.filter((n) => !session.done_tasks.includes(n));

  // microphone permission up front, so the first task doesn't stall
  root.innerHTML = `<div class="center-block pad"><h1>Getting ready</h1><p class="lead">Allow the microphone${session.tasks.some((n) => byNum[n].camera) ? " and camera" : ""} when the browser asks.</p><div class="spinner"></div></div>`;
  try { await mic.init(); } catch (e) {
    root.innerHTML = `<div class="center-block pad"><h1>Microphone needed</h1><p class="lead">${esc(e.message)}</p><p>Allow microphone access for this page in the browser settings, then reload.</p></div>`;
    return;
  }
  for (;;) {
    const st = await api("/api/status");
    if (st.speech_ready) break;
    if (st.speech_error) {
      root.innerHTML = `<div class="center-block pad"><h1>Speech recogniser failed</h1><p>${esc(st.speech_error)}</p></div>`;
      return;
    }
    root.innerHTML = `<div class="center-block pad"><h1>Loading the speech recogniser…</h1><p class="lead">The first time, this downloads the model (a few hundred MB). After that it starts in seconds.</p><div class="spinner"></div></div>`;
    await sleep(1500);
  }

  for (let k = 0; k < todo.length; k++) {
    const n = todo[k];
    const info = { ...byNum[n], sessionId, index: session.tasks.indexOf(n) + 1, count: session.tasks.length };
    if (abandoned) return;
    const stage = new Stage(root, info);
    activeStage = stage;
    let result = null, ended = false;
    try {
      result = await FLOWS[n](stage, cfg);
    } catch (e) {
      if (e instanceof Skipped && e.message === "abandon") return;
      if (e instanceof Skipped) {
        ended = e.message === "end";
        result = await api(`/api/sessions/${sessionId}/tasks/${n}/skip`, { method: "POST" });
      } else {
        stage.cleanup();
        const again = await showError(root, info, e);
        if (again === "retry") { k--; continue; }
        result = await api(`/api/sessions/${sessionId}/tasks/${n}/skip`, { method: "POST" });
      }
    } finally {
      activeStage = null;
      stage.cleanup();
      stopSpeaking();
    }
    if (ended) break;
    const last = k === todo.length - 1;
    root.innerHTML = `<div class="after-task">${resultCardHtml(result, `Task ${n} · ${info.title}`)}
        <div class="row-end"><button class="btn primary" data-act="next">${last ? "See final score" : "Next task →"}</button></div></div>`;
    if (abandoned) return;
    await new Promise((r) => {
      const b = root.querySelector('[data-act="next"]');
      b.focus();
      b.onclick = r;
    });
  }
  root.innerHTML = `<div class="center-block pad"><h1>Adding up the score…</h1><div class="spinner"></div></div>`;
  await api(`/api/sessions/${sessionId}/finish`, { method: "POST" });
  stopCamera();
  navigate(`#/session/${sessionId}`);
}

function showError(root, info, e) {
  root.innerHTML = `<div class="center-block pad"><h1>Something went wrong</h1>
      <p class="lead">Task ${info.number} · ${esc(info.title)}</p><p class="error-text">${esc(e.message)}</p>
      <div class="row-center"><button class="btn primary" data-act="retry">Try this task again</button>
      <button class="btn" data-act="skip">Skip it (counts as 0)</button></div></div>`;
  return new Promise((r) => {
    root.querySelector('[data-act="retry"]').onclick = () => r("retry");
    root.querySelector('[data-act="skip"]').onclick = () => r("skip");
  });
}
