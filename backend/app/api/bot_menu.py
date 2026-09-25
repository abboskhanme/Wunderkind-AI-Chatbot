"""Telegram bot menu management (admin)."""
from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from app import runtime_config
from app.config import settings
from app.core.deps import DB, get_user_header_or_query, require_admin
from app.models.bot_menu import (
    ALLOWED_IMAGE_TYPES, MAX_IMAGE_BYTES, MAX_IMAGES_PER_ITEM, RESERVED_COMMANDS,
    BotMenuImage, BotMenuItem,
)
from app.schemas.api import GreetingIn, MenuItemIn, MenuItemOut, MenuItemPatch, MenuOut, ReorderIn

router = APIRouter(prefix="/bot-menu", tags=["Bot menu"])
admin = [Depends(require_admin)]


async def _refresh_bot() -> None:
    try:
        from app.telegram_business import menu

        await menu.refresh()
    except Exception:  # noqa: BLE001
        pass


async def _items(db) -> list[BotMenuItem]:
    return list((await db.execute(
        select(BotMenuItem).order_by(BotMenuItem.sort_order, BotMenuItem.created_at)
    )).scalars().all())


async def _item(db, item_id: uuid.UUID) -> BotMenuItem:
    item = await db.get(BotMenuItem, item_id)
    if not item:
        raise HTTPException(404, "Bo'lim topilmadi")
    return item


async def _check_command(db, command: str, exclude: uuid.UUID | None = None) -> None:
    if command in RESERVED_COMMANDS:
        raise HTTPException(400, f"/{command} buyrug'i band — boshqa nom tanlang")
    q = select(BotMenuItem.id).where(BotMenuItem.command == command)
    if exclude:
        q = q.where(BotMenuItem.id != exclude)
    if (await db.execute(q)).scalar_one_or_none():
        raise HTTPException(400, f"/{command} buyrug'i allaqachon mavjud")


@router.get("", response_model=MenuOut, dependencies=admin)
async def get_menu(db: DB):
    return MenuOut(greeting=settings.TG_MENU_GREETING or "", items=await _items(db))


@router.put("/greeting", dependencies=admin)
async def set_greeting(payload: GreetingIn, db: DB):
    await runtime_config.save(db, {"TG_MENU_GREETING": payload.greeting})
    await _refresh_bot()
    return {"greeting": settings.TG_MENU_GREETING}


@router.post("/items", response_model=MenuItemOut, status_code=201, dependencies=admin)
async def create_item(payload: MenuItemIn, db: DB):
    await _check_command(db, payload.command)
    max_order = (await db.execute(select(func.max(BotMenuItem.sort_order)))).scalar() or 0
    item = BotMenuItem(command=payload.command, title=payload.title.strip(),
                       text=payload.text, is_active=payload.is_active,
                       sort_order=max_order + 1)
    db.add(item)
    await db.commit()
    await db.refresh(item, ["images"])
    await _refresh_bot()
    return item


@router.patch("/items/{item_id}", response_model=MenuItemOut, dependencies=admin)
async def update_item(item_id: uuid.UUID, payload: MenuItemPatch, db: DB):
    item = await _item(db, item_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("command"):
        await _check_command(db, data["command"], exclude=item.id)
    for key, value in data.items():
        if value is not None or key == "text":
            setattr(item, key, value)
    await db.commit()
    await db.refresh(item, ["images"])
    await _refresh_bot()
    return item


@router.delete("/items/{item_id}", status_code=204, dependencies=admin)
async def delete_item(item_id: uuid.UUID, db: DB):
    await db.delete(await _item(db, item_id))
    await db.commit()
    await _refresh_bot()
    return Response(status_code=204)


@router.post("/items/reorder", response_model=list[MenuItemOut], dependencies=admin)
async def reorder(payload: ReorderIn, db: DB):
    items = {i.id: i for i in await _items(db)}
    for index, item_id in enumerate(payload.ids):
        if item_id in items:
            items[item_id].sort_order = index
    await db.commit()
    await _refresh_bot()
    return await _items(db)


@router.post("/items/{item_id}/images", response_model=MenuItemOut, dependencies=admin)
async def upload_images(item_id: uuid.UUID, db: DB, files: list[UploadFile] = File(...)):
    item = await _item(db, item_id)
    if len(item.images) + len(files) > MAX_IMAGES_PER_ITEM:
        raise HTTPException(400, f"Bitta bo'limda ko'pi bilan {MAX_IMAGES_PER_ITEM} ta rasm")
    order = max((img.sort_order for img in item.images), default=-1)
    for f in files:
        if f.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(400, f"{f.filename}: faqat JPG, PNG yoki WEBP")
        data = await f.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(400, f"{f.filename}: 5 MB dan katta")
        if not data:
            raise HTTPException(400, f"{f.filename}: bo'sh fayl")
        order += 1
        db.add(BotMenuImage(item_id=item.id, content_type=f.content_type, data=data,
                            size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            sort_order=order))
    await db.commit()
    db.expire(item)
    item = await _item(db, item_id)
    await db.refresh(item, ["images"])
    await _refresh_bot()
    return item


@router.delete("/images/{image_id}", status_code=204, dependencies=admin)
async def delete_image(image_id: uuid.UUID, db: DB):
    image = await db.get(BotMenuImage, image_id)
    if not image:
        raise HTTPException(404, "Rasm topilmadi")
    await db.delete(image)
    await db.commit()
    await _refresh_bot()
    return Response(status_code=204)


@router.get("/images/{image_id}")
async def get_image(image_id: uuid.UUID, db: DB,
                    user=Depends(get_user_header_or_query)):
    if user.role != "admin":
        raise HTTPException(403, "Faqat administrator uchun")
    image = (await db.execute(
        select(BotMenuImage).options(undefer(BotMenuImage.data))
        .where(BotMenuImage.id == image_id)
    )).scalar_one_or_none()
    if not image:
        raise HTTPException(404, "Rasm topilmadi")
    return Response(content=image.data, media_type=image.content_type,
                    headers={"Cache-Control": "private, max-age=3600"})
