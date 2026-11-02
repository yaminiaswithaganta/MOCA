// Voice (browser speech), microphone streaming and camera for the MoCA tasks.

import { accessToken } from "../lib/api";

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- voice
let chosenVoice: SpeechSynthesisVoice | null = null;
const NORMAL_RATE = 0.92, SLOW_RATE = 0.75;
let defaultRate = NORMAL_RATE;

/** The examiner's "voice speed" setting for this test. */
export function setVoiceSpeed(speed: "normal" | "slow") {
  defaultRate = speed === "slow" ? SLOW_RATE : NORMAL_RATE;
}

function pickVoice() {
  const voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
  const en = voices.filter((v) => /^en[-_]/i.test(v.lang));
  const prefer = ["Samantha", "Karen", "Daniel", "Moira", "Google US English", "Microsoft Aria"];
  chosenVoice =
    prefer.map((n) => en.find((v) => v.name.includes(n))).find(Boolean) ||
    en.find((v) => v.localService) || en[0] || null;
}
if (window.speechSynthesis) {
  pickVoice();
  speechSynthesis.onvoiceschanged = pickVoice;
}

export function voiceAvailable() {
  return !!window.speechSynthesis;
}

/** Speak text. Resolves when finished. onStart(time) is called when speech begins. */
export function speak(text: string, { rate = defaultRate, onStart }: { rate?: number; onStart?: (ms: number) => void } = {}) {
  return new Promise<boolean>((resolve) => {
    if (!window.speechSynthesis) return resolve(false);
    const u = new SpeechSynthesisUtterance(text);
    if (chosenVoice) u.voice = chosenVoice;
    u.lang = "en-US";
    u.rate = rate;
    let done = false;
    const finish = () => { if (!done) { done = true; clearTimeout(guard); resolve(true); } };
    // some browsers never fire onend; never let the test hang on the voice
    const guard = setTimeout(finish, 2500 + text.length * 110);
    u.onstart = () => onStart && onStart(performance.now());
    u.onend = finish;
    u.onerror = finish;
    speechSynthesis.speak(u);
  });
}

export function stopSpeaking() {
  if (window.speechSynthesis) speechSynthesis.cancel();
}

// ---------------------------------------------------------------- microphone
const TARGET_RATE = 16000;

class Microphone {
  ctx: AudioContext | null = null;
  stream: MediaStream | null = null;
  listener: ((chunk: Float32Array) => void) | null = null;
  level = 0;

  async init() {
    if (this.ctx) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/mic-worklet.js");
    const src = this.ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(this.ctx, "mic-tap");
    const ratio = this.ctx.sampleRate / TARGET_RATE;
    let pos = 0;           // fractional read position into `carry`
    let carry: Float32Array = new Float32Array(0);
    node.port.onmessage = (e) => {
      const input = e.data;
      let peak = 0;
      for (let i = 0; i < input.length; i++) peak = Math.max(peak, Math.abs(input[i]));
      this.level = Math.max(peak, this.level * 0.9);
      if (!this.listener) { carry = new Float32Array(0); pos = 0; return; }
      // downsample to 16 kHz: average the input samples in each output step
      const buf = new Float32Array(carry.length + input.length);
      buf.set(carry); buf.set(input, carry.length);
      const out: number[] = [];
      while (pos + ratio <= buf.length) {
        const a = Math.floor(pos), b = Math.floor(pos + ratio);
        let s = 0;
        for (let i = a; i < b; i++) s += buf[i];
        out.push(s / Math.max(1, b - a));
        pos += ratio;
      }
      const keep = Math.floor(pos);
      carry = buf.slice(keep);
      pos -= keep;
      if (out.length) this.listener(Float32Array.from(out));
    };
    src.connect(node);
    // the node must reach the output to keep running; it outputs silence
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    node.connect(mute).connect(this.ctx.destination);
  }

  async start(onChunk: (chunk: Float32Array) => void) {
    await this.init();
    if (this.ctx!.state === "suspended") await this.ctx!.resume();
    this.listener = onChunk;
  }

  stop() {
    this.listener = null;
  }
}

export const mic = new Microphone();

/**
 * Record one spoken answer: the server transcribes and decides when it is over.
 * handlers: onHeard(text), onStatus(text), onToken(token), onReady()
 * Returns {promise, stop(), cancel()}.
 */
export interface ListenHandlers {
  onHeard?: (text: string) => void;
  onStatus?: (text: string, type: string) => void;
  onToken?: (token: string) => void;
  onReady?: () => void;
}

export function listen(sessionId: number, task: number, step: string, handlers: ListenHandlers = {}) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/listen`);
  ws.binaryType = "arraybuffer";
  let pending: Float32Array[] = [];
  let flushTimer: ReturnType<typeof setInterval> | undefined;
  let finished = false;

  const promise = new Promise<any>((resolve, reject) => {
    const cleanup = () => {
      finished = true;
      mic.stop();
      clearInterval(flushTimer);
    };
    ws.onopen = async () => ws.send(JSON.stringify({ token: await accessToken(), session_id: sessionId, task, step }));
    ws.onmessage = async (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "ready") {
        await mic.start((chunk) => pending.push(chunk));
        flushTimer = setInterval(() => {
          if (!pending.length || ws.readyState !== 1) return;
          const n = pending.reduce((a, c) => a + c.length, 0);
          const all = new Float32Array(n);
          let o = 0;
          for (const c of pending) { all.set(c, o); o += c.length; }
          pending = [];
          ws.send(all.buffer);
        }, 100);
        handlers.onReady && handlers.onReady();
      } else if (msg.type === "heard") handlers.onHeard && handlers.onHeard(msg.text);
      else if (msg.type === "status" || msg.type === "reminder") handlers.onStatus && handlers.onStatus(msg.text, msg.type);
      else if (msg.type === "token") handlers.onToken && handlers.onToken(msg.token);
      else if (msg.type === "done") { cleanup(); resolve(msg); }
      else if (msg.type === "error") { cleanup(); reject(new Error(msg.text)); }
    };
    ws.onerror = () => { if (!finished) { cleanup(); reject(new Error("lost connection to the app")); } };
    ws.onclose = () => { if (!finished) { cleanup(); reject(new Error("listening was cancelled")); } };
  });

  return {
    promise,
    stop: () => ws.readyState === 1 && ws.send(JSON.stringify({ type: "stop" })),
    cancel: () => { finished = true; mic.stop(); clearInterval(flushTimer); ws.close(); },
  };
}

// ---------------------------------------------------------------- camera
let camStream: MediaStream | null = null;

export async function camera(videoEl: HTMLVideoElement) {
  if (!camStream || !camStream.active) {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false,
    });
  }
  videoEl.srcObject = camStream;
  videoEl.muted = true;
  videoEl.playsInline = true;
  await videoEl.play();
  return camStream;
}

export function stopCamera() {
  if (camStream) camStream.getTracks().forEach((t) => t.stop());
  camStream = null;
}

/** Full-resolution still from the video as a PNG blob. */
export function snapshot(videoEl: HTMLVideoElement) {
  const c = document.createElement("canvas");
  c.width = videoEl.videoWidth;
  c.height = videoEl.videoHeight;
  c.getContext("2d")!.drawImage(videoEl, 0, 0);
  return new Promise<Blob>((r) => c.toBlob((b) => r(b!), "image/png"));
}
