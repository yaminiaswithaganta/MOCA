// Task 7 hand-raise detector -- the same method as HandRaiseDetector in
// task7_letters.py, run in the browser so it is timed exactly with the letters:
// compare each camera frame with a "hands down" picture in the areas beside /
// above the head; thresholds come from one practice raise.

import { sleep, speak } from "./media.js";

const now = () => performance.now() / 1000;

function percentile(values, p) {
  const s = Float64Array.from(values).sort();
  if (!s.length) return 0;
  const idx = (s.length - 1) * (p / 100);
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  return s[lo] + (s[hi] - s[lo]) * (idx - lo);
}

function boxBlur(src, w, h, ch) {
  // 5-wide box blur, horizontal then vertical (stands in for the 5x5 Gaussian)
  const tmp = new Float32Array(src.length), out = new Float32Array(src.length);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++)
      for (let c = 0; c < ch; c++) {
        let s = 0, n = 0;
        for (let k = -2; k <= 2; k++) {
          const xx = x + k;
          if (xx >= 0 && xx < w) { s += src[(y * w + xx) * ch + c]; n++; }
        }
        tmp[(y * w + x) * ch + c] = s / n;
      }
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++)
      for (let c = 0; c < ch; c++) {
        let s = 0, n = 0;
        for (let k = -2; k <= 2; k++) {
          const yy = y + k;
          if (yy >= 0 && yy < h) { s += tmp[(yy * w + x) * ch + c]; n++; }
        }
        out[(y * w + x) * ch + c] = s / n;
      }
  return out;
}

export class HandRaiseDetector {
  constructor(video, width = 320) {
    this.video = video;
    this.w = width;
    this.h = Math.round((video.videoHeight * width) / video.videoWidth) || 240;
    this.canvas = document.createElement("canvas");
    this.canvas.width = this.w;
    this.canvas.height = this.h;
    this.cx = this.canvas.getContext("2d", { willReadFrequently: true });
    this.base = null;
    this.baseSkin = null;
    this.zone = null;
    this.face = null;
    this.thrUp = this.thrDown = null;
    this.up = false;
    this.streak = 0;
    this.mode = "changed";     // "changed" (brightness) or "skin" (hand-coloured pixels)
  }

  /** Current frame, mirrored and blurred: {gray, rgb} or null. */
  read() {
    if (this.video.readyState < 2) return null;
    const { w, h, cx } = this;
    cx.save();
    cx.scale(-1, 1);
    cx.drawImage(this.video, -w, 0, w, h);
    cx.restore();
    const px = cx.getImageData(0, 0, w, h).data;
    const rgb0 = new Float32Array(w * h * 3);
    for (let i = 0, j = 0; i < px.length; i += 4, j += 3) {
      rgb0[j] = px[i]; rgb0[j + 1] = px[i + 1]; rgb0[j + 2] = px[i + 2];
    }
    const rgb = boxBlur(rgb0, w, h, 3);
    const gray = new Float32Array(w * h);
    for (let i = 0, j = 0; i < gray.length; i++, j += 3)
      gray[i] = 0.299 * rgb[j] + 0.587 * rgb[j + 1] + 0.114 * rgb[j + 2];
    return { gray, rgb };
  }

  skinMask(rgb) {
    // YCrCb skin range, as in task7_letters.py
    const n = this.w * this.h, m = new Uint8Array(n);
    for (let i = 0, j = 0; i < n; i++, j += 3) {
      const r = rgb[j], g = rgb[j + 1], b = rgb[j + 2];
      const y = 0.299 * r + 0.587 * g + 0.114 * b;
      const cr = (r - y) * 0.713 + 128, cb = (b - y) * 0.564 + 128;
      m[i] = cr >= 133 && cr <= 178 && cb >= 77 && cb <= 130 ? 1 : 0;
    }
    return m;
  }

  async findFace() {
    const blob = await new Promise((r) => this.canvas.toBlob(r, "image/jpeg", 0.85));
    const fd = new FormData();
    fd.append("file", blob, "frame.jpg");
    try {
      const res = await fetch("/api/face", { method: "POST", body: fd });
      return (await res.json()).face;
    } catch {
      return null;
    }
  }

