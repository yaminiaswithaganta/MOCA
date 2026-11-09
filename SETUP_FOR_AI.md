# Setup and deployment guide (for an AI coding assistant)

**To the person reading this:** open this project folder in Claude Code (or another AI coding
assistant) and say: *"Read SETUP_FOR_AI.md and walk me through it."* The assistant will do the
technical work and tell you the few things only you can do, such as clicking in a website.

**To the AI assistant:** you are helping a non-technical person set up and run this app, and
optionally put it online. Follow this guide in order. Do the technical work yourself. Explain each
step in one short, plain sentence. Ask the person to act only when they must: logging in to a
website, clicking a button, copying a value, or typing their computer password.

---

## 0. Before anything else

### What this app is
A web app for the MoCA (Montreal Cognitive Assessment) with three kinds of accounts:

- **Admin:** adds examiners with an email and a password it chooses (no emails sent). Can't see results.
- **Examiner:** adds patients and sends each one a link, designs tests, reviews answers, corrects scores and
  releases results.
- **Patient:** opens the examiner's link, confirms name, email and date of birth, and takes the test by voice
  and camera. Patients can also sign up themselves.

How it's built:
- **Server:** Python (FastAPI) in `webapp/`. It also runs speech recognition (faster-whisper) and
  drawing scoring (OpenCV).
- **Screens:** React + TypeScript in `frontend/`. They're built into `frontend/dist`, and the
  Python server serves them.
- **Accounts, database and file storage:** a Supabase project. The app never stores data in the
  code folder, apart from working copies of recordings in `results/`.
- **Settings:** a file named `.env` in the project folder. It holds the Supabase keys. **It's not
  in GitHub on purpose.**

