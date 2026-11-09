# MoCA Auto-Scoring

A full-stack web app for the **Montreal Cognitive Assessment (MoCA)**, with separate accounts for patients and
examiners. Patients sign in, enter their details, choose an examiner and take the test by voice and camera.
Examiners design tests, review each automatically scored result, correct it if needed and release it to the
patient.

Built with React and TypeScript, a Python (FastAPI) server, and Supabase for sign-in, the Postgres database and
file storage. Speech recognition (Whisper) runs on your own server, not a third-party speech service.

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

Open this folder in Claude Code (or another AI coding assistant) and say: *"Read SETUP_FOR_AI.md and walk me
through it."* [`SETUP_FOR_AI.md`](SETUP_FOR_AI.md) covers setup on a computer, connecting Supabase, creating the
admin and deploying online.

### Option B: by hand

You need Python 3.11-3.13, Node.js 20+ and a free [Supabase](https://supabase.com) project.

```bash
cp .env.example .env                     # then fill it in: each line says where to find the value
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-web.txt
(cd frontend && npm ci && npm run build)
.venv/bin/python -m uvicorn webapp.server:app --port 8000
```

Open http://127.0.0.1:8000. On a Mac, double-clicking `start.command` does all of this after `.env` exists.
Database tables are created automatically on start. The first start downloads the speech model (about 500 MB).

Then create your administrator (there is no way to sign up as one). It prints a one-time link for choosing a password:

```bash
.venv/bin/python -m webapp.make_admin you@example.com
```

For a quick demo, `.venv/bin/python -m webapp.make_demo_accounts` creates one admin, one examiner and one
patient with ready-made passwords (printed once, no emails sent).

In Supabase, add your site's address followed by `/**` under Authentication > URL Configuration > Redirect URLs,
or invitation links won't return to the app. Supabase's built-in email is limited to a few messages an hour; add
your own SMTP provider (Authentication > Emails) before inviting many people.

**Working on the screens:** run the server as above and `npm run dev` in `frontend/`, then open
http://127.0.0.1:5173 for live reload.

**Local Supabase instead of a cloud project:** `npx supabase init`, then `npx supabase start` (needs Docker);
`npx supabase status` prints the values for `.env`.

### Going online

**Free:** Vercel (Hobby plan) runs it from `Dockerfile.vercel`; see `SETUP_FOR_AI.md`, Part DV. It shuts down when
unused and the next visit waits while the speech model loads.

`deploy/huggingface.py` puts it on Hugging Face Spaces (see `SETUP_FOR_AI.md`, Part D0). Docker Spaces need a
Hugging Face PRO subscription; the Space sleeps when unused and wakes in a few minutes.

The `Dockerfile` builds everything into one image. Host it on a service that runs long-lived containers with
WebSockets, such as Render, Railway, Fly.io or a VM. Serverless platforms can't run Whisper. Pass the `.env`
values as environment variables and serve over HTTPS, because browsers only allow the microphone on secure pages.
In Supabase, set your site's address under Authentication > URL Configuration so email links return to it.

On an always-on host, use a machine with at least 2 CPUs and 4 GB of memory. Speech is transcribed one phrase at a
time, so many patients talking at once will slow each other down.

---

## 2. Requirements

| What | Details |
|---|---|
| Computer | macOS (tested on Apple Silicon). Windows and Linux work with Option B or Docker. |
| Python | **3.11, 3.12 or 3.13**. 3.14+ and 3.10 and older lack builds of some packages. |
| Node.js | **20 or newer**, to build the screens |
| Supabase | A project, free tier or local |
| Browser | **Google Chrome** (recommended). It must be allowed to use the microphone and camera. |
| Hardware | A microphone and a webcam. The built-in ones on a laptop are fine. |
| Internet | Needed to reach Supabase. The first setup also downloads about 1 GB of packages plus the speech model. |
| Disk | About 2 GB for packages and models. Recordings and photos add a few MB per test. |

Python packages (`requirements-web.txt`, which includes `requirements.txt`):

| Package | Used for |
|---|---|
| `fastapi`, `uvicorn[standard]` | The web server and the live audio WebSocket |
| `sqlalchemy`, `alembic`, `psycopg` | The database and its migrations |
| `pyjwt[crypto]` | Checking Supabase sign-in tokens |
| `httpx`, `python-dotenv` | Supabase Storage calls and reading `.env` |
| `python-multipart` | Photo uploads |
| `faster-whisper` | Offline speech recognition (Whisper `small.en`) and voice detection (Silero VAD) |
| `opencv-python`, `numpy`, `scikit-image` | Scoring the cube and clock drawings |
| `matplotlib`, `sounddevice` | Only for the command-line version's windows and microphone |

---

## 3. Using the app

There are three roles, and an account has one. **Patients** join from a link their examiner sends, sign up
themselves, or are added by an admin. **Examiners** are only added by an admin. **Admins** are only created from
the server with `python -m webapp.make_admin`.

### Administrators

**People** lists examiners and patients. An admin can:

- **Add** a person with their name, details, email and a **password the admin chooses**. They can sign in
  straight away; no email is sent. Examiners start with a published Standard MoCA.
- **Set new password** for someone who forgot theirs (the ⋯ menu on their row).
- **Deactivate** an account. Access ends on their next request, an examiner disappears from patients' choices, and
  records are kept. **Reactivate** restores it. Tests waiting for a deactivated examiner stay unreviewed.

Admins can't see scores, transcripts or recordings, only how many tests an account has.

### Patients

1. Enter name, date of birth, sex and years of education.
2. **Start a test:** choose an examiner, choose one of their published tests, read the checklist and agree to
   the recording.
3. Take the test by voice and camera. Answers are saved after each task, with no scores shown. If the page is
   closed, **Continue** on the home page picks up at the next unfinished task.
4. The test then shows as **Awaiting review**. When the examiner releases it, the patient sees the total, the
   score per area and the examiner's note, but not transcripts or recordings.

### Examiners

- **Overview:** tests awaiting review, tests in progress and recent results.
- **Test designs:** every examiner starts with a published **Standard MoCA**. A design sets which tasks, their
  order, voice speed, extra seconds to start answering, whether tasks can be skipped and a message shown first.
  Task content and scoring never change. Delayed recall needs Memory earlier in the test. Tests already started
  keep the design they began with.
- **Review:** the score sheet, what was heard, and each recording and photo. **Correct score** needs a reason, and
  the automatic score is kept beside the correction.
- **Release result:** shows the result to the patient, with an optional note. It's final: corrections stop here.
- **Patients → Add patient:** enter the patient's name, email and date of birth to get a link to send them.
  The patient opens it and enters the same name, email and date of birth (plus years of education). If they
  match, the patient is signed in, connected to this examiner and can start a test. The same link signs them
  back in later, so they don't need a password. **Patient links** shows who has joined, with Copy link and
  Delete.
- **Patients:** everyone who joined through a link or has tested with this examiner, with their score over time.
- **Delete** permanently removes a test with its recordings and photos.

### During a test

- The test opens with a **Start** button, including when a patient comes back to finish it. Browsers block the voice and microphone until the page is clicked, so this makes sure answers aren't recorded as silence.
- The clock task asks for "ten past eleven" in words only; patient screens never show a clock time.
- **Done answering** ends an answer early. **Skip task** (if the design allows) counts as 0 and is marked not
  completed. **End test** finishes now; remaining tasks count as 0.
- If a task hits an error, the patient can retry it or skip it.
- If no sound reaches the server, the answer isn't scored: the patient is told to check the microphone and can retry.
- Task 7 falls back to pressing Space if the camera can't see the hand.

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
| Supabase Auth | Emails and passwords (hashed by Supabase) |
| Supabase Postgres | Everything in the tables below |
| Supabase Storage, private bucket `moca-evidence` | Recordings, photos and report files |
| `results/session_.../` on the server | Working copy of each test's files |

Without `MOCA_SUPABASE_SERVICE_KEY`, files stay only in `results/`.

### Who can see what

| | Patient | The test's examiner | Other examiners | Admins |
|---|---|---|---|---|
| Name, email, number of tests | Yes | Yes | No | Yes |
| Date of birth, sex, education | Yes | Yes | No | No |
| Scores, before release | **No** | Yes | No | No |
| Total and area scores, after release | Yes | Yes | No | No |
| Transcripts, recordings, photos | No | Yes | No | No |

The server enforces these rules on every request. The browser never reads the database or the bucket directly:
all tables have row-level security on with no policies, and the bucket is private, so the public Supabase key
reaches nothing. The role is stored in the app's own `users` table, never in Supabase metadata, which users can edit.

### Database tables (`webapp/db.py`)

| Table | Holds |
|---|---|
| `users` | Supabase user id, email, role, which admin added them, when deactivated |
| `patient_invites` | An examiner's link for one patient: token, name, email, date of birth, who joined |
| `patients` | Name, date of birth, sex, years of education |
| `examiners` | Name, title, organisation |
| `test_templates` | An examiner's designs: tasks in order, settings, published |
| `test_sessions` | One test taken: copy of the design, time zone, consent time, totals, release time, note |
| `task_results` | Score, criteria, reason, details, evidence files, and the automatic score if corrected |

To change the schema, edit `webapp/db.py`, then run
`.venv/bin/python -m alembic revision --autogenerate -m "what changed"`. Migrations apply on the next start.
**A new table needs `ENABLE ROW LEVEL SECURITY` in its migration**, or the Data API exposes it.

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

### Before real patients use it

This app has consent capture and access control, but **it is not certified for any regulation**. Before using
real patient data online: sign a data agreement with Supabase and your host (HIPAA needs a BAA on a paid plan;
GDPR needs a DPA and a suitable region), add a privacy policy and data-retention rules, and check that your use
of the MoCA is licensed. See [section 13](#13-known-limitations).

---

## 6. How it works (architecture)

```
┌──────────── Browser (React + TypeScript) ─────────────┐      ┌── Supabase ──────┐
│  Sign-in, patient and examiner pages                  │─────▶│  Auth            │
│  Test runner: voice, microphone, camera, hand raise   │      └──────────────────┘
└───────────────┬───────────────────────────────────────┘               ▲ public keys
                │ HTTPS + WebSocket, with the Supabase token             │
                ▼                                                        │
┌──────────── Python server (FastAPI) ──────────────────┐                │
│  auth.py       checks the token, finds the role       │────────────────┘
│  accounts.py   profiles, sign-up, examiner list       │
│  admin.py      adding and deactivating people         │
│  templates.py  test designs                           │      ┌── Supabase ──────┐
│  sessions.py   taking, review, release, files         │─────▶│  Postgres        │
│  listen.py     live audio → Whisper + Silero VAD      │      │  Storage         │
│  web_tasks.py  → the original task modules score it   │      └──────────────────┘
└───────────────────────────────────────────────────────┘
```

The browser signs in directly with Supabase and sends the access token with every call. The server checks the
token's signature, then loads the role from its own database. Everything else goes through the server.

While a patient answers, the browser streams 16 kHz audio over `/ws/listen`. The token goes in the first
WebSocket message, because browsers can't set WebSocket headers and addresses end up in logs. The server decides
when the answer is over, transcribes it, and scores the task with the same functions as the command-line version.

Only the Whisper call is locked, not the whole answer, so patients don't wait for each other to finish speaking.
Task 13 judges the date in the patient's own time zone, not the server's.

---

## 7. Project structure

```
├── frontend/                  React + TypeScript app (Vite)
│   ├── public/                Fonts and the microphone worklet
│   └── src/
│       ├── lib/               API calls, Supabase, sign-in state, formatting, types
│       ├── components/        Layout and role checks, forms, the examiner's task card
│       ├── pages/             auth/, patient/, examiner/, admin/, landing, first-time setup
│       ├── runner/            The test itself: voice, mic, camera, hand raise, task flows
│       └── styles/app.css     Design tokens and all styles
├── webapp/                    The server
│   ├── server.py              App setup, security headers, serves the React build
│   ├── auth.py                Token checks, current user and role
│   ├── accounts.py            Profiles, first-time setup, list of examiners
│   ├── admin.py               The admin portal: adding and deactivating people
│   ├── invites.py             Patient links an examiner shares
│   ├── supabase_admin.py      Creating logins through Supabase's admin API
│   ├── make_admin.py          Command that creates an administrator
│   ├── make_demo_accounts.py  Command that creates demo admin, examiner and patient logins
│   ├── templates.py           Test designs
│   ├── sessions.py            Taking tests, results, corrections, release, files
│   ├── listen.py              Whisper and the live-audio WebSocket
│   ├── storage.py             Supabase Storage
│   ├── db.py                  Tables
│   └── web_tasks.py           Bridge to the task modules
├── migrations/                Database schema history (Alembic)
├── task1_trail_making.py … task13_orientation.py      The 13 tasks and their scoring
├── moca_common.py, moca_speech.py, moca_score_sheet.py, moca_tasks.py, moca_voice.py
├── run_moca.py                Command-line version
├── models/                    Task 3 digit model
├── images/                    Task 4 pictures
├── tests/                     test_web.py (accounts, access), test_moca.py (scoring)
├── deploy/huggingface.py     Deployment to Hugging Face Spaces (needs PRO)
├── Dockerfile.vercel, vercel.json, .vercelignore   Deployment to Vercel
├── Dockerfile, .env.example, .github/workflows/ci.yml
└── results/                   Working copies of each test's files (never committed)
```

---

## 8. API reference

Every route needs `Authorization: Bearer <Supabase access token>` unless marked public.
Interactive docs are at `/docs` while the server runs.

| Method | Path | Who | What |
|---|---|---|---|
| GET | `/api/status`, `/api/public-config` | Public | Speech status; Supabase address and public key |
| GET | `/api/me` | Signed in | Who am I, role, profile |
| POST | `/api/me/onboard` | Signed in | First-time setup; sets the role once |
| PUT | `/api/me/profile` | Signed in | Update details |
| GET | `/api/config` | Signed in | Task texts and pictures |
| GET | `/api/examiners` | Patient | Examiners with their published tests |
| GET, POST | `/api/templates` | Examiner | List or create designs |
| GET, PUT, DELETE | `/api/templates/{id}` | Examiner, own | Read, edit or archive a design |
| GET | `/api/sessions`, `/api/sessions/{id}` | Both | Own tests; each role gets its own view |
| POST | `/api/sessions` | Patient | Start a test (template, consent, time zone) |
| POST | `/api/sessions/{id}/tasks/{n}/finish`, `/skip` | Patient, own | Finish or skip a task; no score returned |
| POST | `/api/sessions/{id}/tasks/{n}/photo`, `/tasks/7/letters` | Patient, own | Photo and Task 7 answers |
| POST | `/api/face` | Patient | Task 7 face position |
| POST | `/api/sessions/{id}/finish` | Patient, own | Finish the test |
| PATCH | `/api/sessions/{id}/tasks/{n}` | Examiner, own | Correct a score, with a reason |
| POST | `/api/sessions/{id}/release` | Examiner, own | Release to the patient |
| DELETE | `/api/sessions/{id}` | Examiner, own | Delete a test and its files |
| GET | `/api/sessions/{id}/files/{name}` | Examiner, own | A recording or photo |
| GET | `/api/stats`, `/api/patients`, `/api/patients/{id}` | Examiner | Own numbers and patients |
| GET | `/api/admin/stats`, `/api/admin/users?role=` | Admin | Counts; examiners or patients |
| POST | `/api/admin/examiners`, `/api/admin/patients` | Admin | Add a person with a password |
| POST | `/api/admin/users/{id}/deactivate`, `/reactivate`, `/password` | Admin | Manage an account |
| GET, POST | `/api/invites` | Examiner | List or create patient links |
| DELETE | `/api/invites/{id}` | Examiner, own | Delete a link |
| GET, POST | `/api/join/{token}` | Public (the link) | Who invited them; confirm details and sign in |
| WS | `/ws/listen` | Patient, own | Live listening for one answer |

---

## 9. Configuration and tuning

### Environment variables

`.env.example` lists them all. The main ones:

| Variable | Default | What it does |
|---|---|---|
| `MOCA_SUPABASE_URL` | none | Supabase project address |
| `MOCA_SUPABASE_ANON_KEY` | none | Public key, sent to the browser |
| `MOCA_SUPABASE_SERVICE_KEY` | none | Server-only key for Storage. Without it, files stay in `results/` |
| `MOCA_SUPABASE_JWT_SECRET` | none | Only for older projects with shared-secret tokens |
| `MOCA_DATABASE_URL` | `sqlite:///moca_local.db` | Database address |
| `MOCA_SITE_URL` | the address in use | The app's address, for links in emails |
| `MOCA_GOOGLE_LOGIN` | off | `1` shows the Google button |
| `MOCA_STORAGE_BUCKET` | `moca-evidence` | Bucket name; created on first start |
| `MOCA_WHISPER_MODEL` | `small.en` | Speech model. `base.en` is smaller and faster |

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
.venv/bin/python -m unittest tests/test_web.py -v    # accounts, access rules, test flow
.venv/bin/python -m unittest tests/test_moca.py -v   # scoring
(cd frontend && npm test)                            # frontend helpers
```

`test_web.py` needs no Supabase, microphone or browser. It checks who can see what: forged and expired tokens,
patients and examiners reaching each other's data, scores staying hidden until release, and what admins can and can't reach. CI runs it on every push.

`test_moca.py` and the speech harness cover synthetic good and bad cubes and clocks (wobbly lines, rotated paper, missing or extra
edges, mirrored cubes, squares, wrong times, reversed numbers…), the scoring maths, the score sheet,
the Task 1 path rules, naming and memory matching, digit span, serial 7s, the letter rules and the
hand-raise detector on synthetic video.

- `tests/speech_harness.py` runs synthesised voices through the real Task 1 pipeline. It needs
  optional test-only models (see the file).
- `TestRealPhotos` needs webcam photos in `tests/real_photos/`, which are not included in the repo
  (they show a real person). It fails without them.
- **Known:** 1 clock test fails: a synthetic clock with an extra "13" still gets the "numbers" point
  (`TestTask3Clock.test_cases`). With OpenCV 5, 3 more clock tests fail, which is why `requirements.txt`
  keeps OpenCV below 5.

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| "Supabase isn't set up yet" | Fill in `.env` (see `.env.example`) and restart the server |
| "Please sign in again" on every page | The app and `.env` point at different Supabase projects |
| Email links open the wrong site | Set the site address in Supabase under Authentication > URL Configuration |
| "doesn't match what your examiner entered" | The patient must type the same email and date of birth the examiner entered. The examiner can check them under **Patient links** |
| Invitation link opens the wrong site | Add your address to Redirect URLs in Supabase and set `MOCA_SITE_URL` |
| "this email already has a login that isn't set up" | Delete that login in Supabase (Authentication > Users), then add the person again |
| Invitation email never arrives | Supabase's built-in email has a low hourly limit; add your own SMTP provider |
| Blank page or "frontend isn't built yet" | Run `npm ci && npm run build` in `frontend/` |
| "Python 3.12 is needed" | Install Python 3.12 from python.org, then start again |
| `start.command` won't open | Right-click → **Open** → **Open** (first time only) |
| Page says "Server offline" | Start it again (`start.command`), and keep its Terminal window open |
| "Getting ready…" for a long time | First start downloads the speech model (about 500 MB). Check the internet connection. On a slow computer use `MOCA_WHISPER_MODEL=base.en`. |
| No microphone or camera | Chrome → Settings → Privacy and security → Site settings → Microphone / Camera → allow `127.0.0.1`. On macOS also check System Settings → Privacy & Security → Microphone / Camera → Google Chrome. |
| No voice | Check the volume, use Chrome, and try **Mic & camera → Play a test sentence** |
| Answers cut off or not heard | Speak closer to the microphone in a quiet room. **Done answering** ends an answer manually. |
| Cube or clock scores 0 unexpectedly | Open the test's results and look at the *annotated* photo: it shows what the scorer saw. Retake with even light, the whole drawing in view, the paper straight. |
| Task 7 asks for the Space key | The camera couldn't tell hand-up from hand-down. Better light, plain background, raise the hand beside the head. |
| Port 8000 already in use | `MOCA_PORT=8001 ./start.command`, then open `http://127.0.0.1:8001` |
| Page looks outdated after an update | Reload the page (the server tells the browser not to cache app files) |

The server log is in the Terminal window (or `server.log` when started by an AI assistant).

---

## 13. Known limitations

- **Not a medical device.** The automatic score is a first pass for a qualified examiner to check. Every
  recording, transcript and annotated photo is saved so they can.
- **Not yet ready for real patient data online.** See [section 5](#before-real-patients-use-it). There is no
  audit log of who viewed what, no multi-factor sign-in for examiners or admins and no automatic data retention.
- **The MoCA is copyrighted.** Check its licensing and training rules before offering this to the public.
- **Unsupervised testing.** The MoCA is normally given in person, so a remote result isn't the same as a
  clinic one. Examiner-run mode from the old app was replaced by patient self-testing.
- **The patient's browser receives the test content** (the five words, for example) because it has to read them
  aloud. A determined patient could find them. Scores are never sent to it before release.
- **Each server copy loads its own speech model**, which takes time on a fresh start (on Vercel, after a few
  minutes unused). Answers of a task in progress are stored in the database, so a restart or another copy can
  still finish the task.
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
- **Limited capacity:** one Whisper model on the CPU transcribes one phrase at a time, so simultaneous patients
  slow each other down. It hasn't been load tested.

---

## 14. Credits and licences

- **MoCA** is © Z. Nasreddine MD. Check the MoCA licensing and training requirements
  (<https://mocacognition.com>) before using it with patients.
- **Whisper** (OpenAI) via **faster-whisper**; **Silero VAD**.
- **mnist-8.onnx**: handwritten-digit model from the ONNX Model Zoo. `digits_hog_softmax.npz` is
  trained by `tools/train_digit_model.py`.
- **Figtree** font by Erik Kennedy, SIL Open Font License.
- The reference cube is drawn by the code, not scanned from a test sheet.
