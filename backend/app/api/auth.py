"""Login and current user."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.core.deps import DB, CurrentUser
from app.core.security import create_token, verify_password
from app.models.user import User
from app.schemas.api import LoginIn, LoginOut, UserOut
from app.state.store import store

router = APIRouter(prefix="/auth", tags=["Auth"])


_LOGIN_WINDOW = 15 * 60
_LOGIN_MAX_ATTEMPTS = 10


@router.post("/login", response_model=LoginOut)
async def login(payload: LoginIn, db: DB, request: Request):
    ip = request.client.host if request.client else "?"
    key = f"login:{ip}:{payload.username.strip().lower()}"
    if await store.bump_rate(key, _LOGIN_WINDOW) > _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Juda ko'p urinish. 15 daqiqadan keyin qayta urinib ko'ring")
    user = (await db.execute(
        select(User).where(User.username == payload.username.strip())
    )).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login yoki parol noto'g'ri")
    return LoginOut(access_token=create_token(str(user.id)), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