### Rules you must follow
1. **Never show, print, log or paste the contents of `.env`**, or any key, password or database
   address. If you need to check a value, check its format (for example "starts with
   `sb_secret_`"), never the value itself.
2. **Never commit `.env`** or put keys in any other file. Check `git status` before any commit.
3. **Never ask the person to paste keys into the chat.** Tell them to paste each key straight into
   the `.env` file in the editor and save it.
4. **Never delete or overwrite** `.env`, `results/`, `moca.db` or `moca_local.db`. They may hold
   patient data.
5. **Don't change the app's code.** If something is broken in the code, explain the error instead
   of rewriting files.
6. Work only inside this project folder (the one containing this file).
7. **Never screenshot a page that shows a secret key.**

### Ask these two questions first
Ask the person, then follow the matching path:

1. **"Do you already have the `.env` file from the person who built this?"**
   - **Yes:** they'll put it in the project folder in Part A, step 4. Skip Part B unless the app
     can't connect.
   - **No:** they'll get the values themselves in Part B.
2. **"Do you only want to run it on this computer, or also put it online so others can use it
   from their own devices?"**
   - **This computer only:** do Parts A to C.
   - **Online too:** do Parts A to C, then Part D.

---

## Part A: Run the app on this computer

### A1. Check the computer
Find out the operating system (macOS or Windows). On Windows, use `.venv\Scripts\python` wherever
this guide says `.venv/bin/python`, and run commands in PowerShell.

### A2. Install Python 3.12 and Node.js
**Python:** it must be **3.11, 3.12 or 3.13**. 3.14+ and 3.10 and older won't work. Check in this
order and use the first that works:

```bash
python3.12 --version; python3.11 --version; python3.13 --version; python3 --version
```

If none is suitable, install Python 3.12:
- macOS with Homebrew (`brew --version` works): `brew install python@3.12`
- macOS without Homebrew: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then
  `~/.local/bin/uv python install 3.12`, then use `~/.local/bin/uv python find 3.12` as the Python
  path.
- Windows: `winget install Python.Python.3.12`, then use `py -3.12`.

**Node.js:** version 20 or newer. Check with `node --version`. If it's missing or older:
- macOS: `brew install node`, or ask the person to install the **LTS** version from
  https://nodejs.org
- Windows: `winget install OpenJS.NodeJS.LTS`

### A3. Install the app
From the project folder:

```bash
<python3.12> -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-web.txt
cd frontend && npm ci && npm run build && cd ..
```

This downloads about 1 GB and takes several minutes, so tell the person it's working. If `.venv`
already exists, still run the `pip install` line, because requirements change over time (OpenCV
must be version 4, not 5).

Check it worked:
```bash
.venv/bin/python -c "import cv2, fastapi; print('opencv', cv2.__version__)"
ls frontend/dist/index.html
```
OpenCV must start with `4.`.

### A4. Put the `.env` file in place
- **If they have the file:** ask them to put it in the project folder (the folder containing this
  guide), named exactly `.env`, with nothing before or after. On macOS it's hidden in Finder;
  `Cmd + Shift + .` shows hidden files. Messaging apps sometimes rename it to `env` or `env.txt`,
  so check with `ls -a`.
- **If they don't have it:** run `cp .env.example .env` (Windows: `copy .env.example .env`), then
  do Part B.

Then check, without printing values:
```bash
.venv/bin/python - <<'EOF'
from dotenv import dotenv_values
v = dotenv_values(".env")
for k in ["MOCA_SUPABASE_URL", "MOCA_SUPABASE_ANON_KEY", "MOCA_SUPABASE_SERVICE_KEY", "MOCA_DATABASE_URL"]:
    s = v.get(k) or ""
    print(k, "OK" if s and "YOUR-" not in s and "PASSWORD@" not in s else "MISSING OR PLACEHOLDER")
EOF
```
All four must say `OK`. If any don't, do Part B.

### A5. Start the app
- **macOS (easiest):** the person double-clicks `start.command`. The first time, they right-click
  it, choose **Open**, then **Open** again.
- **Any system, or when you start it yourself**, run it in the background so it keeps running:

```bash
.venv/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
```

The first start downloads the speech model (about 500 MB). Wait until this returns
`"speech_ready":true`:
```bash
curl -s http://127.0.0.1:8000/api/status
```

Then check the connection to Supabase:
```bash
curl -s http://127.0.0.1:8000/api/public-config
```
It must show a `supabase_url` ending in `.supabase.co`. Look in `server.log` for any line containing
`password authentication failed`, `401` or `Traceback`. If you find one, go to Part B.

Give the person this link: **http://127.0.0.1:8000**. Tell them to use **Google Chrome** and to
click **Allow** when it asks for the microphone and camera.

This address only works on the computer running the app. Other people can't open it. For that,
do Part D.

---

## Part B: Connect the Supabase project

Do this if there's no `.env` file, or if the app can't connect: for example "please sign in again"
on every page, "password authentication failed", or a 401 error.

The person needs to be logged in to https://supabase.com/dashboard and to be an **Owner** of the
organization that holds the project. If the builder invited them, they accept the invitation email
first. The project is called something like `moca-web` or `moca-autoscoring`.

Guide them through each step. They copy each value from the website and **paste it straight into
`.env` in the editor**, after the `=` sign, with no spaces or quotes. They don't paste it into the
chat. Remind them to save (**Cmd + S** or **Ctrl + S**) after each one.

### B1. Project URL
**Project Settings** (gear icon, bottom left) → **API Keys** or **Data API**. Copy the **Project
URL** (`https://xxxxxxxx.supabase.co`) into:
```
MOCA_SUPABASE_URL=
```

### B2. Publishable key (safe to share)
Same page, **API Keys** tab. Copy the **publishable** key (starts with `sb_publishable_`), or the
legacy **anon** key, into:
```
MOCA_SUPABASE_ANON_KEY=
```

### B3. Secret key (private)
Same page, under **Secret keys**:
1. Click **New secret key** and name it after this computer or the hosting service, for example
   `moca-laptop`.
2. Copy it (starts with `sb_secret_`) into:
   ```
   MOCA_SUPABASE_SERVICE_KEY=
   ```
3. **Security:** a secret key was once shown in a screenshot. Once the app works with the new key,
   ask the person to delete any secret key they don't recognise or no longer use, with the **⋮**
   menu on its row. Never delete the key the app is using.

### B4. Database address
1. Click the green **Connect** button at the top of the Supabase page.
2. Choose **Direct** ("Connection string"), then find **Session pooler**.
3. Copy the address. It must contain `pooler.supabase.com` and end with `:5432/postgres`.
4. Paste it into:
   ```
   MOCA_DATABASE_URL=
   ```
5. Replace `[YOUR-PASSWORD]`, including the square brackets, with the database password.

If they don't know the password: **Project Settings → Database → Reset database password**. Tell
them to use **only letters and numbers**, because symbols break the address. They type it into
`.env`, not the chat.

### B5. Allow the app's address
**Authentication → URL Configuration**:
- **Site URL:** `http://127.0.0.1:8000` (change it to the online address after Part D)
- **Redirect URLs:** add `http://127.0.0.1:8000/**`

Without this, invitation and password-reset links don't work.

### B6. Check and restart
Run the check in A4. All four must say `OK`. Then restart the app (stop it, then start it as in
A5) and check `server.log` again. Database tables are created automatically on start.

---

## Part C: Create the accounts and try it

### C0. Quickest: demo accounts (one command, no emails)
For a demo or to try the app, this creates one admin, one examiner (with the Standard MoCA ready)
and one patient, each with a password, and prints them:

```bash
.venv/bin/python -m webapp.make_demo_accounts
```

Show the person the three emails and passwords it prints, and tell them to save them, because
they aren't shown again. Running it again skips accounts that already exist. These accounts use
`@example.com` addresses that can't receive email, so "Forgot password" won't work for them. If a
password is lost, delete that login in Supabase (**Authentication → Users**) and run the command
again. Anyone who knows these passwords can sign in, so use them only for demos and testing.

For the person's own admin login, which they'll keep, use C1 as well.

### C1. Create the admin
There's no way to sign up as an admin. It's created from the server. Ask for the email they want
to use. **It should be an inbox they can open**, so password resets reach them. Then run:

```bash
.venv/bin/python -m webapp.make_admin THEIR-EMAIL http://127.0.0.1:8000
```

It prints a one-time link. Give it to them, and tell them to open it soon and choose a password.
It works once and expires. If it fails, run the command again for a new link. If the email is
already an admin, the command just prints a new link.

### C2. Try the app (about 10 minutes)
With the demo accounts from C0, they can sign in as each role straight away and skip steps 2 to 4.
Otherwise, guide them through this:
1. **Sign in** at http://127.0.0.1:8000/login with the admin email and password. They land on
   **People**.
2. **Add an examiner:** **Add examiner**. Fill in the name, title, organisation, an email and a
   password. No email is sent: they sign in with that email and password straight away.
3. **Become the examiner:** in a **private window**, sign in with that email and password. Go to
   **Test designs**: a **Standard MoCA** is already there. For a quick try, create a short test
   with 1 or 2 tasks and tick **Published**. Then **Patients → Add patient**: enter a patient's
   name, email and date of birth, and copy the link it shows.
4. **Become the patient:** open the link in another private window. Enter the same name, email
   and date of birth, plus years of education, and press **Continue**. They're signed in with the
   examiner already chosen: choose the test, tick the consent box, **Begin test**, then **Start**.
5. **Review as the examiner:** **Overview** → open the test → check the answers → **Release
   result**.
6. **See the result as the patient:** reload the patient window.

Supabase's built-in email sends only a few emails an hour. If an invitation doesn't arrive, wait,
or set up an email provider (Part E, "Emails don't arrive").

---

## Part D: Put the app online (optional)

Only do this if they want people to use it from their own devices.

### D1. What the app needs from a host
Explain these simply. They decide which host to use:

- **Long-running server with WebSockets.** Serverless platforms like Vercel or Netlify **won't
  work**, because speech recognition needs a server that stays on.
- **At least 2 GB of memory, ideally 4 GB, and 2 CPUs.** Speech recognition is heavy. On a smaller
  plan, add the setting `MOCA_WHISPER_MODEL=base.en` (smaller and faster, a bit less accurate).
- **HTTPS.** Browsers only allow the microphone on secure (`https://`) sites. Most hosts provide
  this.
- **Run one copy.** Don't scale to more than 1 instance: tests in progress are held in that
  server's memory.
- **It costs money.** Free plans are usually too small. Check current prices on the host's website
  before choosing. For an academic project, ask the supervisor whether the university has a server.

The project has a `Dockerfile`, so any host that builds from a Dockerfile in a GitHub repo works.
**Railway** and **Render** both do this from a website, with no command line. The steps below use
Railway; Render is very similar. Hosting websites change often, so follow what's on screen and
adapt.

### D2. Code on GitHub
The code is at https://github.com/yaminiaswithaganta/MOCA. The working branch is
**`fullstack-roles`** (there may be no `main` branch yet). The person needs a GitHub account with
access to this repository.

### D3. Create the service (Railway example)
1. Sign in at https://railway.com with GitHub.
2. **New Project → Deploy from GitHub repo** → choose `MOCA`.
3. In the service's settings, set the branch to **`fullstack-roles`**.
4. It detects the `Dockerfile` automatically. Don't add a start command, because the Dockerfile has
   one. The app reads the `PORT` the host gives it.
5. Choose a plan or size with at least 2 GB of memory.
6. **Networking:** generate a public domain. They get an address like
   `https://moca-xxxx.up.railway.app`, which is the **online address** used below.

### D4. Add the settings
In the service's **Variables** (sometimes called Environment), add each line from their `.env`
file as a variable. They copy the values from `.env` themselves:

| Variable | Value |
|---|---|
| `MOCA_SUPABASE_URL` | same as in `.env` |
| `MOCA_SUPABASE_ANON_KEY` | same as in `.env` |
| `MOCA_SUPABASE_SERVICE_KEY` | **best:** a new secret key named `moca-online`, made as in B3 |
| `MOCA_DATABASE_URL` | same as in `.env` |
| `MOCA_SITE_URL` | **the online address**, for example `https://moca-xxxx.up.railway.app` (no `/` at the end) |
| `MOCA_WHISPER_MODEL` | only on small plans: `base.en` |

Most hosts have a "Raw editor" where they can paste all lines at once. If they use it, they must
change `MOCA_SITE_URL` to the online address.

### D5. Tell Supabase about the online address
**Authentication → URL Configuration**:
- **Site URL:** the online address
- **Redirect URLs:** add `https://THE-ONLINE-ADDRESS/**`, and keep `http://127.0.0.1:8000/**` if
  they still use it locally

### D6. Deploy and check
1. Deploy, or wait for it to finish building. The first build and start take several minutes,
   because it installs everything and downloads the speech model.
2. Check: open `https://THE-ONLINE-ADDRESS/api/status` in a browser. It should show
   `"speech_ready":true` after a few minutes.
3. Open the online address, sign in as the admin, and repeat the quick try in C2. Use **Chrome**
   and allow the microphone.
4. Admin invitation emails now link to the online address, because of `MOCA_SITE_URL`.

### D7. Things to know once it's online
- **Every redeploy restarts the server.** Finished tasks and results are safe in Supabase, but a
  task someone is in the middle of is lost. Avoid redeploying while people are taking tests.
- **Logs** are in the host's dashboard. Look there first if something breaks.
- **Updating:** push new code to `fullstack-roles` on GitHub, and the host redeploys automatically.
- **Create another admin from the online address:**
  `.venv/bin/python -m webapp.make_admin EMAIL https://THE-ONLINE-ADDRESS`, run on any computer
  with the `.env` file, because it talks to the same Supabase project.

---

## Part E: Fixing problems

| What they see | What to do |
|---|---|
| "Supabase isn't set up yet" | `.env` is missing or empty. Do A4, then Part B. |
| "Please sign in again" on every page | `MOCA_SUPABASE_URL` or the keys belong to a different project. Recheck B1–B3. |
| Signs in, then the page fails, or `password authentication failed` in the log | Database password is wrong. B4: reset it (letters and numbers only), update `.env`, restart. |
| `401` errors in the log, or adding people fails | Secret key was deleted or is wrong. B3: make a new one, update `.env` (or the host's variables), restart. |
| Invitation or reset link opens the wrong site or says "invalid" | B5 / D5: Site URL and Redirect URLs must match the address in use. Set `MOCA_SITE_URL` the same. Links work once and expire, so send a new one. |
| "This email already has a login that isn't set up" | Delete that login in Supabase (**Authentication → Users**), then add the person again. |
| Patient link says details don't match | The patient must type exactly the email and date of birth the examiner entered (shown under **Patients → Patient links**). |
| Someone forgot their password | Admin: **People → ⋯ → Set new password**, then tell them the new one. Patients from a link don't need one: they open their link again. |
| Emails don't arrive | The app only sends emails for self sign-up and "Forgot password". Supabase's built-in email sends only a few an hour, so wait. For more, add an email provider under **Authentication → Emails → SMTP** (Resend and Brevo have free tiers). |
| "Getting ready…" for a long time | First start downloads the speech model. Check internet. On slow computers or small servers, set `MOCA_WHISPER_MODEL=base.en`. |
| "No sound reached the app" during a test | Microphone blocked. In Chrome: **Settings → Privacy and security → Site settings → Microphone**, allow the site. On macOS also: **System Settings → Privacy & Security → Microphone → Chrome**. Then **Try this task again**. |
| No camera | Same as above, under **Camera**. Close other apps using the camera. |
| Microphone doesn't work on the online site | The address must start with `https://`. |
| Blank page, or "the frontend isn't built yet" | Run `cd frontend && npm ci && npm run build && cd ..`. Online: the Dockerfile does this; check the build log. |
| `Address already in use` | The app is already running. Open http://127.0.0.1:8000, or stop the old one first. |
| Task 7 (letters) asks to press Space | Normal: the camera couldn't see the hand clearly, so the patient presses Space at each A. |
| OpenCV version starts with `5.` | Run `.venv/bin/python -m pip install -r requirements-web.txt` again. It must be 4. |
| Supabase project "paused" | Free projects pause after a period of inactivity. Restore it in the Supabase dashboard. |

To restart the app on this computer: stop it (close the `start.command` window, or
`kill $(lsof -ti:8000)` on macOS), then start it again as in A5.

---

## Part F: Good to know

- **Where data lives:** accounts, test results, recordings and photos are in the Supabase project.
  Removing the app from a computer doesn't delete any data.
- **Who sees what:** patients see their score only after an examiner releases it. Examiners see only
  their own patients. Admins manage accounts but can't see results.
- **Academic use:** use made-up names and data for demos. Before testing on real people, ask the
  supervisor about ethics approval and the MoCA licence.
- **More detail:** `README.md` has the full documentation, and `HOW TO START.txt` has a short
  version.
