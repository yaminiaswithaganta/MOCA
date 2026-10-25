# MoCA Auto-Scoring

A local web app that runs the **Montreal Cognitive Assessment (MoCA)** by voice and camera,
and scores all 13 tasks automatically. The examiner opens it in a browser. The patient speaks
their answers and holds drawings up to the webcam. Each task is scored as soon as it ends, and
everything is saved: a score sheet laid out like the paper form, the recordings, and the photos.

Everything runs **on this one computer**. Speech recognition is offline, and patient data is
never sent to the internet.

---

## Contents

1. [Quick start](#1-quick-start)
2. [Requirements](#2-requirements)
3. [Using the app](#3-using-the-app)
4. [The 13 tasks and how each is scored](#4-the-13-tasks-and-how-each-is-scored)
5. [Data, database and privacy](#5-data-database-and-privacy)
6. [How it works (architecture)](#6-how-it-works-architecture)
7. [Project structure](#7-project-structure)
8. [API reference](#8-api-reference)
9. [Configuration and tuning](#9-configuration-and-tuning)
10. [Command-line version](#10-command-line-version)
11. [Tests](#11-tests)
12. [Troubleshooting](#12-troubleshooting)
13. [Known limitations](#13-known-limitations)
14. [Credits and licences](#14-credits-and-licences)

---

## 1. Quick start

### Option A: let an AI assistant set it up (easiest)

1. Open this folder in **VS Code**.
2. Start **Claude Code** or **Codex** in the VS Code terminal.
3. Paste in the contents of [`SETUP_FOR_AI.md`](SETUP_FOR_AI.md), or type
   *"Read SETUP_FOR_AI.md and do what it says."*
4. The assistant installs everything, starts the app and gives you the link.

### Option B: double-click (Mac)

1. Install **Python 3.12** from <https://www.python.org/downloads/macos/>.
2. Right-click **`start.command`** → **Open** → **Open**. (Only the first time. A normal double-click
   is blocked once, because the file came from the internet.)
3. The first start takes about 10 minutes: it installs packages and downloads the speech model.
   The app then opens in the browser at **<http://127.0.0.1:8000>**.
4. After that, just double-click `start.command`. Keep the Terminal window open while using the
   app; closing it stops the app.

### Option C: by hand (any system)

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
.venv/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# then open http://127.0.0.1:8000
```

On Windows, use `.venv\Scripts\python` in place of `.venv/bin/python`.

Plain-language instructions for the person using the app are in [`HOW TO START.txt`](HOW%20TO%20START.txt).

---

## 2. Requirements

| What | Details |
|---|---|
| Computer | macOS (tested on Apple Silicon). Windows and Linux also work with Option C. |
| Python | **3.11, 3.12 or 3.13**. 3.14+ and 3.10 and older lack builds of some packages. |
| Browser | **Google Chrome** (recommended). It must be allowed to use the microphone and camera. |
| Hardware | A microphone and a webcam. The built-in ones on a laptop are fine. |
| Internet | Needed **once**, for the first setup (about 1 GB of packages plus the speech model). After that it works offline. |
| Disk | About 2 GB for packages and models. Recordings and photos add a few MB per test. |

Python packages (`requirements-web.txt`, which includes `requirements.txt`):

| Package | Used for |
|---|---|
| `fastapi`, `uvicorn[standard]` | The web server and the live audio WebSocket |
| `sqlalchemy` | The database (SQLite by default) |
| `python-multipart` | Photo uploads |
| `faster-whisper` | Offline speech recognition (Whisper `small.en`) and voice detection (Silero VAD) |
| `opencv-python`, `numpy`, `scikit-image` | Scoring the cube and clock drawings |
| `matplotlib`, `sounddevice` | Only for the command-line version's windows and microphone |

---

## 3. Using the app

### Top bar

| Item | What it does |
|---|---|
| **Home** | Overview, recent tests, checklist, what the MoCA measures |
| **Patients** | Every patient, their tests and scores |
| **New test** | Start a test |
| **Mic & camera** | Check the microphone level, the voice and the camera picture |
| **Speech ready** light | Green when speech recognition is loaded. Wait for it before starting a test. |

### Starting a test (New test)

1. **Patient:** search for an existing patient, or press **+ New patient** (name, date of birth, sex,
   years of education). Years of education matters: **12 years or less adds 1 point** to a full test.
2. **Tasks:** all 13 are ticked. Untick any to run a shorter test; the score is then out of the
   chosen tasks' points.
3. Press **Start test**. Chrome asks for the microphone (and the camera, if a camera task is
   included). Click **Allow**.

### During a test

The navigation bar hides, so only the task is on screen. Each task:

- **reads its instructions aloud** (browser voice) and shows them on screen;
- shows a **listening bar** with a pulsing microphone and the words it heard so far;
- ends by itself after a natural pause (or when the answer is complete), then shows the score.

| Control | Effect |
|---|---|
| **Done answering** | Ends the current answer now and scores what was said |
| **Skip task** | Moves on. The task counts as 0 and is marked *not completed*. |
| **End test** | Stops the test. Remaining tasks count as 0. |
| **Next task →** | Shown after each task's score |
| **Space bar** | Starts the photo countdown (Tasks 2 and 3), or marks a hand raise in examiner mode (Task 7) |

**Camera tasks:**
- *Cube (2) and clock (3):* the patient draws on paper and holds it up. Press **Start 10-second
  countdown** (or **Take photo now**). Check the photo, then press **Use this photo** or **Retake**.
- *Letters (7):* the patient sits facing the camera with hands down for 2 seconds, then does one
  practice raise. If the camera can't see the hand clearly (two tries), the app switches to
  **examiner mode**: press Space (or the big button) each time the patient raises a hand.

If the test is interrupted (closed tab, power cut), open it from the patient's page and press
**Continue test**. Finished tasks are kept.

### Results

- **Total score** in a ring, with the education point added for full tests, and a
  "Normal range (26+)" or "Below 26" label.
- **By section**: one bar per MoCA area, each in its own colour.
- **Score sheet**: every line of the paper form with its points, and the memory learning trials
  (not scored).
- **Task details**: one card per task: score, reason, what was heard, the photos (original and
  annotated, showing what the scorer saw) and audio players for every recording.
- **Print** gives a clean paper report. **Delete** removes the test from the database (its files
  stay in `results/`).

### Patients

A searchable list with each patient's number of tests and last score. A patient's page shows
their details (**Edit details**), a **score-over-time chart** (after two full tests) and every test.

---

## 4. The 13 tasks and how each is scored

Nothing is scored by hand. The rule throughout: **anything the system cannot verify scores 0**.
A point is never given just because something was said or drawn.

| # | Task | Input | Points | MoCA section |
|---|---|---|---|---|
| 1 | Trail making (1-A-2-B-…-5-E) | Voice | 1 | Visuospatial / executive (5) |
| 2 | Cube copy | Camera | 1 | 〃 |
| 3 | Clock drawing (ten past eleven) | Camera | 3 | 〃 |
| 4 | Naming: lion, rhinoceros, camel | Pictures + voice | 3 | Naming (3) |
| 5 | Memory: FACE, VELVET, CHURCH, DAISY, RED (2 trials) | Voice | 0 | Memory (not scored) |
| 6 | Digit span: forward and backward | Voice | 2 | Attention (6) |
| 7 | Letters: raise a hand at every A | Camera | 1 | 〃 |
| 8 | Serial 7s from 100 | Voice | 3 | 〃 |
| 9 | Sentence repetition (2 sentences) | Voice | 2 | Language (3) |
| 10 | F-word fluency (one minute) | Voice | 1 | 〃 |
| 11 | Abstraction: train–bicycle, watch–ruler | Voice | 2 | Abstraction (2) |
| 12 | Delayed recall of the 5 words | Voice | 5 | Delayed recall (5) |
| 13 | Orientation: date, month, year, day, place, city | Voice | 6 | Orientation (6) |
| | **Total** | | **30** | +1 if education ≤ 12 years |

### How speech is understood (all voice tasks)

- The browser streams the microphone (16 kHz) to the server over a WebSocket.
- **Silero VAD** finds where speech starts and stops. An answer ends after a real pause, not a
  fixed time or volume.
- Each phrase is transcribed **live** by **Whisper** (`small.en`, offline), so the patient sees what
  was heard. When the answer ends, the **whole recording is transcribed again in one pass**, which
  is more accurate, and both are used for scoring.
- Accents and spelling variants are handled by Whisper plus alias lists and "one letter off"
  matching. Similar real words that mean something else ("line", "cameo", "camera") are rejected.

### Task by task

**Task 1: Trail making (1 point, all-or-nothing).** The patient says the path. Arrows appear on
the diagram live (green = correct step, red = mistake). Listening stops when "E" is heard or after
10 s of silence. Scores 1 only if the final transcript is exactly 1-A-2-B-3-C-4-D-5-E and every step
was recognised with confidence ≥ 0.25 (lower if the live and final passes agree exactly). "To"/"for"
between steps are connecting words, "the" is never read as D, and any other letter or number is a
mistake. If Whisper writes a letter as a word ("A" heard as "Yay!"), the audio is re-decoded
restricted to letters and numbers. Self-correction ("C, no, B") is off by default (`ALLOW_SELF_CORRECTION`).

**Task 2: Cube copy (1 point).** The photo is compared with the reference cube's actual corners:
1. pen strokes are found (coloured things like skin or a clipboard are ignored) and thinned;
2. straight edges are found, broken pieces joined, and edge ends grouped into corners;
3. structure: exactly 8 corners and 12 edges, 3 per corner, joined like a cube;
4. geometry: the 8 corners are matched to the reference's (only move, rotate and resize allowed;
   no mirroring or stretching), and the fit error, the three parallel edge families, the
   perspective direction and the proportions must all be within tolerance.

**Task 3: Clock (3 points, 1 each).** If the numbers don't read as a clock, the photo is also tried
turned 90°, 180° and 270°.
- *Contour:* the largest stroke is fitted with an ellipse. After smoothing out tremor it must stay
  within 8.5 % of that shape, be closed (≥ 85 %), not too oval (axis ratio ≥ 0.75) and big enough.
- *Numbers:* outline and hands are removed, and the remaining marks are grouped into numbers and
  read by two digit readers (a CNN and a HOG model, averaged). All 12 positions must hold the right
  number in clockwise order, within 25°. Up to 3 unclear but correctly placed numbers are allowed;
  a number confidently read as a different one is not.
- *Hands:* exactly two strokes starting at the centre; the hour hand clearly shorter (≤ 85 % of the
  minute hand); the hour hand within ±20° of 11 and the minute hand within ±20° of 2.

**Task 4: Naming (3 points, 1 per animal).** Accepted: *lion*; *rhinoceros* or *rhino*; *camel* or
*dromedary*. The **last** animal named counts, so "a tiger… no, a lion" scores 1. Other animals
(tiger, hippo, horse…) score 0. No answer in 12 s scores 0. Pictures: `images/lion.png`,
`rhino.png`, `camel.png` (replace with your own pictures, same names).

**Task 5: Memory (not scored).** The five words are shown and read one per second, then the
patient says what they remember, in any order. Done twice. The recalled words and any other words
said (intrusions) are saved and shown on the score sheet.

**Task 6: Digit span (2 points).** Forward: 2 1 8 5 4 must be repeated exactly. Backward: 7 4 2
must be said as 2 4 7. One point each. "to"/"for"/"ate" are read as 2/4/8 in a digit list.

**Task 7: Letters (1 point).** 29 letters are read, one every 2 seconds. The camera watches the
areas beside and above the head, comparing each frame with a "hands down" picture. Two signals
(brightness change and new skin-coloured pixels) are measured during the practice raise, and the
clearer one is used. A missed A or a raise on another letter is an error. **0 or 1 error = 1 point.**
A hand still held up from an earlier A isn't penalised (unless held for more than two letters).

**Task 8: Serial 7s (3 points).** "Start at 100 and keep subtracting 7." Four answers are taken, and
each is checked against the **previous answer** minus 7 (MoCA rule: one mistake doesn't spoil the
rest). 4 correct = 3 points, 2–3 = 2, 1 = 1, 0 = 0.

**Task 9: Sentence repetition (2 points).** "I only know that John is the one to help today." and
"The cat always hid under the couch when dogs were in the room." A sentence scores 1 when at least
**90 %** of its words were said in order (`REPEAT_MIN_RATIO`; set it to 1.0 for strict scoring).

**Task 10: F-word fluency (1 point).** One minute. Each different word starting with F counts once
("for" and "from" are ignored). **11 or more** = 1 point. Proper names can't be detected
automatically; the saved word list lets the examiner check.

**Task 11: Abstraction (2 points).** Train–bicycle needs a transport word (transport, vehicle,
travel, wheels…). Watch–ruler needs a measuring word (measure, instrument, scale, time, length…).
The word lists are in `task11_abstraction.py`.

**Task 12: Delayed recall (5 points).** The five words from Task 5, with no cues. One point per word
heard in either the live or the final transcript.

**Task 13: Orientation (6 points).** Date, month, year and day of the week are checked against the
computer's clock. Digits and words are both accepted ("24", "twenty fourth", "the twenty fourth",
"twenty twenty six", "two thousand and twenty six"). Place and city: any real answer scores 1;
"I don't know" scores 0.

---

## 5. Data, database and privacy

### Where data is stored

| Location | Contents |
|---|---|
| `moca.db` | **SQLite database**: patients, tests and scores. Created automatically on first start. |
| `results/session_<date>_<time>/` | One folder per test: recordings, photos and JSON results |

Both hold **private patient information**. They are git-ignored and are never uploaded anywhere.
**Back up** by copying `moca.db` and `results/` somewhere safe (USB stick, encrypted cloud drive).

### Database tables (`webapp/db.py`)

| Table | Columns |
|---|---|
| `patients` | `id`, `name`, `date_of_birth`, `sex`, `education_years`, `notes`, `created_at` |
| `test_sessions` | `id`, `patient_id`, `folder`, `tasks` (list of task numbers), `status` (`in_progress` / `finished`), `started_at`, `finished_at`, `total`, `max_total`, `education_bonus`, `adjusted_total` |
| `task_results` | `id`, `session_id`, `task_id`, `score`, `max_score`, `criteria` (per-item points), `reason`, `details` (transcripts, checks…), `evidence_files` (paths), `completed`, `created_at` |

To browse the database directly, open `moca.db` in **TablePlus** or **DB Browser for SQLite**.

### Files in a test folder

| File | Contents |
|---|---|
| `patient.json` | Patient details at the time of the test |
| `taskN_<name>.json` | Each task's result: score, criteria, reason, details |
| `task1_audio.wav`, `task1_transcript.json` | Trail-making recording and full transcript |
| `cube_capture.png`, `cube_annotated.png` | Cube photo and what the scorer saw |
| `clock_capture.png`, `clock_annotated.png` | Clock photo and what the scorer saw |
| `task4_naming_<animal>.wav`, `task5_memory_trial<N>.wav`, `task6_digits_*.wav`, … | One recording per spoken answer |
| `moca_results.json` | Full report: every task, section totals, summary |
| `score_sheet.json`, `score_sheet.txt` | The paper-form score sheet |

### Moving to PostgreSQL (e.g. Supabase) later

The database code uses SQLAlchemy, so you only change the connection address:

```bash
MOCA_DATABASE_URL=postgresql://user:password@host:5432/dbname
```

You also need `pip install psycopg[binary]`. Existing SQLite data has to be copied over once
(for example with `pgloader`). Putting the app online also needs logins and care with patient-data
regulations (HIPAA/GDPR), which this app doesn't provide.

---

## 6. How it works (architecture)

```
┌────────────────────── Browser (Chrome) ──────────────────────┐
│  Pages (HTML/CSS/JS, no build step)                          │
│  • voice: browser speech synthesis reads the instructions    │
│  • microphone → 16 kHz audio ─────────────┐ WebSocket        │
│  • camera → photo (Tasks 2, 3) ───────────┤ HTTP upload      │
│  • camera → hand-raise times (Task 7) ────┤ HTTP (JSON)      │
└───────────────────────────────────────────┼──────────────────┘
                                            ▼
┌──────────────── Python server (FastAPI, localhost) ──────────┐
│  webapp/server.py   API, live listening, database writes     │
│  webapp/web_tasks.py  calls each task module's own scoring   │
│  task1_…task13_*.py  scoring rules (shared with the CLI)     │
│  moca_speech.py / Whisper + Silero VAD  speech               │
│  moca_common.py / OpenCV  drawings, result format            │
│  webapp/db.py → moca.db (SQLite)    files → results/         │
└──────────────────────────────────────────────────────────────┘
```

**Live listening protocol** (`/ws/listen`):
1. The browser sends `{"session_id", "task", "step"}`.
2. The server replies `{"type": "ready"}` once the speech engine is free.
3. The browser streams binary float32 16 kHz audio every 100 ms.
4. The server sends `heard` (live phrase), `status` / `reminder` messages, and `token` (Task 1 path
   steps) while listening, then one `done` (or `error`).
5. `{"type": "stop"}` from the browser ends the answer early (**Done answering**). Closing the
   socket cancels it (**Skip task**).

Spoken answers are kept in memory until the task is finished. Then
`POST /api/sessions/{id}/tasks/{n}/finish` scores them with the task module's own functions, saves
the JSON in the test folder and writes the row to the database.

The **scoring code is shared** with the command-line version. The web app only replaces the windows,
microphone and camera with the browser.

---

## 7. Project structure

```
MoCA_AutoScoring/
├── start.command              Mac launcher (sets up on first run, then starts the app)
├── SETUP_FOR_AI.md            Setup instructions for an AI coding assistant
├── HOW TO START.txt           Plain-language instructions for the user
├── requirements.txt           Scoring/CLI packages
├── requirements-web.txt       + web app packages
│
├── webapp/                    ── the web app ──
│   ├── server.py              FastAPI app: API, WebSocket listening, database writes
│   ├── web_tasks.py           Per-task listening settings and scoring glue
│   ├── db.py                  SQLAlchemy models (patients, test_sessions, task_results)
│   └── static/
│       ├── index.html         Page shell and top navigation
│       ├── app.css            All styles (ocean-blue theme)
│       ├── app.js             Pages: home, patients, new test, results, device check
│       ├── runner.js          Runs a test: one flow per task, result cards
│       ├── media.js           Browser voice, microphone streaming, camera
│       ├── hand.js            Task 7 hand-raise detector (port of the Python one)
│       ├── ui.js              Helpers, icons, MoCA area colours
│       ├── mic-worklet.js     Audio thread that taps the microphone
│       └── fonts/             Figtree (bundled for offline use)
│
├── task1_trail_making.py      ── one module per task: scoring rules + CLI runner ──
├── task2_cube_copy.py
├── task3_clock_draw.py
├── task4_naming.py
├── task5_memory.py
├── task6_attention.py         Digit span (+ wiring for tasks 7 and 8 in the CLI)
├── task7_letters.py
├── task8_serial7s.py
├── task9_sentence_repetition.py
├── task10_fluency.py
├── task11_abstraction.py
├── task12_delayed_recall.py
├── task13_orientation.py
│
├── moca_common.py             Result format, totals, sections, image helpers
├── moca_speech.py             Listening for one answer, word matching, number parsing
├── moca_score_sheet.py        Score sheet in the paper form's layout
├── moca_tasks.py              Task list and titles; runs one task (CLI)
├── moca_voice.py              macOS voice for the CLI
├── run_moca.py                Command-line runner (all tasks in a row)
│
├── models/                    mnist-8.onnx + digits_hog_softmax.npz (clock digit readers)
├── images/                    lion.png, rhino.png, camel.png
├── tests/                     Unit tests, synthetic drawings, speech harnesses
├── tools/                     Digit-model training, Task 7 camera check
├── _superseded/               Older versions of tasks 9–12 (not used)
│
├── moca.db                    (created on first start: the database)
└── results/                   (created on first start: one folder per test)
```

---

## 8. API reference

All endpoints are served at `http://127.0.0.1:8000`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | `{speech_ready, speech_error}` |
| GET | `/api/config` | Task list, instruction texts, words, pictures, letters (everything the pages need) |
| GET | `/api/stats` | Counts of patients and tests, and the average full-test score |
| GET | `/api/reference-cube.png` | The cube the patient copies |
| POST | `/api/face` | Finds a face in a small camera frame (Task 7 uses it to place the hand zone) |
| GET | `/api/patients?q=` | List and search patients (with their last test) |
| POST | `/api/patients` | Create a patient |
| GET | `/api/patients/{id}` | One patient with their tests |
| PUT | `/api/patients/{id}` | Update a patient |
| GET | `/api/sessions?limit=` | Recent tests |
| POST | `/api/sessions` | Start a test: `{patient_id, tasks: [1..13]}` |
| GET | `/api/sessions/{id}` | A test with its report, score sheet and evidence links |
| DELETE | `/api/sessions/{id}` | Remove a test from the database (files are kept) |
| POST | `/api/sessions/{id}/finish` | Total up the test; writes `moca_results.json` and the score sheet |
| POST | `/api/sessions/{id}/tasks/{n}/finish` | Score a spoken task from its recorded answers |
| POST | `/api/sessions/{id}/tasks/{n}/photo` | Upload and score a cube (2) or clock (3) photo |
| POST | `/api/sessions/{id}/tasks/7/letters` | Score Task 7 from the measured letter and hand-raise times |
| POST | `/api/sessions/{id}/tasks/{n}/skip` | Mark a task skipped (0, not completed) |
| WS | `/ws/listen` | Live listening for one answer (see [section 6](#6-how-it-works-architecture)) |
| GET | `/results/...` | Recordings and photos of a test |

---

## 9. Configuration and tuning

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `MOCA_WHISPER_MODEL` | `small.en` | Speech model. `base.en` is smaller and faster for slow computers. |
| `MOCA_DATABASE_URL` | `sqlite:///moca.db` | Database address (e.g. PostgreSQL) |
| `MOCA_PORT` | `8000` | Port used by `start.command` |
| `MOCA_MIC_DEVICE` | system default | Microphone number (**command-line version only**) |

### Scoring tolerances

Each task keeps its settings at the top of its file:

| File | Settings |
|---|---|
| `task1_trail_making.py` | `MIN_WORD_PROB`, `END_OF_PHRASE_SILENCE_S`, `END_OF_TASK_SILENCE_S`, `ALLOW_SELF_CORRECTION` |
| `task2_cube_copy.py` | `CUBE_TOL` (fit error, rotation, proportions…) |
| `task3_clock_draw.py` | `CLOCK_TOL` (contour, hands, numbers), `REQUIRED_TIME = (11, 10)` |
| `task4_naming.py` | `ANIMAL_VOCAB` (accepted and rejected words), `ANSWER_TIMEOUT_S` |
| `task5_memory.py` | `WORD_VOCAB` (accepted spellings) |
| `task7_letters.py` | `LETTERS`, `LETTER_INTERVAL_S` |
| `task9_sentence_repetition.py` | `SENTENCES`, `REPEAT_MIN_RATIO` |
| `task10_fluency.py` | `FLUENCY_MIN_WORDS`, `FLUENCY_IGNORE` |
| `task11_abstraction.py` | `TRANSPORT_WORDS`, `MEASURE_WORDS` |

The tolerances were set on synthetic drawings and voices. Calibrate them on about 10 real tests:
the annotated photos and saved transcripts show why each decision was made. For accents, add any
consistently misheard spellings to the alias lists.

---

## 10. Command-line version

The original version runs without a browser, using desktop windows (OpenCV/matplotlib), the
microphone directly and the macOS voice:

```bash
python run_moca.py                    # all 13 tasks, total out of 30
python run_moca.py --tasks 4 5        # only some tasks
python run_moca.py --camera 1         # a different webcam
python task3_clock_draw.py            # any single task
```

Results go to the same `results/session_<date>_<time>/` folders. The command-line version doesn't use
the database and doesn't record patient details.

---

## 11. Tests

```bash
.venv/bin/python -m unittest tests/test_moca.py -v
```

They cover synthetic good and bad cubes and clocks (wobbly lines, rotated paper, missing or extra
edges, mirrored cubes, squares, wrong times, reversed numbers…), the scoring maths, the score sheet,
the Task 1 path rules, naming and memory matching, digit span, serial 7s, the letter rules and the
hand-raise detector on synthetic video.

- `tests/speech_harness.py` runs synthesised voices through the real Task 1 pipeline. It needs
  optional test-only models (see the file).
- `TestRealPhotos` needs webcam photos in `tests/real_photos/`, which are not included in the repo
  (they show a real person). It fails without them.
- **Known:** 4 clock tests currently fail on the "numbers" criterion for synthetic clocks
  (`TestTask3Clock`). Real clock photos score correctly.

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| "Python 3.12 is needed" | Install Python 3.12 from python.org, then start again |
| `start.command` won't open | Right-click → **Open** → **Open** (first time only) |
| Page says "App not running" | Start it again (`start.command`), and keep its Terminal window open |
| "Loading speech…" for a long time | First start downloads the speech model (about 500 MB). Check the internet connection. On a slow computer use `MOCA_WHISPER_MODEL=base.en`. |
| No microphone or camera | Chrome → Settings → Privacy and security → Site settings → Microphone / Camera → allow `127.0.0.1`. On macOS also check System Settings → Privacy & Security → Microphone / Camera → Google Chrome. |
| No voice | Check the volume, use Chrome, and try **Mic & camera → Play a test sentence** |
| Answers cut off or not heard | Speak closer to the microphone in a quiet room. **Done answering** ends an answer manually. |
| Cube or clock scores 0 unexpectedly | Open the test's results and look at the *annotated* photo: it shows what the scorer saw. Retake with even light, the whole drawing in view, the paper straight. |
| Task 7 uses examiner mode | The camera couldn't tell hand-up from hand-down. Better light, plain background, raise the hand beside the head. |
| Port 8000 already in use | `MOCA_PORT=8001 ./start.command`, then open `http://127.0.0.1:8001` |
| Page looks outdated after an update | Reload the page (the server tells the browser not to cache app files) |

The server log is in the Terminal window (or `server.log` when started by an AI assistant).

---

## 13. Known limitations

- **Not a medical device.** Automatic scores should be reviewed by a qualified examiner. Every
  recording, transcript and annotated photo is saved so they can be checked.
- **Differences from the paper MoCA:**
  - letters are read every **2 s** (paper: 1 s) to give the camera time;
  - **serial 7s takes 4 answers** (paper: 5 subtractions: 4–5 correct = 3 points);
  - sentence repetition accepts **90 %** of the words (paper: exact);
  - place and city accept **any real answer**;
  - proper names in F-word fluency aren't excluded automatically.
- **Photos are taken with a countdown button.** The command-line version starts automatically when
  the paper is held still; the web version doesn't.
- **Task 7 in the browser** is a port of the Python detector and has not yet been tried with a
  real camera.
- Tolerances were tuned on **synthetic** data. Calibrate on real tests (see [section 9](#9-configuration-and-tuning)).
- **One test at a time:** the speech engine handles one answer at a time.
- Runs on **localhost only**: there are no logins, because only this computer can reach it.

---

## 14. Credits and licences

- **MoCA** is © Z. Nasreddine MD. Check the MoCA licensing and training requirements
  (<https://mocacognition.com>) before using it with patients.
- **Whisper** (OpenAI) via **faster-whisper**; **Silero VAD**.
- **mnist-8.onnx**: handwritten-digit model from the ONNX Model Zoo. `digits_hog_softmax.npz` is
  trained by `tools/train_digit_model.py`.
- **Figtree** font by Erik Kennedy, SIL Open Font License.
- The reference cube is drawn by the code, not scanned from a test sheet.
