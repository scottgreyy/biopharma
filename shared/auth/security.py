"""
JWT security primitives + the FastAPI auth dependency, shared by all backends.

- Passwords hashed with bcrypt (via passlib).
- Tokens are signed JWTs (HS256) carrying the username as `sub` and an expiry.
- `require_auth` is the single dependency every protected route depends on;
  swapping the auth scheme later means editing only this file.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from shared.config import get_settings

_bearer = HTTPBearer(auto_error=True)

# We use the `bcrypt` library directly rather than passlib: passlib has been
# unmaintained since 2020 and breaks against bcrypt 4.x (it can't read the
# module version and mishandles the 72-byte limit). Direct bcrypt is simpler,
# maintained, and removes a fragile dependency.
_BCRYPT_MAX_BYTES = 72  # bcrypt truncates silently past this; we cap explicitly.


def _to_bytes(password: str) -> bytes:
    # Encode and enforce bcrypt's 72-byte input limit deterministically.
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_to_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(username: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.auth.jwt_expiry_minutes)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.auth.jwt_secret, algorithm=settings.auth.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.auth.jwt_secret, algorithms=[settings.auth.jwt_algorithm])


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Verify the bearer JWT and return the authenticated username."""
    settings = get_settings()  # noqa: F841 (kept for parity/explicitness)
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise cred_exc
    username = payload.get("sub")
    if not username:
        raise cred_exc
    return username
