# Setup instructions for an AI coding assistant

You (the AI assistant) are helping a non-technical user run this app on their own computer.
Do the whole setup yourself, step by step, and finish by giving them a link to click.
Explain what you're doing in one short, plain sentence per step. Don't ask them technical
questions. Ask only if something really needs their action (like typing their computer password).

## What this app is

A local web app for the MoCA (Montreal Cognitive Assessment). It has a Python server
(FastAPI) that does speech recognition (faster-whisper) and drawing scoring (OpenCV), and a
browser front end. Data goes in a SQLite file `moca.db` plus the `results/` folder.
It runs on this computer only, at `http://127.0.0.1:8000`.

## Rules

- **Never delete, overwrite or move `moca.db` or `results/`.** They hold real patient data.
- Never upload, share, commit or print the contents of `moca.db` or `results/`.
- Don't change the app's code. Only set it up and run it. If something is broken in the code,
  explain the error to the user instead of rewriting files.
- Work only inside this project folder (the one that contains `SETUP_FOR_AI.md`).

## Steps

### 1. Find a suitable Python (3.11, 3.12 or 3.13)

Python 3.14 and newer, and 3.10 and older, are **not** suitable: some packages have no builds for them.
Check in this order and use the first that works:

```bash
python3.12 --version; python3.11 --version; python3.13 --version; python3 --version
```

If none of them is 3.11–3.13, install Python 3.12:
- If Homebrew exists (`brew --version`): `brew install python@3.12`
- Otherwise use uv (no admin rights needed):
  `curl -LsSf https://astral.sh/uv/install.sh | sh`, then `~/.local/bin/uv python install 3.12`,
  and use `~/.local/bin/uv python find 3.12` to get the Python path.
- On Windows: `winget install Python.Python.3.12`, then use `py -3.12`.

### 2. Create the environment and install packages

From the project folder (skip creating `.venv` if it already exists and works):

```bash
<python3.12> -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-web.txt
touch .venv/.installed
```

On Windows, use `.venv\Scripts\python` in place of `.venv/bin/python`, and skip the `touch` line.
The install downloads about 1 GB and can take several minutes. Tell the user it's working.
`touch .venv/.installed` tells `start.command` that setup is done, so it won't reinstall later.

### 3. Start the app (in the background, so it keeps running)

First check whether it's already running: `curl -s http://127.0.0.1:8000/api/status`.
If that returns JSON, it's running. Skip to step 4.

Otherwise start it:

```bash
nohup .venv/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
```

If port 8000 is taken by a different program, use port 8001 instead (and use that port in the link).
On Windows, start it with
`Start-Process .venv\Scripts\python -ArgumentList "-m uvicorn webapp.server:app --host 127.0.0.1 --port 8000" -WindowStyle Hidden`.

### 4. Check it works

1. Repeat `curl -s http://127.0.0.1:8000/api/status` until it returns JSON (up to about 30 seconds).
2. The first start downloads the speech model (about 500 MB). Repeat the same check every
   15 seconds until it shows `"speech_ready": true`. This can take several minutes. If it shows
   `"speech_error"`, read `server.log` and fix the cause, usually a network problem; then restart step 3.
   On a slow computer or connection, you may restart with the smaller model by putting
   `MOCA_WHISPER_MODEL=base.en ` in front of the start command.
3. `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/` must print `200`.
4. If anything fails, read `server.log`, fix the setup problem (missing package, wrong Python,
   port in use), and try again.

### 5. Hand over to the user

Give them the link, **http://127.0.0.1:8000** (or the port you used), and tell them, in these words or similar:

- "Open this link in Google Chrome. Allow the microphone and camera when Chrome asks."
- "Wait for the green 'Speech ready' sign at the top, then press 'Start test'."
- "Next time, just double-click `start.command` in this folder. It opens the app by itself."
  (On Windows, tell them to ask you to start it again instead.)
- "To stop the app, restart the computer, or ask me to stop it."

If you are asked to stop it later: `lsof -ti tcp:8000 | xargs kill` (macOS/Linux).

## Useful facts if something goes wrong

- Server log: `server.log` in the project folder.
- Status: `http://127.0.0.1:8000/api/status` shows whether speech recognition is ready.
- The camera and microphone are used by the **browser**, not by Python. Permission problems are
  fixed in Chrome's site settings (and in macOS System Settings → Privacy & Security for Chrome).
- Instructions are spoken by the browser's built-in voice. If there's no sound, check the
  computer's volume and use Chrome.
- More detail on how the app works: `README.md`.
