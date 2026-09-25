"""Fill the knowledge base and Telegram bot menu with SAMPLE data for testing.

Goes through the admin API, so the running backend reloads settings and the bot
menu immediately. Idempotent and non-destructive: a setting that already has a
value and a menu command that already exists are left untouched.

    python backend/scripts/seed_demo.py            # reads ADMIN_* from ./.env
    API=http://localhost:8080/api python backend/scripts/seed_demo.py

Everything here is fictional — replace it with real data before going live.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("API", "http://localhost:8080/api").rstrip("/")

KNOWLEDGE: dict[str, str] = {
    "COMPANY_NAME": "Wunderkind",
    "KB_COMPANY": """\
Wunderkind — bolalar va o'smirlar uchun o'quv markazi. 2016-yildan beri faoliyat yuritadi, 1 500+ bitiruvchi.
Filiallar:
- Chilonzor: Bunyodkor shoh ko'chasi 12 (mo'ljal: «Chilonzor» metro bekati, Korzinka yonida)
- Yunusobod: Amir Temur ko'chasi 108, 4-kvartal (mo'ljal: «Minor» metro, Mega Planet ro'parasida)
Ish vaqti: Dushanba–Shanba 9:00–20:00, Yakshanba dam olish kuni.
Telefon: +998 71 200 00 00
Telegram: @wunderkind_admin
Afzalliklar: kichik guruhlar (8–12 o'quvchi), har oy ota-onaga natija hisoboti, bepul sinov darsi, zamonaviy jihozlangan xonalar.""",
    "KB_COURSES": """\
- Ingliz tili — Kids (6–9 yosh): haftada 3 dars × 60 daqiqa, oyiga 450 000 so'm. O'yin orqali so'z boyligi, talaffuz va birinchi gaplar.
- Ingliz tili — Juniors (10–14 yosh): haftada 3 dars × 90 daqiqa, oyiga 550 000 so'm. Beginner'dan Intermediate'gacha, har daraja 4 oy.
- IELTS (15+ yosh, Intermediate darajadan): haftada 3 dars × 120 daqiqa, oyiga 800 000 so'm. Kurs 4 oy, har oy mock imtihon.
- Matematika — Prezident va ixtisoslashgan maktablarga tayyorlov (4–7-sinf): haftada 3 dars × 90 daqiqa, oyiga 500 000 so'm.
- Mental arifmetika (5–10 yosh): haftada 2 dars × 60 daqiqa, oyiga 400 000 so'm. Abakus bilan tez hisoblash, diqqat va xotira.
- Robototexnika (8–14 yosh): haftada 2 dars × 90 daqiqa, oyiga 600 000 so'm. LEGO Spike va Arduino, konstruktorlar markazda beriladi.
- Rus tili (7–14 yosh): haftada 2 dars × 60 daqiqa, oyiga 400 000 so'm.
To'lov: oyning boshida, naqd, karta (Uzcard/Humo), Click yoki Payme orqali. Darslik narxga kiritilgan.""",
    "KB_SCHEDULE": """\
Sinov darsi: BEPUL, 60 daqiqa, oldindan yozilish kerak (ism va telefon raqami). Ota-ona dars oxirida ustoz bilan gaplashadi.
Daraja testi (ingliz tili, IELTS): bepul, 30 daqiqa, sinov darsi bilan bir kunda o'tkazish mumkin.
Guruh vaqtlari:
- Ertalabki: 9:00 va 10:30 (maktabga ikkinchi smenada boruvchilar uchun)
- Tushdan keyin: 14:00, 15:30 va 17:00
- Kechki: 18:30 (asosan IELTS)
Dars kunlari: Du-Cho-Ju yoki Se-Pa-Sha.
Guruhda 8–12 o'quvchi. Yangi guruhlar har oyning 1- va 15-sanasida ochiladi.""",
    "KB_PROMO": """\
- Aka-uka/opa-singil birga o'qisa, ikkinchi farzand uchun 10% chegirma.
- 3 oyga oldindan to'lansa — 1 hafta darslar bepul.
- Do'stini olib kelgan o'quvchiga keyingi oy uchun 50 000 so'm chegirma.""",
    "KB_FAQ": """\
S: O'qituvchilar kimlar?
J: Ingliz tili ustozlarimiz CELTA yoki IELTS 7.5+ sertifikatiga ega, matematika ustozlari — 5+ yillik tajribali pedagoglar.

S: Sertifikat beriladimi?
J: Ha, har bir daraja yoki kurs yakunida Wunderkind sertifikati beriladi.

S: Dars qoldirilsa nima bo'ladi?
J: Kasallik sababli qoldirilgan darslarni boshqa guruhda bepul qayta o'tish mumkin. To'lov qaytarilmaydi.

S: Farzandim natijasini qanday bilaman?
J: Har oy oxirida ota-onaga Telegram orqali baholar va ustoz izohi bilan hisobot yuboriladi.

S: Online darslar bormi?
J: Hozircha faqat IELTS kursi online formatda ham bor (Zoom orqali, narxi bir xil).

S: Parkovka bormi?
J: Ikkala filial yonida ham bepul avtoturargoh bor.""",
    "KB_RULES": """\
- Ota-onaga «Siz» deb murojaat qil, samimiy va qisqa yoz.
- Faqat yuqoridagi narx va aksiyalarni ayt, o'zingdan chegirma va'da berma.
- Maqsad — bepul sinov darsiga yozish: ism, farzand yoshi va telefon raqamini so'ra.
- Aniq javobi yo'q savolda administrator bog'lanishini ayt.""",
}

