"""
Create an administrator. Run on the server; there is no way to sign up as one.

    .venv/bin/python -m webapp.make_admin you@example.com

Prints a one-time link for choosing a password.
"""

import sys

from . import supabase_admin
from .db import SessionLocal, User, init_db


def main(email):
    email = email.strip().lower()
    init_db()
    site = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://127.0.0.1:8000"
    user_id, link = supabase_admin.link_for(email, f"{site}/reset-password")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is not None and user.role != "admin":
            sys.exit(f"{email} is already a {user.role}: an account has one role.")
        if user is None:
            db.add(User(id=user_id, email=email, role="admin"))
            db.commit()
    print(f"{email} is an administrator.\nOne-time link to choose a password:\n{link}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m webapp.make_admin you@example.com [site address]")
    main(sys.argv[1])
