"""Funnel management (SPEC §11.3): `/api/funnel/funnels`.

A,O may list funnels (the Voronka switcher); only admins create/edit/delete.
Rules: slug a-z0-9_ unique; the default funnel cannot be deactivated or
deleted; a funnel with entries cannot be deleted (409 → archive it instead);
an active funnel's keywords must not collide with another active funnel that
covers the same Instagram posts (400).
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.exc import IntegrityError

from app import runtime_config
from app.core.deps import DB, get_current_user, require_admin
from app.core.settings_catalog import CATALOG_BY_KEY
from app.funnel import funnels
from app.funnel.funnels import FunnelView
from app.models.funnel import (
    FUNNEL_TEXT_KEYS, LEAD_MAGNET_KEY, Funnel, FunnelEntry, FunnelFile, FunnelMessage,
    InterviewBooking,
)
from app.schemas.api import ReorderIn
from app.schemas.funnel import FunnelCounts, FunnelIn, FunnelLinks, FunnelOut, FunnelPatch

router = APIRouter(prefix="/funnel", tags=["Funnels"])
staff = [Depends(get_current_user)]
admin = [Depends(require_admin)]


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
async def _outputs(db, rows: list[Funnel]) -> list[FunnelOut]:
    """FunnelOut for many funnels with 3 grouped queries (no per-funnel queries)."""
    from app.services.agent_status import telegram_bot_username

    ids = [f.id for f in rows]
    counts = {fid: (n, pdf) for fid, n, pdf in (await db.execute(
        select(FunnelEntry.funnel_id, func.count(), func.count(FunnelEntry.pdf_sent_at))
        .where(FunnelEntry.funnel_id.in_(ids)).group_by(FunnelEntry.funnel_id))).all()}
    booked = dict((await db.execute(
        select(FunnelEntry.funnel_id, func.count(distinct(InterviewBooking.entry_id)))
        .join(FunnelEntry, FunnelEntry.id == InterviewBooking.entry_id)
        .where(FunnelEntry.funnel_id.in_(ids)).group_by(FunnelEntry.funnel_id))).all())
    with_pdf = set((await db.execute(
        select(FunnelFile.funnel_id).where(FunnelFile.funnel_id.in_(ids),
                                           FunnelFile.key == LEAD_MAGNET_KEY))).scalars().all())
    bot = await telegram_bot_username()
    out = []
    for row in rows:
        view = FunnelView.of(row)
        entries, pdf = counts.get(row.id, (0, 0))
        out.append(FunnelOut(
            id=row.id, name=row.name, slug=row.slug, is_active=row.is_active,
            is_default=row.is_default, keywords=row.keywords or "",
            ig_media_ids=row.ig_media_ids or "",
            texts={k: v for k, v in (row.texts or {}).items() if isinstance(v, str)},
            sort_order=row.sort_order or 0,
            links=FunnelLinks(
                telegram_channel=f"https://t.me/{bot}?start={view.channel_payload}" if bot else None,
                telegram_direct=f"https://t.me/{bot}?start={view.direct_payload}" if bot else None),
            stats=FunnelCounts(entries=int(entries), pdf_sent=int(pdf),
                               booked=int(booked.get(row.id, 0))),
            has_pdf=row.id in with_pdf, created_at=row.created_at,
        ))
    return out


async def _all_rows(db) -> list[Funnel]:
    return list((await db.execute(
        select(Funnel).order_by(Funnel.sort_order, Funnel.created_at))).scalars().all())


async def _row(db, funnel_id: uuid.UUID) -> Funnel:
    row = await db.get(Funnel, funnel_id)
    if row is None:
        raise HTTPException(404, "Voronka topilmadi")
    return row


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _clean_texts(values: dict[str, Optional[str]]) -> dict[str, str]:
    """Whitelisted overrides only; empty = use the global text; same checks as the
    global setting (lengths, grades, button)."""
    unknown = set(values) - set(FUNNEL_TEXT_KEYS)
    if unknown:
        raise HTTPException(400, f"Noma'lum matn kaliti: {', '.join(sorted(unknown))}")
    clean: dict[str, str] = {}
    for key, value in values.items():
        if value is None or not str(value).strip():
            continue
        text = str(value) if CATALOG_BY_KEY[key].type == "textarea" else str(value).strip()
        try:
            runtime_config.validate(key, text)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        clean[key] = text
    return clean


def _merge_texts(base: Optional[dict], changes: dict[str, Optional[str]]) -> dict[str, str]:
    """Apply override changes: text sets a key, ""/null removes it (→ global), keys
    not mentioned stay as they are."""
    kept = {k: v for k, v in (base or {}).items() if k not in changes}
    return {**kept, **_clean_texts(changes)}


def _clean_keywords(value: str) -> str:
    keywords = funnels.normalize_keywords(value or "")
    if keywords:
        try:
            runtime_config.validate("FUNNEL_KEYWORDS", keywords)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return keywords


def _clean_media(value: Optional[str]) -> str:
    try:
        return funnels.normalize_media(value or "")
    except ValueError as exc:
        raise HTTPException(400, f"Instagram postlari: {exc}") from None


async def _check_slug(db, slug: str, exclude: Optional[uuid.UUID] = None) -> None:
    q = select(Funnel.id).where(Funnel.slug == slug)
    if exclude is not None:
        q = q.where(Funnel.id != exclude)
    if (await db.execute(q)).first():
        raise HTTPException(400, f"«{slug}» manzili band — boshqasini tanlang")


async def _check_collisions(db, row: Funnel) -> None:
    candidate = FunnelView.of(row)
    others = [FunnelView.of(r) for r in await _all_rows(db) if r.id != row.id]
    hit = funnels.keyword_collision(candidate, others)
    if hit:
        keyword, other = hit
        raise HTTPException(400, f"«{keyword}» kalit so'zi «{other.name}» voronkasida ham bor "
                                 "(bir xil postlar uchun). Boshqa so'z tanlang, post "
                                 "filtrini o'zgartiring yoki u voronkani arxivlang.")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/funnels", response_model=list[FunnelOut], dependencies=staff)
async def list_funnels(db: DB):
    return await _outputs(db, await _all_rows(db))


@router.post("/funnels", response_model=FunnelOut, status_code=201, dependencies=admin)
async def create_funnel(payload: FunnelIn, db: DB):
    source = await _row(db, payload.copy_from_id) if payload.copy_from_id else None
    slug = payload.slug or await funnels.unique_slug(db, funnels.slugify(payload.name))
    await _check_slug(db, slug)
    texts = _merge_texts(source.texts if source else {}, payload.texts)
    row = Funnel(name=payload.name.strip(), slug=slug, is_active=payload.is_active,
                 is_default=False, keywords=_clean_keywords(payload.keywords),
                 ig_media_ids=_clean_media(payload.ig_media_ids), texts=texts,
                 sort_order=await funnels.next_sort_order(db))
    db.add(row)
    await db.flush()
    await _check_collisions(db, row)
    if source is not None:
        await _copy_content(db, source.id, row.id)
    await db.commit()
    funnels.invalidate()
    return (await _outputs(db, [row]))[0]


async def _copy_content(db, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
    """Sales messages (with images) and the PDF of another funnel."""
    messages = (await db.execute(
        select(FunnelMessage.sort_order, FunnelMessage.text, FunnelMessage.delay_minutes,
               FunnelMessage.is_active, FunnelMessage.image, FunnelMessage.image_content_type)
        .where(FunnelMessage.funnel_id == source_id))).all()
    for m in messages:
        db.add(FunnelMessage(funnel_id=target_id, sort_order=m.sort_order, text=m.text,
                             delay_minutes=m.delay_minutes, is_active=m.is_active,
                             image=m.image, image_content_type=m.image_content_type))
    pdf = (await db.execute(
        select(FunnelFile.filename, FunnelFile.content_type, FunnelFile.size_bytes,
               FunnelFile.data, FunnelFile.sha256, FunnelFile.tg_file_id)
        .where(FunnelFile.funnel_id == source_id, FunnelFile.key == LEAD_MAGNET_KEY))).first()
    if pdf is not None:
        # Same bot: the Telegram file_id is reusable, no second upload needed
        db.add(FunnelFile(funnel_id=target_id, key=LEAD_MAGNET_KEY, filename=pdf.filename,
                          content_type=pdf.content_type, size_bytes=pdf.size_bytes,
                          data=pdf.data, sha256=pdf.sha256, tg_file_id=pdf.tg_file_id))


@router.patch("/funnels/{funnel_id}", response_model=FunnelOut, dependencies=admin)
async def update_funnel(funnel_id: uuid.UUID, payload: FunnelPatch, db: DB):
    row = await _row(db, funnel_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_active") is False and row.is_default:
        raise HTTPException(400, "Asosiy voronkani o'chirib bo'lmaydi")
    renamed = data.get("name") is not None and data["name"].strip() != row.name
    if data.get("name") is not None:
        row.name = data["name"].strip()
    if data.get("slug") is not None and data["slug"] != row.slug:
        await _check_slug(db, data["slug"], exclude=row.id)
        row.slug = data["slug"]
    if data.get("keywords") is not None:
        row.keywords = _clean_keywords(data["keywords"])
    if "ig_media_ids" in data:
        row.ig_media_ids = _clean_media(data["ig_media_ids"])
    if data.get("is_active") is not None:
        row.is_active = data["is_active"]
    if data.get("texts") is not None:
        row.texts = _merge_texts(row.texts, data["texts"])
    await db.flush()
    await _check_collisions(db, row)
    if renamed:
        # The Sheet's "Voronka" column shows the name: re-sync those rows (their
        # updated_at is kept — a rename is not a change of the person's data)
        await db.execute(update(FunnelEntry).where(FunnelEntry.funnel_id == row.id)
                         .values(sheet_dirty=True, updated_at=FunnelEntry.updated_at)
                         .execution_options(synchronize_session=False))
    await db.commit()
    funnels.invalidate()
    return (await _outputs(db, [row]))[0]


@router.delete("/funnels/{funnel_id}", status_code=204, dependencies=admin)
async def delete_funnel(funnel_id: uuid.UUID, db: DB):
    row = await _row(db, funnel_id)
    if row.is_default:
        raise HTTPException(400, "Asosiy voronkani o'chirib bo'lmaydi")
    if await _has_entries(db, row.id):
        raise HTTPException(409, _HAS_ENTRIES)
    # Explicit: SQLite (tests) does not enforce ON DELETE CASCADE
    await db.execute(delete(FunnelMessage).where(FunnelMessage.funnel_id == row.id))
    await db.execute(delete(FunnelFile).where(FunnelFile.funnel_id == row.id))
    await db.delete(row)
    try:
        await db.commit()
    except IntegrityError:
        # Someone entered the funnel between the check and the delete (FK restrict)
        await db.rollback()
        raise HTTPException(409, _HAS_ENTRIES) from None
    funnels.invalidate()
    return Response(status_code=204)


_HAS_ENTRIES = ("Voronkada mijozlar bor — o'chirib bo'lmaydi. Uni arxivlang (nofaol qiling): "
                "ma'lumotlar saqlanadi.")


async def _has_entries(db, funnel_id: uuid.UUID) -> bool:
    return (await db.execute(
        select(FunnelEntry.id).where(FunnelEntry.funnel_id == funnel_id).limit(1))).first() \
        is not None


@router.post("/funnels/reorder", response_model=list[FunnelOut], dependencies=admin)
async def reorder_funnels(payload: ReorderIn, db: DB):
    rows = {r.id: r for r in await _all_rows(db)}
    for index, funnel_id in enumerate(payload.ids):
        if funnel_id in rows:
            rows[funnel_id].sort_order = index
    await db.commit()
    funnels.invalidate()
    return await _outputs(db, await _all_rows(db))