GREETING = """\
Assalomu alaykum! 👋 Wunderkind o'quv markaziga xush kelibsiz.
Quyidagi bo'limlardan birini tanlang yoki savolingizni yozing — AI yordamchimiz darhol javob beradi."""

MENU: list[dict[str, str]] = [
    {"command": "kurslar", "title": "📚 Kurslar va narxlar", "text": """\
📚 Kurslarimiz (oylik narx):

• Ingliz tili Kids (6–9 yosh) — 450 000 so'm
• Ingliz tili Juniors (10–14 yosh) — 550 000 so'm
• IELTS (15+) — 800 000 so'm
• Matematika, Prezident maktabiga tayyorlov — 500 000 so'm
• Mental arifmetika (5–10 yosh) — 400 000 so'm
• Robototexnika (8–14 yosh) — 600 000 so'm
• Rus tili (7–14 yosh) — 400 000 so'm

Batafsil ma'lumot uchun kurs nomini yozing."""},
    {"command": "sinov", "title": "🎁 Bepul sinov darsi", "text": """\
🎁 Bepul sinov darsi — 60 daqiqa.

Yozilish uchun shu yerga yozing:
1) Farzandingiz ismi va yoshi
2) Qaysi kurs qiziqtiradi
3) Telefon raqamingiz

Administratorimiz qulay vaqtni kelishish uchun qo'ng'iroq qiladi."""},
    {"command": "jadval", "title": "🕘 Dars jadvali", "text": """\
🕘 Guruh vaqtlari:
• Ertalab: 9:00, 10:30
• Tushdan keyin: 14:00, 15:30, 17:00
• Kechqurun: 18:30

Dars kunlari: Du-Cho-Ju yoki Se-Pa-Sha.
Yangi guruhlar har oyning 1- va 15-sanasida ochiladi."""},
    {"command": "aksiyalar", "title": "🔥 Aksiyalar", "text": """\
🔥 Amaldagi aksiyalar:
• Ikkinchi farzand uchun — 10% chegirma
• 3 oyga oldindan to'lov — 1 hafta bepul
• Do'stingizni olib keling — 50 000 so'm chegirma"""},
    {"command": "manzil", "title": "📍 Manzil va aloqa", "text": """\
📍 Filiallarimiz:
• Chilonzor — Bunyodkor shoh ko'chasi 12 («Chilonzor» metro)
• Yunusobod — Amir Temur ko'chasi 108 («Minor» metro)

🕘 Du–Sha, 9:00–20:00
📞 +998 71 200 00 00
💬 @wunderkind_admin"""},
]


def _env(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    env = Path(__file__).resolve().parents[2] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"{key} not found in environment or .env")


def call(method: str, path: str, body: dict | None = None, token: str = "") -> dict:
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path} -> {exc.code}: {exc.read().decode()[:300]}")
    return json.loads(raw) if raw else {}


def current_values(payload: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for group in payload["groups"]:
        for item in group.get("items", []):
            values[item["key"]] = item.get("value") or ""
    return values


def main() -> None:
    token = call("POST", "/auth/login", {
        "username": _env("ADMIN_USERNAME"), "password": _env("ADMIN_PASSWORD"),
    })["access_token"]

    existing = current_values(call("GET", "/settings", token=token))
    todo = {k: v for k, v in KNOWLEDGE.items() if not existing.get(k, "").strip()}
    if todo:
        call("PUT", "/settings", {"values": todo}, token=token)
    print(f"settings: set {sorted(todo) or 'nothing'}; kept {sorted(set(KNOWLEDGE) - set(todo)) or 'nothing'}")

    menu = call("GET", "/bot-menu", token=token)
    if not (menu.get("greeting") or "").strip():
        call("PUT", "/bot-menu/greeting", {"greeting": GREETING}, token=token)
        print("menu greeting: set")
    have = {i["command"] for i in menu.get("items", [])}
    for item in MENU if os.environ.get("SEED_MENU") else []:
        if item["command"] in have:
            print(f"menu /{item['command']}: exists, kept")
            continue
        call("POST", "/bot-menu/items", item, token=token)
        print(f"menu /{item['command']}: created")


if __name__ == "__main__":
    main()
