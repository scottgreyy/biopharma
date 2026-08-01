"""
Auth routes shared by all three backends. Each FastAPI app includes this
router, so register/login behave identically regardless of which approach's
port the Streamlit app talks to.

  POST /auth/register  -> create a user
  POST /auth/login     -> exchange username/password for a JWT
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from shared.auth.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from shared.auth.users import create_user, ensure_users_table, get_user

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(creds: Credentials) -> TokenResponse:
    await ensure_users_table()
    ok = await create_user(creds.username, hash_password(creds.password))
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists.",
        )
    token = create_access_token(creds.username)
    return TokenResponse(access_token=token, username=creds.username)


@router.post("/login", response_model=TokenResponse)
async def login(creds: Credentials) -> TokenResponse:
    await ensure_users_table()
    user = await get_user(creds.username)
    if not user or not verify_password(creds.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    token = create_access_token(creds.username)
    return TokenResponse(access_token=token, username=creds.username)
