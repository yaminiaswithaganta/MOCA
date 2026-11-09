"""
Put the app online on Hugging Face Spaces. Docker Spaces need a Hugging Face PRO subscription.

    .venv/bin/hf auth login                              # once: paste a Hugging Face access token
    .venv/bin/python deploy/huggingface.py moca-web      # create or update the Space

The Space is private and built from the Dockerfile. Only committed files are uploaded, so
.env, recordings and databases never leave this computer. The Supabase settings from .env
are stored as private Space secrets, and their values are never printed.

    .venv/bin/python deploy/huggingface.py moca-web --dry-run    # show what would happen
"""

import argparse
import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ["MOCA_SUPABASE_URL", "MOCA_SUPABASE_ANON_KEY", "MOCA_SUPABASE_SERVICE_KEY", "MOCA_DATABASE_URL"]
OPTIONAL = ["MOCA_SUPABASE_JWT_SECRET", "MOCA_WHISPER_MODEL", "MOCA_GOOGLE_LOGIN", "MOCA_STORAGE_BUCKET"]

# Hugging Face reads the Space's settings from the top of its README
SPACE_HEADER = """---
title: MoCA Cognitive Assessment
emoji: 🧠
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
short_description: Online MoCA screening for patients and examiners
---

"""


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def export_committed(dest):
    """The committed files of HEAD, without anything ignored or uncommitted."""
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")
    readme = Path(dest) / "README.md"
    readme.write_text(SPACE_HEADER + readme.read_text())


def space_url(repo_id):
    return "https://" + repo_id.replace("/", "-").replace("_", "-").replace(".", "-").lower() + ".hf.space"


def read_settings():
    env = ROOT / ".env"
    if not env.is_file():
        sys.exit("No .env file: the Space needs your Supabase settings. See SETUP_FOR_AI.md, Part B.")
    values = dotenv_values(env)
    missing = [k for k in SECRETS if not values.get(k) or "YOUR-" in values[k] or "PASSWORD@" in values[k]]
    if missing:
        sys.exit(f"Fill these in .env first: {', '.join(missing)}")
    return {k: values[k] for k in SECRETS + OPTIONAL if values.get(k)}


def main():
    parser = argparse.ArgumentParser(description="Deploy to Hugging Face Spaces")
    parser.add_argument("space", help="the Space's name, for example moca-web")
    parser.add_argument("--public", action="store_true", help="make the Space public (default: private)")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    args = parser.parse_args()

    settings = read_settings()
    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("Note: you have uncommitted changes. Only committed code is uploaded.\n")

    from huggingface_hub import HfApi
    api = HfApi()
    try:
        user = api.whoami()["name"]
    except Exception:
        sys.exit("Not signed in to Hugging Face. Run:  .venv/bin/hf auth login\n"
                 "and paste an access token with Write permission "
                 "(huggingface.co → Settings → Access Tokens).")
    repo_id = f"{user}/{args.space}"
    url = space_url(repo_id)
    settings["MOCA_SITE_URL"] = url

    with tempfile.TemporaryDirectory() as tmp:
        export_committed(tmp)
        files = sorted(str(p.relative_to(tmp)) for p in Path(tmp).rglob("*") if p.is_file())
        forbidden = [f for f in files if f == ".env" or f.endswith(".db") or f.startswith("results/")]
        if forbidden:
            sys.exit(f"Refusing to upload private files: {forbidden}")
        print(f"Space:   https://huggingface.co/spaces/{repo_id}  ({'public' if args.public else 'private'})")
        print(f"App:     {url}")
        print(f"Upload:  {len(files)} committed files from {git('rev-parse', '--short', 'HEAD').strip()}")
        print(f"Secrets: {', '.join(sorted(settings))}")
        if args.dry_run:
            print("\nDry run: nothing was changed.")
            return

        try:
            api.create_repo(repo_id, repo_type="space", space_sdk="docker",
                            private=not args.public, exist_ok=True)
        except Exception as e:
            if "402" in str(e):
                sys.exit("Hugging Face needs a PRO subscription to run Docker Spaces "
                         "(huggingface.co/pro). Nothing was created or uploaded.")
            raise
        for key, value in settings.items():
            api.add_space_secret(repo_id, key, value)
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=tmp,
                          commit_message=f"Deploy {git('rev-parse', '--short', 'HEAD').strip()}")

    print(f"""
Uploaded. The Space is building now (the first build takes 10 to 20 minutes).

Next:
  1. Watch the build:  https://huggingface.co/spaces/{repo_id}
  2. In Supabase → Authentication → URL Configuration:
       Site URL:       {url}
       Redirect URLs:  add {url}/**
  3. When it says Running, open:  {url}/api/status
     It shows "speech_ready":true once the speech model has loaded.
  4. Sign in at:  {url}/login
""")


if __name__ == "__main__":
    main()
