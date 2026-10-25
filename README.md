# MoCA Auto-Scoring

## Web app (recommended)

**Start:** double-click `start.command` (Mac). The first start installs everything
and downloads the speech model (needs internet once, a few minutes). After that the
app opens in the browser at http://127.0.0.1:8000. Keep the black Terminal window
open while using it; close it to stop the app.

Use Chrome. Allow the microphone and camera when the browser asks.

* **New test:** choose or add the patient, tick the tasks (all 13 by default), Start.
  Instructions are spoken aloud, answers are heard through the microphone, drawings
  are photographed with the camera, and every task is scored as soon as it ends.
  *Skip task* counts that task as 0; *Done answering* ends an answer early.
* **Patients:** every patient, their tests, a score-over-time chart, and the full
  results of each test (score sheet like the paper form, photos, recordings, Print).

Everything stays on this computer, and nothing is sent to the internet:
* `moca.db`: the database (patients, tests, scores), one SQLite file. Copy it to back up.
  To view it directly, open it in TablePlus or DB Browser for SQLite.
* `results/session_<date>_<time>/`: photos, recordings and JSON for each test, as before.

Code: `webapp/server.py` (FastAPI), `webapp/web_tasks.py` (calls each task's own
scoring functions), `webapp/db.py` (SQLAlchemy; set `MOCA_DATABASE_URL` to a
PostgreSQL address to move to Supabase later), `webapp/static/` (the pages).

---

## Command-line version

Five runnable Python scripts, one per task, plus a runner that does them in
a row and adds up the score. Each task scores itself automatically the
moment it is completed — nobody types a score in.

| File | Task | Input | Score |
|---|---|---|---|
| `task1_trail_making.py` | Trail Making (1→A→2→B...) | Microphone (patient speaks the path) | 0 or 1 |
| `task2_cube_copy.py` | Cube copy | Webcam, auto-capture 10 s after the paper is held steady | 0 or 1 |
| `task3_clock_draw.py` | Clock drawing (ten past eleven) | Webcam, same capture | 0–3 (contour / numbers / hands) |
| `task4_naming.py` | Naming: lion, rhinoceros, camel | Pictures on screen + microphone | 0–3 (1 per animal) |
| `task5_memory.py` | Memory: FACE, VELVET, CHURCH, DAISY, RED — 2 trials | Words on screen (+ read aloud on Mac) + microphone | not scored (saved for delayed recall) |
| `run_moca.py` | All five in sequence | — | **Visuospatial /5 + Naming /3 = total /8** |

## Install

```bash
pip install -r requirements.txt
```

* `faster-whisper` — offline Whisper speech recognition for Task 1. The
  model (`small.en`, a few hundred MB) downloads once on first run; after
  that no internet is needed. On a slow computer use
  `MOCA_WHISPER_MODEL=base.en python ...`.
* `sounddevice` — continuous microphone recording (bundles PortAudio on Mac/Windows).
* `scikit-image` — thins pen strokes to 1-pixel lines for Tasks 2 and 3.
* `models/mnist-8.onnx` (26 KB, handwritten-digit CNN from the ONNX model zoo)
  and `models/digits_hog_softmax.npz` (back-up digit reader, trained by
  `tools/train_digit_model.py`) are included — keep the `models` folder next
  to the scripts.
* Optional: `pytesseract` + Tesseract is used as a second opinion when a
  clock number is hard to read. No longer required.
* `SpeechRecognition` / `PyAudio` are only used as a fallback if
  faster-whisper isn't installed.

## Run

```bash
python run_moca.py            # Task 1 -> 5, running total, final report (/8)
python run_moca.py --tasks 4 5   # only naming + memory
python task1_trail_making.py  # or any single task on its own
```

Results go to `results/session_<date>_<time>/`:
`task1_trail_making.json` … `task5_memory.json`,
the final `moca_results.json`, plus evidence (Task 1 audio + transcript,
captured photos, annotated photos showing what the scorer saw). The summary
block looks like:

```json
"summary": {"task1_trail_making": 1, "task2_cube_copy": 0,
            "task3_clock_draw": {"contour": 1, "numbers": 0, "hands": 1},
            "task4_naming": {"lion": 1, "rhino": 1, "camel": 0},
            "task5_memory": {"trial1": ["FACE", "RED"], "trial2": ["FACE", "VELVET", "RED"]},
            "total": 5, "max_total": 8}
"sections": {"visuospatial_executive": {"score": 3, "max": 5},
             "naming": {"score": 2, "max": 3}, "memory": {"score": 0, "max": 0}}
```

## How each one is scored

Everything is fail-safe: anything the system cannot verify scores 0; a
point is never given just because *something* was drawn or said.

