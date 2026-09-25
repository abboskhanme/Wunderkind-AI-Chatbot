"""Application settings.

Two kinds of values live on the same `settings` object:
  * infrastructure (DATABASE_URL, SECRET_KEY, ...) — `.env` only;
  * runtime agent settings (AI keys, tokens, knowledge base, ...) — editable in
    the admin panel. `app.runtime_config` overlays DB values on top of the
    `.env` baseline and mutates this object in place, so every module that reads
    `settings.X` at call time picks up changes without a restart.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Infrastructure (.env only) ---------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://wk:wk@localhost:5432/wk_agent"
    REDIS_URL: str = ""
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_MINUTES: int = 60 * 12
    # Public HTTPS origin, e.g. https://agent.wunderkind.uz (webhooks + OAuth)
    PUBLIC_URL: str = ""
    CORS_ORIGINS: str = ""
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""
    LOG_LEVEL: str = "INFO"

    # --- AI ------------------------------------------------------------------
    AI_PROVIDER: str = "gemini"  # gemini | claude | mock
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-5"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"
    # Thinking also consumes max_tokens — keep >= 2048 or replies get cut.
    AI_MAX_TOKENS: int = 2048
    AI_EFFORT: str = "low"

    # --- Knowledge base (panel "Bilim bazasi") -----------------------------
    KB_COMPANY: str = ""
    KB_COURSES: str = ""
    KB_SCHEDULE: str = ""
    KB_PROMO: str = ""
    KB_FAQ: str = ""
    KB_RULES: str = ""
    KNOWLEDGE_DIR: str = "data/knowledge"

    # --- Instagram (Instagram API with Instagram Login) --------------------
    IG_AI_ENABLED: bool = True
    IG_API_BASE: str = "https://graph.instagram.com"
    IG_VERIFY_TOKEN: str = ""
    IG_APP_ID: str = ""
    IG_APP_SECRET: str = ""
    IG_ACCESS_TOKEN: str = ""
    IG_TOKEN_ISSUED_AT: str = ""
    IG_USER_ID: str = ""
    IG_ACCOUNT_ID: str = ""
    IG_USERNAME: str = ""
    GRAPH_API_VERSION: str = "v23.0"

    # --- Telegram sales bot (answers private chats / Business connection) --
    TG_SALES_BOT_TOKEN: str = ""
    TG_SALES_ENABLED: bool = True
    TG_WEBHOOK_SECRET: str = ""
    TG_API_BASE: str = "https://api.telegram.org"
    TG_MENU_GREETING: str = ""
    # Long polling when PUBLIC_URL is empty (local dev without a public URL)
    TG_POLLING: bool = True

    # --- Telegram notifications (staff alerts) -----------------------------
    # Empty token -> the sales bot token is used for alerts.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    DAILY_REPORT_TIME: str = "20:00"

    # --- Sales behaviour ---------------------------------------------------
    FOLLOWUP_ENABLED: bool = True
    FOLLOWUP_AFTER_HOURS: int = 3
    BOT_PAUSE_HOURS: int = 12
    CMT_LIMIT_PER_POST: int = 30
    CMT_LIMIT_TOTAL: int = 100
    DEDUP_TTL: int = 86400

    # --- General -------------------------------------------------------------
    COMPANY_NAME: str = "Wunderkind"
    TIMEZONE: str = "Asia/Tashkent"

    # --- Lead-magnet funnel (SPEC §10; panel page "Voronka") ------------------
    FUNNEL_ENABLED: bool = True
    FUNNEL_KEYWORDS: str = "wunderkind, вундеркинд"
    FUNNEL_IG_REQUIRE_FOLLOW: bool = True
    FUNNEL_IG_FOLLOW_FAIL_OPEN: bool = True
    FUNNEL_IG_COMMENT_REPLY: str = (
        # "|" separates variants — one is picked at random (identical replies
        # to hundreds of comments look like spam to Instagram)
        "Shaxsiydan javob berdik 📩 | Shaxsiydan javob berdik ✅ | "
        "Shaxsiydan javob berdik 😊 | Shaxsiydan javob berdik 🌟"
    )
    FUNNEL_IG_DM_WELCOME: str = (
        "Assalomu alaykum! 😊 Farzandingiz tarbiyasiga e'tiboringiz uchun rahmat!\n\n"
        "«Lider farzand tarbiyalash uchun 8 ta maslahat» qo'llanmasini Sizga bepul "
        "sovg'a qilamiz 🎁\n\n"
        "Buning uchun sahifamizga obuna bo'ling, so'ng pastdagi «✅ Obuna bo'ldim» "
        "tugmasini bosing (yoki «tayyor» deb yozing)."
    )
    FUNNEL_IG_NOT_FOLLOWING: str = (
        "Hozircha obunangizni ko'rmayapmiz 🙈\n\n"
        "Iltimos, sahifamizga obuna bo'ling va «✅ Obuna bo'ldim» tugmasini qayta bosing "
        "(yoki «tayyor» deb yozing)."
    )
    FUNNEL_IG_LINK_MESSAGE: str = (
        "Obunangiz uchun rahmat! 🤗\n\n"
        "Qo'llanmani Telegram botimiz orqali yuboramiz: pastdagi tugmani bosing va "
        "botda «Start»ni bosing 👇"
    )
    FUNNEL_TG_CHANNEL: str = ""
    FUNNEL_TG_REQUIRE_CHANNEL: bool = True
    FUNNEL_TG_DISCUSSION_CHAT_ID: str = ""
    FUNNEL_TG_COMMENT_REPLY: str = (
        "Rahmat! 🎁 Qo'llanmani olish uchun pastdagi tugmani bosing va botda «Start»ni "
        "bosing 👇"
    )
    FUNNEL_BOT_START_FUNNEL: bool = True
    FUNNEL_BOT_WELCOME: str = (
        "Assalomu alaykum, xush kelibsiz! 😊\n\n"
        "«Lider farzand tarbiyalash uchun 8 ta maslahat» qo'llanmasini hozir yuboramiz. "
        "Faqat 3 ta qisqa savolga javob bering 👇"
    )
    FUNNEL_ASK_NAME: str = (
        "1/3. Ism-familiyangizni yozing, iltimos ✍️\n(masalan: Aliyeva Malika)"
    )
    FUNNEL_ASK_PHONE: str = (
        "2/3. Telefon raqamingizni yuboring 📱\n\n"
        "Pastdagi «📱 Raqamni yuborish» tugmasini bosing yoki raqamni yozing "
        "(masalan: +998 90 123 45 67)."
    )
    FUNNEL_ASK_GRADE: str = (
        "3/3. Farzandingiz nechanchi sinfda o'qiydi? 🎒\nPastdagi tugmalardan birini tanlang."
    )
    FUNNEL_GRADES: str = "Bog'cha,0,1,2,3,4,5,6,7,8,9,10,11"
    FUNNEL_PDF_CAPTION: str = (
        "🎁 Mana, Sizning qo'llanmangiz: «Lider farzand tarbiyalash uchun 8 ta maslahat»!\n\n"
        "Farzandingiz bilan birga o'qib, bugunoq bitta maslahatni amalda sinab ko'ring 💛\n\n"
        "Wunderkind maktabiga qabul davom etmoqda. Farzandingiz uchun bepul tanishuv "
        "suhbatiga yozilish uchun pastdagi tugmani bosing 👇"
    )
    FUNNEL_BOOK_BUTTON: str = "📝 Suhbatga ro'yxatdan o'tish"
    FUNNEL_WORK_DAYS: str = "1-6"
    FUNNEL_DAY_START: str = "09:00"
    FUNNEL_DAY_END: str = "16:00"
    FUNNEL_SLOT_MINUTES: int = 30
    FUNNEL_SLOT_CAPACITY: int = 1
    FUNNEL_BOOK_DAYS_AHEAD: int = 7
    FUNNEL_HOLIDAYS: str = ""
    FUNNEL_STAFF_NAME: str = ""
    FUNNEL_STAFF_PHONE: str = ""
    FUNNEL_ADDRESS: str = ""
    FUNNEL_LOCATION_LAT: str = ""
    FUNNEL_LOCATION_LON: str = ""
    # Lines whose placeholders are all empty are dropped (e.g. no address yet)
    FUNNEL_CONFIRM_TEXT: str = (
        "✅ {name}, Siz tanishuv suhbatiga muvaffaqiyatli yozildingiz!\n\n"
        "📅 Sana: {date} ({weekday})\n"
        "🕐 Vaqt: {time}\n"
        "👤 Mas'ul xodim: {staff_name}\n"
        "📞 Telefon: {staff_phone}\n"
        "📍 Manzil: {address}\n\n"
        "Suhbat kuni ertalab Sizga eslatma yuboramiz. Kutib qolamiz! 🤗"
    )
    FUNNEL_REMINDER_TIME: str = "07:00"
    FUNNEL_REMINDER_TEXT: str = (
        "🔔 Assalomu alaykum, {name}!\n\n"
        "Eslatib o'tamiz: bugun soat {time} da Wunderkind maktabida tanishuv suhbatingiz bor.\n\n"
        "📍 Manzil: {address}\n"
        "👤 Mas'ul xodim: {staff_name}\n"
        "📞 Telefon: {staff_phone}\n\n"
        "Kela olmasangiz, iltimos, vaqtni o'zgartiring yoki bekor qiling. Kutib qolamiz! 😊"
    )

    # --- Google Sheets (funnel entries until the CRM exists) ---------------
    GSHEET_SERVICE_ACCOUNT_JSON: str = ""
    GSHEET_SPREADSHEET_ID: str = ""
    GSHEET_WORKSHEET: str = "Leadlar"

    # Kept for ported code that still references the old name.
    @property
    def AGENT_PUBLIC_URL(self) -> str:  # noqa: N802
        return self.PUBLIC_URL

    @property
    def tg_webhook_secret(self) -> str:
        """Configured secret, or one derived from SECRET_KEY — never empty, so
        the Telegram webhook is never open to forged updates."""
        if self.TG_WEBHOOK_SECRET:
            return self.TG_WEBHOOK_SECRET
        import hashlib
        import hmac

        return hmac.new(self.SECRET_KEY.encode(), b"tg-webhook", hashlib.sha256).hexdigest()[:48]

    @property
    def alert_bot_token(self) -> str:
        return self.TELEGRAM_BOT_TOKEN or self.TG_SALES_BOT_TOKEN


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
