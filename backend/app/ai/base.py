"""AI provayder abstraksiyasi — Claude va Gemini shu interfeysni bajaradi."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AIProvider(ABC):
    """Almashtiriladigan AI provayder.

    `system` — barqaror (persona + bilim) tizim ko'rsatmasi. Provayder buni
    imkon qadar keshlaydi (Claude prompt caching), shuning uchun uni HAR
    javobda o'zgartirmang.
    `messages` — [{"role": "user"|"assistant", "content": str}, ...] suhbat.
    """

    @abstractmethod
    async def generate(
        self, system: str, messages: list[dict], output_model: type[T]
    ) -> T:
        ...
