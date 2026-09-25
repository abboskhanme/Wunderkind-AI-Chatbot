"""Agent I/O models.

  * AgentOutput — structured JSON the AI returns (same schema for Claude/Gemini)
  * LeadInfo    — lead facts inside AgentOutput
  * LeadPayload — lead update the pipeline writes to the database

No `minLength`/`ge`/`le` constraints in the output schema — Claude structured
outputs do not support them; ranges are clamped in Python instead.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LeadInfo(BaseModel):
    name: Optional[str] = Field(default=None, description="Mijoz (yoki ota-ona) ismi, aniqlansa")
    contact: Optional[str] = Field(
        default=None, description="Telefon raqami, mijoz bergan bo'lsa"
    )
    course_interest: Optional[str] = Field(
        default=None, description="Qiziqish (masalan: 1-sinfga qabul, tayyorlov sinfi, 5-sinf)"
    )
    student_age: Optional[str] = Field(
        default=None, description="Farzand yoshi yoki sinfi, aytilgan bo'lsa"
    )
    preferred_time: Optional[str] = Field(
        default=None, description="Qulay vaqt, aytilgan bo'lsa"
    )
    summary: Optional[str] = Field(
        default=None, description="Suhbat qisqacha xulosasi (o'zbekcha, 1-2 gap)"
    )


class AgentOutput(BaseModel):
    reply: str = Field(description="Mijozga yuboriladigan javob matni")
    language: str = Field(description="Mijoz tili/yozuvi: uz-Cyrl | uz-Latn | ru | en")
    intent: str = Field(
        description=(
            "Mijoz niyati: greeting | price_question | course_question | schedule_question | "
            "buying_intent | objection | complaint | spam | other"
        )
    )
    stage: str = Field(
        default="discovery",
        description=(
            "Sotuv bosqichi: greeting | discovery | offer | objection | closing | booked | support"
        ),
    )
    lead_score: int = Field(description="Lead qiymati 0..100 (100 = yozilishga tayyor)")
    is_hot_lead: bool = Field(
        description="Jiddiy xaridor belgilari bormi (raqam qoldirdi, maktabga suhbatga yozilmoqchi)"
    )
    move_to_dm: bool = Field(
        description="Ochiq izohdan shaxsiy xabarga o'tkazish kerakmi"
    )
    escalate_to_human: bool = Field(
        description="Operatorga o'tkazish kerakmi (javobni bilmasa, shikoyat, operator so'radi)"
    )
    lead: LeadInfo = Field(default_factory=LeadInfo)

    def clamp(self) -> "AgentOutput":
        self.lead_score = max(0, min(100, self.lead_score))
        return self


class LeadPayload(BaseModel):
    channel: str = "instagram"
    source: str = "instagram"
    user_id: Optional[str] = None
    username: Optional[str] = None
    media_id: Optional[str] = None
    comment_id: Optional[str] = None

    name: Optional[str] = None
    contact: Optional[str] = None
    course_interest: Optional[str] = None
    student_age: Optional[str] = None
    preferred_time: Optional[str] = None
    language: Optional[str] = None
    intent: Optional[str] = None
    stage: Optional[str] = None
    lead_score: int = 0
    summary: Optional[str] = None
    extra: dict = Field(default_factory=dict)
