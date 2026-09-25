"""FastAPI dependencies: current user and role guards."""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)

DB = Annotated[AsyncSession, Depends(get_db)]


async def _user_from_token(db: AsyncSession, token: Optional[str]) -> User:
    data = decode_token(token) if token else None
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Avtorizatsiya talab qilinadi")
    try:
        user_id = uuid.UUID(str(data.get("sub")))
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token noto'g'ri") from None
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Foydalanuvchi faol emas")
    return user


async def get_current_user(
    db: DB,
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
) -> User:
    return await _user_from_token(db, creds.credentials if creds else None)


async def get_user_header_or_query(
    db: DB,
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
    token: Optional[str] = Query(default=None),
) -> User:
    """For <img src> / file downloads where a header cannot be set."""
    return await _user_from_token(db, creds.credentials if creds else token)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Faqat administrator uchun")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
