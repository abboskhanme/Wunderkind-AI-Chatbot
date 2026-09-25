"""Catalog of settings editable from the admin panel — the single source of
truth for which keys exist, how they are shown and whether they are secret.

Infrastructure values (DATABASE_URL, SECRET_KEY, PUBLIC_URL, ...) are deliberately
absent: they stay in `.env` so the panel can never lock itself out.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingItem:
    key: str
    label: str
    group: str
    secret: bool = False
    type: str = "text"  # text | number | select | textarea
    options: tuple[str, ...] = ()
    placeholder: str = ""
    help: str = ""
    # Filled automatically (e.g. by the Instagram "Ulash" flow) — not shown.
    hidden: bool = False


GROUPS: dict[str, str] = {
    "ai": "Sun'iy intellekt (AI)",
    "knowledge": "Bilim bazasi",
    "instagram": "Instagram",
    "telegram": "Telegram",
    "sales": "Sotuv sozlamalari",
    "general": "Umumiy",
    # Shown on the "Voronka" page, not in Sozlamalar (SPEC §10.3)
    "funnel": "Lead-magnet voronkasi",
    "gsheet": "Google Sheets",
}

YES_NO = ("ha", "yo'q")

CATALOG: tuple[SettingItem, ...] = (
    # --- AI -----------------------------------------------------------------
    SettingItem("AI_PROVIDER", "AI provayder", "ai", type="select",
                options=("gemini", "claude"),
                help="Asosiy provayder — Gemini. Claude — zaxira (kaliti bo'lsa)."),
    SettingItem("GEMINI_API_KEY", "Gemini API kaliti", "ai", secret=True,
                help="aistudio.google.com → Get API key."),
    SettingItem("GEMINI_MODEL", "Gemini modeli", "ai", placeholder="gemini-3.6-flash",
                help="Sifatliroq: gemini-3.1-pro-preview. Arzonroq: gemini-3.5-flash-lite."),
    SettingItem("ANTHROPIC_API_KEY", "Anthropic (Claude) API kaliti", "ai", secret=True,
                help="console.anthropic.com → API Keys."),
    SettingItem("CLAUDE_MODEL", "Claude modeli", "ai", placeholder="claude-sonnet-5",
                help="Sifatliroq: claude-opus-5-5. Arzonroq: claude-haiku-4-5."),
    SettingItem("AI_MAX_TOKENS", "Javob limiti (token)", "ai", type="number",
                placeholder="2048",
                help="2048 dan pastga tushirmang — fikrlash ham shu limitdan yeydi."),
    SettingItem("AI_EFFORT", "Fikrlash darajasi", "ai", type="select",
                options=("low", "medium", "high"),
                help="«low» — tez va arzon, chat uchun yetarli."),

    # --- Knowledge base -------------------------------------------------------
    SettingItem(
        "KB_COMPANY", "O'quv markazi haqida", "knowledge", type="textarea",
        placeholder=(
            "Wunderkind — bolalar va kattalar uchun o'quv markazi. 2015-yildan beri.\n"
            "Filiallar: Chilonzor (Bunyodkor 12), Yunusobod (...).\n"
            "Ish vaqti: Du–Sha 9:00–20:00.\nTelefon: +998 ...\nTelegram: @..."
        ),
        help="Kimsiz, filiallar va manzillar (mo'ljal bilan), ish vaqti, aloqa, afzalliklaringiz.",
    ),
    SettingItem(
        "KB_COURSES", "Kurslar va narxlar", "knowledge", type="textarea",
        placeholder=(
            "- Ingliz tili (7–12 yosh): haftada 3 dars × 90 daqiqa, oyiga 450 000 so'm\n"
            "- IELTS (16+): ... \n- Matematika (Prezident maktabiga tayyorlov): ..."
        ),
        help="Har bir kurs: nomi, yosh/daraja, dars soni va davomiyligi, oylik narx, "
             "natija (nima o'rganadi). Agent faqat shu narxlarni aytadi.",
    ),
    SettingItem(
        "KB_SCHEDULE", "Guruhlar, jadval va sinov darsi", "knowledge", type="textarea",
        placeholder=(
            "Sinov darsi: BEPUL, 60 daqiqa, oldindan yozilish kerak.\n"
            "Daraja testi: bepul, 30 daqiqa.\n"
            "Guruhlar: ertalab 9:00, tushdan keyin 14:00, 16:00, kechqurun 18:30.\n"
            "Guruhda 8–12 o'quvchi."
        ),
        help="Sinov darsi/daraja testi qanday o'tadi, guruh vaqtlari, guruh hajmi, "
             "yangi guruhlar qachon ochiladi.",
    ),
    SettingItem(
        "KB_PROMO", "Aksiyalar va chegirmalar", "knowledge", type="textarea",
        placeholder="- Aka-uka/opa-singil uchun 10% chegirma\n- 3 oyga oldindan to'lovda 1 hafta bepul",
        help="Faqat HAQIQIY amaldagi aksiyalar. Bo'lmasa bo'sh qoldiring — agent o'ylab topmaydi.",
    ),
    SettingItem(
        "KB_FAQ", "Ko'p so'raladigan savollar", "knowledge", type="textarea",
        placeholder=(
            "S: O'qituvchilar kimlar?\nJ: CELTA/IELTS 8+ sertifikatli ustozlar.\n\n"
            "S: Sertifikat beriladimi?\nJ: Ha, har bir daraja yakunida."
        ),
        help="«S:» savol, «J:» javob. Qancha ko'p bo'lsa, agent shuncha kam operatorga o'tkazadi.",
    ),
    SettingItem(
        "KB_RULES", "Muloqot qoidalari (ixtiyoriy)", "knowledge", type="textarea",
        placeholder="- Ota-onaga «Siz» deb murojaat qil.\n- Chegirma haqida o'zingdan va'da berma.",
        help="Agent uslubi va nima deyish MUMKIN EMASligi.",
    ),

    # --- Instagram ------------------------------------------------------------
    SettingItem("IG_AI_ENABLED", "Instagramda AI javob", "instagram", type="select",
                options=YES_NO,
                help="«yo'q» — xabarlar faqat Suhbatlar bo'limiga tushadi, AI javob bermaydi."),
    SettingItem("IG_APP_ID", "Instagram App ID", "instagram",
                help="Meta App → Instagram → API setup with Instagram login. Meta'da "
                     "OAuth redirect URI sifatida {PUBLIC_URL}/connect/callback ni qo'shing."),
    SettingItem("IG_APP_SECRET", "Instagram App Secret", "instagram", secret=True,
                help="Webhook imzosini tekshirishda ham ishlatiladi."),
    SettingItem("IG_VERIFY_TOKEN", "Webhook verify token", "instagram", secret=True,
                help="O'zingiz o'ylab topasiz va Meta webhook sozlamasiga aynan shuni kiritasiz."),
    SettingItem("IG_ACCESS_TOKEN", "Access token", "instagram", secret=True, hidden=True),
    SettingItem("IG_USER_ID", "Instagram User ID", "instagram", hidden=True),
    SettingItem("IG_ACCOUNT_ID", "Instagram Account ID", "instagram", hidden=True),
    SettingItem("IG_USERNAME", "Instagram username", "instagram", hidden=True),
    SettingItem("IG_TOKEN_ISSUED_AT", "Token olingan sana", "instagram", hidden=True),
    SettingItem("GRAPH_API_VERSION", "Graph API versiyasi", "instagram", hidden=True),

    # --- Telegram -------------------------------------------------------------
    SettingItem(
        "TG_SALES_BOT_TOKEN", "AI bot tokeni", "telegram", secret=True,
        help="@BotFather'dan olingan token. Mijozlar shu botga yozadi. Telegram Premium "
             "bo'lsa: Sozlamalar → Telegram Business → Chatbotlar orqali ulab, shaxsiy "
             "chatlaringizga ham javob berdirish mumkin.",
    ),
    SettingItem("TG_SALES_ENABLED", "Telegramda AI javob", "telegram", type="select",
                options=YES_NO),
    SettingItem("TG_WEBHOOK_SECRET", "Webhook maxfiy kaliti (ixtiyoriy)", "telegram",
                secret=True,
                help="Bo'sh qoldirsangiz tizim o'zi xavfsiz kalit yaratadi. O'zingiz "
                     "bersangiz: 16+ belgi, faqat A-Z, a-z, 0-9, _ va -."),
    SettingItem("TELEGRAM_BOT_TOKEN", "Bildirishnoma boti tokeni (ixtiyoriy)", "telegram",
                secret=True,
                help="Bo'sh bo'lsa bildirishnomalar AI bot orqali yuboriladi."),
    SettingItem("TELEGRAM_CHAT_ID", "Bildirishnoma oluvchilar (chat ID)", "telegram",
                placeholder="123456789, -1001234567890",
                help="Vergul bilan. Chat ID'ni bilish uchun botga /id yozing (guruhda ham "
                     "ishlaydi — avval botni guruhga qo'shing)."),
    SettingItem("DAILY_REPORT_TIME", "Kunlik hisobot vaqti", "telegram", placeholder="20:00"),
    SettingItem("TG_MENU_GREETING", "Menyu salomlashuvi", "telegram", type="textarea",
                hidden=True),

    # --- Sales behaviour ------------------------------------------------------
    SettingItem("FOLLOWUP_ENABLED", "Javobsiz mijozga eslatma", "sales", type="select",
                options=YES_NO,
                help="Mijoz javob bermay qolsa, AI bir marta muloyim eslatma yozadi "
                     "(Instagramda faqat 24 soat ichida)."),
    SettingItem("FOLLOWUP_AFTER_HOURS", "Eslatma necha soatdan keyin", "sales",
                type="number", placeholder="3"),
    SettingItem("BOT_PAUSE_HOURS", "Operator yozgach AI pauzasi (soat)", "sales",
                type="number", placeholder="12",
                help="Operator o'zi javob yozsa, AI o'sha suhbatda shuncha soat jim turadi."),
    SettingItem("CMT_LIMIT_PER_POST", "Izoh javobi chegarasi (1 post, 10 daqiqa)", "sales",
                type="number", placeholder="30",
                help="Spam/halqadan himoya. Oshgan izohlar navbatga qo'yiladi, tashlanmaydi."),
    SettingItem("CMT_LIMIT_TOTAL", "Izoh javobi chegarasi (jami, 10 daqiqa)", "sales",
                type="number", placeholder="100"),

    # --- General --------------------------------------------------------------
    SettingItem("COMPANY_NAME", "O'quv markazi nomi", "general", placeholder="Wunderkind"),
    SettingItem("TIMEZONE", "Vaqt mintaqasi", "general", placeholder="Asia/Tashkent"),

    # --- Lead-magnet funnel (SPEC §10) ------------------------------------------
    SettingItem("FUNNEL_ENABLED", "Voronka yoqilgan", "funnel", type="select",
                options=YES_NO,
                help="«yo'q» — yangi izoh/start qabul qilinmaydi va sotuv xabarlari to'xtaydi. "
                     "Boshlangan ro'yxatdan o'tish, suhbatga yozilish va eslatmalar ishlayveradi."),
    SettingItem("FUNNEL_KEYWORDS", "Kalit so'zlar", "funnel",
                placeholder="wunderkind, вундеркинд",
                help="Vergul bilan. Katta-kichik harf, lotin/kirill farqi hisobga olinmaydi."),
    SettingItem("FUNNEL_IG_REQUIRE_FOLLOW", "Instagram: obunani tekshirish", "funnel",
                type="select", options=YES_NO,
                help="«ha» — havola faqat sahifaga obuna bo'lganlarga yuboriladi."),
    SettingItem("FUNNEL_IG_FOLLOW_FAIL_OPEN", "Instagram: tekshirib bo'lmasa ham havola", "funnel",
                type="select", options=YES_NO,
                help="Instagram obunani tekshirishga ruxsat bermasa — baribir havola yuborilsin "
                     "(mijoz yo'qolmasin)."),
    SettingItem("FUNNEL_IG_COMMENT_REPLY", "Instagram: izohga ochiq javob", "funnel",
                type="textarea",
                help="Variantlarni «|» bilan ajrating — har izohga tasodifiy biri yoziladi "
                     "(bir xil javob spam bo'lib ko'rinmasin). Bo'sh bo'lsa ochiq javob "
                     "yozilmaydi (faqat Direct)."),
    SettingItem("FUNNEL_IG_DM_WELCOME", "Instagram: Direct'dagi birinchi xabar", "funnel",
                type="textarea",
                help="Ostida «✅ Obuna bo'ldim» tugmasi chiqadi. Tugma ishlamasa mijoz «tayyor» "
                     "deb yozadi — shuni matnda eslating. 1000 belgigacha."),
    SettingItem("FUNNEL_IG_NOT_FOLLOWING", "Instagram: hali obuna bo'lmagan", "funnel",
                type="textarea", help="1000 belgigacha."),
    SettingItem("FUNNEL_IG_LINK_MESSAGE", "Instagram: bot havolasi xabari", "funnel",
                type="textarea",
                help="Ostida Telegram botga havola tugmasi chiqadi. 640 belgigacha."),
    SettingItem("FUNNEL_TG_CHANNEL", "Telegram kanal", "funnel",
                placeholder="@wunderkind_kanal",
                help="@username yoki -100… ID. Bot kanalda administrator bo'lishi kerak."),
    SettingItem("FUNNEL_TG_REQUIRE_CHANNEL", "Telegram: kanalga obunani tekshirish", "funnel",
                type="select", options=YES_NO,
                help="Telegram'dan kelganlarga qo'llanma faqat kanalga obuna bo'lgach yuboriladi."),
    SettingItem("FUNNEL_TG_DISCUSSION_CHAT_ID", "Kanal muhokama guruhi ID", "funnel",
                placeholder="-1001234567890",
                help="Kanal postlari ostidagi izohlar shu guruhga tushadi. Bo'sh — istalgan guruh. "
                     "Botni guruhga administrator qiling; ID'ni bilish uchun guruhda /id yozing."),
    SettingItem("FUNNEL_TG_COMMENT_REPLY", "Telegram: izohga javob", "funnel",
                type="textarea", help="Izoh ostida botga havola tugmasi bilan chiqadi."),
    SettingItem("FUNNEL_BOT_START_FUNNEL", "Botga to'g'ridan-to'g'ri kirganlarga ham", "funnel",
                type="select", options=YES_NO,
                help="«ha» — botda oddiy /start bosganlar ham qo'llanma oladi."),
    SettingItem("FUNNEL_BOT_WELCOME", "Bot: salomlashuv", "funnel", type="textarea"),
    SettingItem("FUNNEL_ASK_NAME", "Bot: ism so'rash", "funnel", type="textarea"),
    SettingItem("FUNNEL_ASK_PHONE", "Bot: telefon so'rash", "funnel", type="textarea"),
    SettingItem("FUNNEL_ASK_GRADE", "Bot: sinf so'rash", "funnel", type="textarea"),
    SettingItem("FUNNEL_GRADES", "Sinf tugmalari", "funnel",
                placeholder="Bog'cha,0,1,2,3,4,5,6,7,8,9,10,11",
                help="Vergul bilan. Raqamlar «5-sinf» ko'rinishida chiqadi."),
    SettingItem("FUNNEL_PDF_CAPTION", "Qo'llanma (PDF) izohi", "funnel", type="textarea",
                help="1024 belgigacha. Ostida suhbatga yozilish tugmasi chiqadi."),
    SettingItem("FUNNEL_BOOK_BUTTON", "Suhbatga yozilish tugmasi", "funnel",
                placeholder="📝 Suhbatga ro'yxatdan o'tish"),
    SettingItem("FUNNEL_WORK_DAYS", "Suhbat kunlari", "funnel", placeholder="1-6",
                help="1 — dushanba … 7 — yakshanba. Masalan «1-6» yoki «1,2,3,5»."),
    SettingItem("FUNNEL_DAY_START", "Suhbatlar boshlanishi", "funnel", placeholder="09:00"),
    SettingItem("FUNNEL_DAY_END", "Suhbatlar tugashi", "funnel", placeholder="16:00",
                help="Oxirgi suhbat shu vaqtdan oldin boshlanadi (16:00 → oxirgisi 15:30)."),
    SettingItem("FUNNEL_SLOT_MINUTES", "Bitta suhbat (daqiqa)", "funnel", type="number",
                placeholder="30"),
    SettingItem("FUNNEL_SLOT_CAPACITY", "Bir vaqtga nechta oila", "funnel", type="number",
                placeholder="1"),
    SettingItem("FUNNEL_BOOK_DAYS_AHEAD", "Necha kun oldinga yozish mumkin", "funnel",
                type="number", placeholder="7"),
    SettingItem("FUNNEL_HOLIDAYS", "Dam olish kunlari", "funnel", type="textarea",
                placeholder="2026-10-01, 2026-12-08",
                help="YYYY-MM-DD, vergul yoki yangi qator bilan. Bu kunlarga yozilib bo'lmaydi."),
    SettingItem("FUNNEL_STAFF_NAME", "Mas'ul xodim ismi", "funnel",
                placeholder="Malika Karimova"),
    SettingItem("FUNNEL_STAFF_PHONE", "Mas'ul xodim telefoni", "funnel",
                placeholder="+998 90 123 45 67"),
    SettingItem("FUNNEL_ADDRESS", "Manzil", "funnel", type="textarea",
                placeholder="Toshkent, Chilonzor 7-mavze, 12-uy (mo'ljal: ... )"),
    SettingItem("FUNNEL_LOCATION_LAT", "Lokatsiya: kenglik", "funnel", placeholder="41.311081",
                help="Google Maps'da joyni bosing — birinchi son. Ikkalasi to'lsa lokatsiya "
                     "ham yuboriladi."),
    SettingItem("FUNNEL_LOCATION_LON", "Lokatsiya: uzunlik", "funnel", placeholder="69.240562",
                help="Ikkinchi son."),
    SettingItem("FUNNEL_CONFIRM_TEXT", "Suhbatga yozilganda tasdiq", "funnel", type="textarea",
                help="O'rinbosarlar: {name} {date} {weekday} {time} {staff_name} {staff_phone} "
                     "{address}. Qiymati bo'sh o'rinbosarli qator chiqmaydi."),
    SettingItem("FUNNEL_REMINDER_TIME", "Eslatma vaqti (suhbat kuni)", "funnel",
                placeholder="07:00"),
    SettingItem("FUNNEL_REMINDER_TEXT", "Eslatma matni", "funnel", type="textarea",
                help="O'rinbosarlar tasdiq matnidagi bilan bir xil."),

    # --- Google Sheets ------------------------------------------------------------
    SettingItem("GSHEET_SERVICE_ACCOUNT_JSON", "Service account JSON", "gsheet", secret=True,
                type="textarea",
                help="Google Cloud → Service accounts → Keys → JSON. Jadvalni shu JSON'dagi "
                     "client_email manziliga «Editor» qilib ulashing."),
    SettingItem("GSHEET_SPREADSHEET_ID", "Jadval ID yoki havolasi", "gsheet",
                placeholder="https://docs.google.com/spreadsheets/d/…",
                help="Jadval havolasini to'liq qo'yish ham mumkin."),
    SettingItem("GSHEET_WORKSHEET", "Varaq nomi", "gsheet", placeholder="Leadlar",
                help="Bo'lmasa o'zi yaratiladi."),
)

CATALOG_BY_KEY: dict[str, SettingItem] = {i.key: i for i in CATALOG}
ALLOWED_KEYS: frozenset[str] = frozenset(CATALOG_BY_KEY)
