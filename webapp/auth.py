"""
Who is calling: checks the Supabase access token and finds the user's row.

The browser logs in directly with Supabase and sends the access token on every request.
New Supabase projects sign tokens with a key pair (checked against the project's public
keys); older ones share a secret (MOCA_SUPABASE_JWT_SECRET).
"""

import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import Examiner, Patient, SessionLocal, User

SUPABASE_URL = os.environ.get("MOCA_SUPABASE_URL", "").rstrip("/")
JWT_SECRET = os.environ.get("MOCA_SUPABASE_JWT_SECRET", "")
ISSUER = f"{SUPABASE_URL}/auth/v1"
ASYMMETRIC = ("ES256", "RS256")

_jwks = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True) if SUPABASE_URL else None


@dataclass
class Identity:
    id: str
    email: str


def verify_token(token):
    """The Identity in a Supabase access token. Raises HTTPException(401) if it isn't valid."""
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg in ASYMMETRIC and _jwks is not None:
            key = _jwks.get_signing_key_from_jwt(token).key
        elif alg == "HS256" and JWT_SECRET:
            key = JWT_SECRET
        else:
            raise jwt.InvalidAlgorithmError(f"unexpected token algorithm {alg}")
        # only the algorithm chosen above, so a token can't pick how it is checked
        claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated", issuer=ISSUER)
        return Identity(id=claims["sub"], email=claims.get("email", ""))
    except (jwt.PyJWTError, KeyError) as e:
        raise HTTPException(401, "please sign in again") from e


def get_db():
    with SessionLocal() as db:
        yield db


def current_identity(authorization: str = Header(default="")):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "please sign in")
    return verify_token(token)


def current_user(identity: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    user = db.get(User, identity.id)
    if user is None:
        raise HTTPException(403, "finish setting up your account first")
    if user.deactivated_at is not None:
        raise HTTPException(403, "this account has been deactivated")
    return user


def current_patient(user: User = Depends(current_user)) -> Patient:
    if user.role != "patient":
        raise HTTPException(403, "this is for patients")
    return user.patient


def current_examiner(user: User = Depends(current_user)) -> Examiner:
    if user.role != "examiner":
        raise HTTPException(403, "this is for examiners")
    return user.examiner


def current_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "this is for administrators")
    return user
