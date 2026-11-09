"""
Create ready-to-use demo accounts: one admin, one examiner and one patient.

    .venv/bin/python -m webapp.make_demo_accounts

No emails are sent: each login gets a password straight away, printed at the end.
Running it again skips accounts that already exist. For demos and testing only:
anyone who knows these passwords can sign in.
"""

import secrets
import string
import sys

import httpx

from . import supabase_admin
from .accounts import new_examiner
from .db import Patient, SessionLocal, User, init_db

DEMO = [
    ("admin", "demo-admin@example.com", None),
    ("examiner", "demo-examiner@example.com",
     {"name": "Demo Examiner", "title": "Neuropsychologist", "organization": "Demo Clinic"}),
    ("patient", "demo-patient@example.com",
     {"name": "Demo Patient", "date_of_birth": "1955-06-15", "sex": "Female", "education_years": 10}),
]


def _password():
    letters = string.ascii_letters + string.digits
    return "Moca-" + "".join(secrets.choice(letters) for _ in range(10))


def _create_login(email, password):
    r = supabase_admin._call("POST", "/admin/users",
                             json={"email": email, "password": password, "email_confirm": True})
    if r.status_code == 422:
        return None                                   # this email already has a login
    if r.status_code >= 400:
        raise supabase_admin._failed(r)
    return r.json()["id"]


def main():
    init_db()
    created = []
    with SessionLocal() as db:
        for role, email, details in DEMO:
            if db.query(User).filter(User.email == email).first():
                print(f"  {role:<9} {email}  already exists, skipped")
                continue
            password = _password()
            user_id = _create_login(email, password)
            if user_id is None:
                print(f"  {role:<9} {email}  has a login but no account; delete it in Supabase "
                      "(Authentication > Users) and run this again")
                continue
            user = User(id=user_id, email=email, role=role)
            if role == "examiner":
                user.examiner = new_examiner(details)
            elif role == "patient":
                user.patient = Patient(**details)
            db.add(user)
            db.commit()
            created.append((role, email, password))
    if created:
        print("\nDemo accounts created. Save these passwords now; they aren't shown again:\n")
        for role, email, password in created:
            print(f"  {role:<9} {email:<28} {password}")
    print("\nSign in at the app's /login page.")


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, Exception) as e:          # one plain message for a non-technical user
        sys.exit(f"Could not create the demo accounts: {getattr(e, 'detail', e)}")