  makeZone(face) {
    const { w, h } = this, zone = new Uint8Array(w * h);
    if (face) {
      const [fx, fy, fw, fh] = face;
      const bottom = Math.min(h, Math.floor(fy + 1.4 * fh));       // about shoulder height
      const x0 = Math.max(0, Math.floor(fx - 0.35 * fw)), x1 = Math.min(w, Math.floor(fx + 1.35 * fw));
      for (let y = 0; y < bottom; y++)
        for (let x = 0; x < w; x++) zone[y * w + x] = x >= x0 && x < x1 ? 0 : 1;   // not the head
    } else {
      for (let y = 0; y < Math.floor(0.55 * h); y++)
        for (let x = 0; x < w; x++)
          zone[y * w + x] = x >= Math.floor(0.33 * w) && x < Math.floor(0.67 * w) ? 0 : 1;
    }
    this.face = face;
    this.zone = zone;
  }

  /** [brightness-change fraction, new-skin fraction] of the raise zone. */
  features(f) {
    const { zone, base, baseSkin } = this;
    const skin = this.skinMask(f.rgb);
    let n = 0, changed = 0, newSkin = 0;
    for (let i = 0; i < zone.length; i++) {
      if (!zone[i]) continue;
      n++;
      if (Math.abs(f.gray[i] - base[i]) > 25) changed++;
      if (skin[i] && !baseSkin[i]) newSkin++;
    }
    return n ? [changed / n, newSkin / n] : [0, 0];
  }

  /** Hands-down picture, then one practice raise. Returns {ok, info}. */
  async calibrate(onFrame) {
    const frames = [];
    let t0 = now();
    while (now() - t0 < 2.5) {
      const f = this.read();
      if (f) frames.push(f);
      onFrame && onFrame(null);
      await sleep(50);
    }
    if (frames.length < 5) return { ok: false, info: { reason: "no camera frames" } };
    const rest = frames.slice(Math.floor(frames.length / 3));
    const n = this.w * this.h, base = new Float32Array(n), col = new Float32Array(rest.length);
    const skinCount = new Uint16Array(n);
    for (const f of rest) {
      const s = this.skinMask(f.rgb);
      for (let i = 0; i < n; i++) skinCount[i] += s[i];
    }
    for (let i = 0; i < n; i++) {
      for (let k = 0; k < rest.length; k++) col[k] = rest[k].gray[i];
      col.sort();
      base[i] = col[Math.floor(col.length / 2)];
    }
    this.base = base;
    this.baseSkin = Uint8Array.from(skinCount, (c) => (c / rest.length >= 0.5 ? 1 : 0));
    this.makeZone(await this.findFace());
    const restF = rest.map((f) => this.features(f));
    const restLevel = [0, 1].map((k) => percentile(restF.map((v) => v[k]), 95));

    speak("Now raise your hand, and hold it up.");
    const vals = [];
    t0 = now();
    while (now() - t0 < 3.5) {
      const f = this.read();
      const v = f ? this.features(f) : null;
      onFrame && onFrame(v ? v[1] : null);
      if (v && now() - t0 > 1.5) vals.push(v);
      await sleep(50);
    }
    speak("Thank you. Put your hand down.");
    await sleep(2000);
    if (!vals.length) return { ok: false, info: { reason: "no camera frames during the practice raise" } };
    const raised = [0, 1].map((k) => percentile(vals.map((v) => v[k]), 70));
    const gap = [0, 1].map((k) => (raised[k] - restLevel[k]) / (restLevel[k] + 0.02));
    const idx = gap[1] > gap[0] ? 1 : 0;
    this.mode = ["changed", "skin"][idx];
    const b = restLevel[idx], p = raised[idx];
    const info = { signal: this.mode, rest_level: +b.toFixed(4), raised_level: +p.toFixed(4),
                   face_found: !!this.face };
    if (p < Math.max(2.5 * b, b + 0.03)) return { ok: false, info };
    this.thrUp = b + 0.4 * (p - b);
    this.thrDown = b + 0.15 * (p - b);
    Object.assign(info, { thr_up: +this.thrUp.toFixed(4), thr_down: +this.thrDown.toFixed(4) });
    return { ok: true, info };
  }

  /** Hand up / down with hysteresis (2 frames in a row to change). */
  update(f) {
    const feat = this.features(f);
    const v = this.mode === "skin" ? feat[1] : feat[0];
    const want = this.up ? v > this.thrDown : v > this.thrUp;
    if (want !== this.up) {
      if (++this.streak >= 2) { this.up = want; this.streak = 0; }
    } else {
      this.streak = 0;
      if (!this.up) {                      // slowly follow light changes while the hand is down
        for (let i = 0; i < this.base.length; i++) this.base[i] = 0.97 * this.base[i] + 0.03 * f.gray[i];
      }
    }
    return { up: this.up, value: v };
  }
}
