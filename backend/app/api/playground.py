"""Playground: talk to the agent with the current knowledge base (nothing sent/stored)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import require_admin
from app.processing.pipeline import _agent
from app.schemas.api import PlaygroundIn

router = APIRouter(prefix="/playground", tags=["Playground"],
                   dependencies=[Depends(require_admin)])


@router.post("")
async def playground(payload: PlaygroundIn):
    turns = [m.model_dump() for m in payload.messages]
    if turns[-1]["role"] != "user":
        raise HTTPException(400, "Oxirgi xabar mijozniki bo'lishi kerak")
    try:
        out = await _agent.handle(
            turns[-1]["content"], is_comment=payload.is_comment,
            history=turns[:-1], channel=payload.channel, username="sinov",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"AI javob bermadi: {exc}") from None
    return out
