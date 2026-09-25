"""Mock (soxta) AI provayder — API kalitsiz to'liq oqimni sinash uchun.

`.env` da AI_PROVIDER=mock qo'yilsa ishlatiladi. Tashqi API chaqirmaydi —
mijoz xabaridan oddiy evristika bilan real modelga o'xshash AgentOutput
qaytaradi. Jonli ishlatishда AI_PROVIDER=claude yoki gemini qo'yiladi.
"""
from __future__ import annotations

import re

from app.ai.base import AIProvider, T
from app.models_ai import AgentOutput, LeadInfo

_PRICE = ("qancha", "narx", "turadi", "narxi", "pochom", "цена", "нарх", "нарҳ")
_BUY = ("yozilaman", "yozil", "kerak", "suhbat", "boraman", "хочу", "керак", "запис")
_PRODUCTS = ("tayyorlov", "1-sinf", "2-sinf", "3-sinf", "4-sinf", "5-sinf")


def _guess_product(low: str) -> str | None:
    for p in _PRODUCTS:
        if p in low:
            return p.title()
    return None


class MockProvider(AIProvider):
    async def generate(
        self, system: str, messages: list[dict], output_model: type[T]
    ) -> T:
        text = messages[-1]["content"] if messages else ""
        low = text.lower()

        language = "uz-Cyrl" if re.search(r"[а-яёўқғҳ]", low) else "uz-Latn"
        phone = re.search(r"\+?998\d{9}|\b\d{9}\b", text.replace(" ", ""))
        contact = phone.group(0) if phone else None
        price = any(w in low for w in _PRICE)
        buying = any(w in low for w in _BUY)
        hot = bool(contact) or buying
        score = 90 if contact else (70 if buying else 55 if price else 30)

        reply = "Assalomu alaykum! 💛 Qiziqishingiz uchun rahmat. "
        if price or buying:
            reply += ("Maktabimizga tanishuv suhbatiga yozib qo'yaman — ismingiz va telefon "
                      "raqamingizni qoldiring, administratorimiz bog'lanadi 👌")
        else:
            reply += "Savolingiz bo'lsa, bemalol yozing, yordam beraman 🙌"

        result = AgentOutput(
            reply=reply,
            language=language,
            intent="buying_intent" if buying else ("price_question" if price else "greeting"),
            stage="closing" if (price or buying) else "discovery",
            lead_score=score,
            is_hot_lead=hot,
            move_to_dm=price or buying,
            escalate_to_human=False,
            lead=LeadInfo(
                contact=contact,
                course_interest=_guess_product(low),
                summary=f"[MOCK javob] Mijoz yozdi: {text[:120]}",
            ),
        )
        return result  # type: ignore[return-value]