**Task 1 — Trail Making (1 point, all-or-nothing).** Microphone audio is
recorded continuously (nothing is lost while transcribing). The Silero voice
detector finds phrases and waits for a real ~1.2 s pause — no 4-second
cut-off, no fixed volume threshold. Each phrase is transcribed offline by
Whisper so the path appears on the diagram live. When the patient says "E"
(or is silent for 10 s) the **whole recording is transcribed again in one
pass** and that is scored: 1 only if it is exactly 1-A-2-B-3-C-4-D-5-E and
every step was recognised with confidence ≥ 0.40. Wrong, missing, extra or
unclear steps → 0. "to"/"for" between steps are treated as connecting words
("one to A to two"); "the" is never read as D; any other letter/number
(F, 6…) counts as a mistake; saying the same step twice in a row counts once.
`ALLOW_SELF_CORRECTION` (default off) accepts an immediate "no, sorry, B".
If Whisper writes a letter as a word (e.g. "A" heard as "Yay!"), that audio is
re-decoded with the output restricted to letters, digits and number words;
all 26 letters stay allowed, so a wrong letter is still caught as wrong.

Works with OpenCV 4.x and 5.x.

For accents: Whisper is used as-is (it was trained on many English accents);
no extra training data is needed. To improve further for specific accents,
record a few real answers (they are saved as .wav in the results folder) and
add any consistently misheard spellings to the alias lists in
`task4_naming.py` / `task5_memory.py`.

**Task 2 — Cube copy (1 point, all-or-nothing).** The photo is compared with
the reference cube's actual corner coordinates
(`reference_cube_geometry()`, the same data that draws the reference window):
1. paper found and straightened, pen strokes extracted and thinned;
2. straight edges found, broken pieces joined, edge ends grouped into corners;
3. structure: exactly 8 corners, 12 edges, 3 per corner, joined like a cube;
4. geometry: the 8 corners are matched to the reference's 8 (only move /
   rotate / resize allowed — no mirroring or stretching); fit error, the
   three parallel edge families, the perspective direction (back face
   up-right), and the face/depth proportions must all be within tolerance.

**Task 3 — Clock (3 points, each criterion 0 or 1).**
- *Contour*: the largest stroke is fitted with an ellipse; after smoothing out
  hand tremor it must stay within 8.5 % of that shape, be closed, not too
  oval, and big enough. Shaky circles pass; squares, triangles, open arcs fail.
- *Numbers*: outline and hands are removed, the remaining marks are grouped
  into numbers ("1"+"2" → 12) and read by two digit readers (CNN + HOG model,
  averaged). All 12 clock positions (±20°) must hold the right number in
  clockwise order; missing numbers, wrong order, wrong positions and extra
  numbers → 0. Up to 2 illegible-but-correctly-placed numbers are tolerated;
  a number confidently read as a different one is not.
- *Hands*: straight strokes starting at the centre; exactly two; hour hand
  clearly shorter (≤ 85 % of the minute hand); hour hand within ±20° of 11
  and minute hand within ±20° of 2 (`REQUIRED_TIME = (11, 10)`).

**Task 4 — Naming (3 points, 1 per animal).** The lion, rhinoceros and camel
pictures (`images/lion.png`, `images/rhino.png`, `images/camel.png` — drop in
your own pictures with the same names to replace them) are shown one at a
time. The patient says the animal's name; the answer ends after a pause, or
~1.5 s after an animal was named (so "a tiger… no, a lion" can be corrected).
Accepted: *lion*; *rhinoceros* or *rhino*; *camel* or *dromedary*. Accents and
pronunciations are handled by Whisper (trained on many accents) plus alias
lists and "one letter off" matching (rino, cammel, "lie on"), while
similar-sounding real words (line, cameo, camera, caramel) and other animals
(tiger, hippo, horse…) score 0. The **last** animal named counts. No answer in
12 s → 0.

**Task 5 — Memory (no points).** The five words are shown one per second (and
read aloud with the Mac's voice; `READ_ALOUD = False` to turn off), then hidden;
the patient says all words they remember. Done twice (trial 1, trial 2) as on
the sheet. The recalled words, other words said (intrusions) and transcripts
are saved for the later Delayed Recall task.

## Tuning

All tolerances are in one dict per task: `CUBE_TOL` (Task 2), `CLOCK_TOL`
(Task 3), and the constants at the top of Task 1 (`MIN_WORD_PROB`,
`END_OF_PHRASE_SILENCE_S`, `END_OF_TASK_SILENCE_S`). They were set on
synthetic drawings/voices; calibrate them on ~10 real drawings and a few real
speakers (the annotated images and saved transcripts show why each decision
was made).

## Tests

```bash
python -m unittest tests/test_moca.py -v
```
Synthetic good/bad cubes and clocks (hand-wobbled, rotated, photographed on
a background, missing/extra edges, mirrored, squares, wrong times, swapped
hands, reversed numbers…), the scoring maths (your 4/5 and 3/5 examples), and
the Task 1 path rules. `tests/speech_harness.py` runs synthesised voices
through the real Task 1 pipeline (needs optional test-only models; see file).


