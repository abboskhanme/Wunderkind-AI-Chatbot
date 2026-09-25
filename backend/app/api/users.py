"""User management (admin only)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from app.core.deps import DB, AdminUser, require_admin
from app.core.security import hash_password
from app.models.user import User
from app.schemas.api import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[UserOut])
async def list_users(db: DB):
    return (await db.execute(select(User).order_by(User.created_at))).scalars().all()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, db: DB):
    exists = (await db.execute(
        select(User.id).where(User.username == payload.username)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(400, "Bu login band")
    user = User(username=payload.username, full_name=payload.full_name,
                password_hash=hash_password(payload.password), role=payload.role,
                is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _get(db, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, payload: UserUpdate, db: DB, me: AdminUser):
    user = await _get(db, user_id)
    if user.id == me.id and (payload.is_active is False or payload.role == "operator"):
        raise HTTPException(400, "O'zingizni o'chira yoki rolingizni tushira olmaysiz")
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, db: DB, me: AdminUser):
    user = await _get(db, user_id)
    if user.id == me.id:
        raise HTTPException(400, "O'zingizni o'chira olmaysiz")
    await db.delete(user)
    await db.commit()
    return Response(status_code=204)
