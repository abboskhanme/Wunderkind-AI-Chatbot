# Wunderkind AI Agent — foydalanuvchi qo'llanmasi

AI agent Instagram (izoh va shaxsiy xabar) hamda Telegramda ota-onalarga o'zi
javob beradi, ularni **maktabga qabul suhbatiga** yozishga olib boradi va ism +
telefon raqamini yig'adi. Hamma yozishma admin panelda saqlanadi.

## 1. Kirish
Admin panel manzilini oching, login va parolni kiriting.
- **Administrator** — hamma bo'lim.
- **Operator** — faqat Bosh sahifa, Suhbatlar va Leadlar.

## 2. Birinchi sozlash (administrator)

### 2.1. Sun'iy intellekt
**Sozlamalar → Sun'iy intellekt**: provayder — **gemini**. Gemini API kalitini
(aistudio.google.com → Get API key) kiriting va saqlang. Kalitsiz agent javob bermaydi.

### 2.2. Bilim bazasi — eng muhim qism
**Bilim bazasi** bo'limida quyidagilarni to'liq yozing:
- Maktab haqida (manzil, ish vaqti, telefon, raqamlar bilan afzalliklar)
- Sinflar, ta'lim dasturi va to'lov (oylik to'lov va unga nimalar kiradi)
- Qabul tartibi va kun tartibi
- Aksiyalar (faqat haqiqiylari)
- Ko'p so'raladigan savollar («S:» savol, «J:» javob)

Agent **faqat shu yerdagi** narx va ma'lumotlarni aytadi. Yo'q narsa so'ralsa,
administratorga o'tkazadi. Qancha to'liq yozsangiz, shuncha kam savol sizga tushadi.

### 2.3. Sinab ko'rish
**Sinov** bo'limida mijoz o'rnida yozib ko'ring. Hech kimga hech narsa
yuborilmaydi. Javob yoqmasa — bilim bazasini to'ldiring yoki «Muloqot
qoidalari»ga qo'shimcha yozing.

### 2.4. Telegram
1. Telegramda @BotFather → `/newbot` → token oling.
2. **Sozlamalar → Telegram**: «AI bot tokeni» va «Webhook maxfiy kaliti»
   (20+ tasodifiy belgi) ni kiriting.
3. Xodimlar uchun bildirishnoma: har bir xodim botga `/start` bosadi, uning chat
   ID sini «Bildirishnoma oluvchilar» ga yozing. «Test xabar» tugmasi bilan tekshiring.
4. Ixtiyoriy (Telegram Premium): Telegram → Sozlamalar → Telegram Business →
   Chatbotlar → botni ulang. Shunda bot shaxsiy chatlaringizga ham siz nomingizdan javob beradi.

### 2.5. Instagram
1. Meta ilovasida (Instagram API with Instagram Login) App ID va App Secret oling.
2. **Sozlamalar → Instagram**: App ID, App Secret va o'zingiz o'ylab topgan
   «Webhook verify token» ni kiriting.
3. Meta ilovasida webhook manzilini (Sozlamalar sahifasida ko'rsatilgan) va
   verify tokenni kiriting, `comments` va `messages` ga obuna bo'ling.
4. **«Ulash»** tugmasini bosing va Instagram akkauntingiz bilan kiring.
5. Istasangiz «Eski suhbatlarni import qilish» — oxirgi 30 kundagi yozishmalar
   Suhbatlar bo'limiga tushadi (ularga AI javob yozmaydi).

### 2.6. Bot menyusi (Telegram)
**Bot menyusi** bo'limida tugmalar qo'shing (masalan «🏫 Maktab haqida», «📍 Manzil»).
Mijoz tugmani bossa, AI'siz tayyor matn va rasmlar yuboriladi.

## 3. Kundalik ish

### Suhbatlar
- Chapda barcha suhbatlar; o'qilmaganlar belgilanadi.
- Suhbatni ochib o'zingiz javob yozishingiz mumkin. Siz yozsangiz ham **AI javob
  berishda davom etadi**. AI'ni biror suhbatda to'xtatish kerak bo'lsa, «AI javob»
  tugmasi bilan qo'lda o'chiring (qayta yoqmaguningizcha jim turadi).
- Instagramda javob oynasi cheklangan: mijozning oxirgi xabaridan 24 soat erkin,
  7 kungacha faqat operator javobi, keyin yopiq — telefon orqali bog'laning.
- O'ng tomonda lead kartasi: holat, ism, telefon, qiziqish, izoh.

### Leadlar
Holatlar: **Yangi → Bog'lanildi → Suhbatga yozildi → Qabul qilindi / Yo'qotildi.**
Telefon qoldirganlarga qo'ng'iroq qiling va holatni yangilang. CSV eksport bor.

### Telegram bildirishnomalari
- 🔥 **Qaynoq lead** — mijoz raqam qoldirdi yoki yozilishga tayyor: tezda qo'ng'iroq qiling.
- ⚠️ **Administrator kerak** — agent javobni bilmadi yoki mijoz odam so'radi.
- 📊 Har kuni belgilangan vaqtda kunlik hisobot.

## 4. Muhim eslatmalar
- Mijoz javob bermay qolsa, agent 3 soatdan keyin bir marta muloyim eslatma yozadi
  (Sozlamalar → Sotuv sozlamalari).
- Suhbatning birinchi xabarida agent AI yordamchi ekanini aytadi (Meta talabi).
- Instagram tokeni 60 kunlik, avtomatik yangilanadi. Muammo bo'lsa Telegramga xabar
  keladi — «Qayta ulash» tugmasini bosing.

## 5. Lead-magnet voronkasi («Voronka» bo'limi)

Video ostiga **«Wunderkind»** deb yozganlar «Lider farzand tarbiyalash uchun 8 ta
maslahat» qo'llanmasini Telegram bot orqali oladi, so'ng qabul suhbatiga yoziladi.
Bu qadamlar AI emas — matnlari oldindan yozilgan va o'zgarmaydi.

### 5.1. Sozlash (administrator)
1. **Voronka → (voronkani tanlang) → Sozlamalar**: shu voronkaning qo'llanma PDF
   faylini yuklang (20 MB gacha). PDF yuklanmaguncha kelganlar «tez orada
   yuboramiz» xabarini oladi va fayl yuklangach avtomatik qabul qiladi.
2. Matnlarni ko'rib chiqing: salomlashuv va savollar — voronka sozlamalarida,
   tasdiq va eslatma — «Umumiy sozlamalar»da. Tasdiq va
   eslatmada `{name}`, `{date}`, `{time}`, `{weekday}`, `{staff_name}`,
   `{staff_phone}`, `{address}` o'rinbosarlari ishlaydi. Mas'ul xodim, telefon,
   manzil va lokatsiyani (kenglik/uzunlik) to'ldiring.
3. **Xabarlar** yorlig'ida qo'llanmadan keyin yuboriladigan 3 ta namuna sotuv xabari
   bor — ular **o'chirilgan** holda turadi. `[raqam]`, `[imtiyoz]` joylarini haqiqiy
   ma'lumot bilan almashtiring va keyin yoqing. Matnda `[raqam]` yoki `[imtiyoz]`
   qolib ketsa, xabar yoqilgan bo'lsa ham mijozga yuborilmaydi.
   Xabarlar faqat 09:00–21:00 oralig'ida ketadi va mijoz suhbatga yozilgach to'xtaydi.
4. Suhbat kunlari va vaqti: standart — dushanba–shanba, 09:00–16:00, har 30
   daqiqada bitta oila. Bayram kunlarini «Dam olish kunlari»ga yozing.

### 5.2. Telegram kanal
- Botni **kanalga administrator** qilib qo'shing — shunda bot obunani tekshira oladi.
- Kanal postlari ostidagi izohlarga javob berishi uchun botni kanalning
  **muhokama guruhiga ham administrator** qiling (yoki @BotFather'da
  `/setprivacy` → Disable). Guruhda `/id` yozib, chiqqan ID ni «Kanal muhokama
  guruhi ID» maydoniga kiriting.

### 5.3. Google Sheets
1. Google Cloud'da service account yarating va JSON kalitini yuklab oling.
2. JSON matnini **Voronka → Sozlamalar → Service account JSON** maydoniga to'liq qo'ying.
3. Jadvalni JSON ichidagi `client_email` manziliga **Editor** qilib ulashing,
   jadval havolasini kiriting va «Google Sheets'ni tekshirish» tugmasini bosing.
4. Har bir mijoz — bitta qator, ma'lumot o'zgarsa o'sha qator yangilanadi.
   Qatorni oxirgi **«ID»** ustuni bo'yicha topadi — shuning uchun jadvalni
   saralash mumkin, lekin **«ID» ustunini o'chirmang va o'zgartirmang**. Birinchi
   qator (sarlavha) tizimniki.
5. Jadval havolasi yoki varaq nomi o'zgartirilsa, barcha mijozlar yangi jadvalga
   qaytadan yoziladi.
6. Bitta odam avval Instagram, keyin Telegram orqali kelgan bo'lsa, ikki yozuv
   birlashtiriladi; eski qatorning «Manba» katagida «Birlashtirildi» yoziladi.

### 5.4. Kundalik ish
- **Suhbatlar** yorlig'ida yozilganlar: kelgan/kelmagan holatini belgilang, izoh
  qoldiring. Suhbat kuni ertalab (07:00) mijozga eslatma avtomatik ketadi.
- Yangi yozilish, vaqt o'zgarishi va bekor qilish haqida Telegramga bildirishnoma keladi.
- Mijoz botda `/stop` yozsa, sotuv xabarlari to'xtaydi; savollar o'rtasida bo'lsa,
  savollar ham to'xtaydi (botga `/start` bosib davom ettiradi).
- Ism/telefon/sinf so'ralayotganda mijoz savol bersa («?» bilan) yoki ikki marta
  noto'g'ri javob yozsa, unga AI javob beradi; to'g'ri javob yozgach savollar davom etadi.
- Instagram'da siz o'zingiz yozgan (AI to'xtatilgan) suhbatga voronka aralashmaydi.
- Qo'llanmani yuborishda Telegram xato bersa, tizim o'zi qayta urinadi va sizga
  bildirishnoma keladi.

### 5.5. Bir nechta voronka
Har xil video yoki reklama uchun alohida voronka ochish mumkin (masalan «Yozgi
lager»). Barcha voronkalarda qadamlar bir xil (obuna → ism → telefon → sinf →
qo'llanma → suhbatga yozilish); jadval, mas'ul xodim, manzil, tasdiq/eslatma
matnlari va Google Sheets — umumiy.

Har bir voronkaning o'zida:
- **Kalit so'zlar** — izohga shu so'z yozilsa, shu voronka ishlaydi. Asosiy voronkada
  bo'sh qoldirilsa — umumiy kalit so'zlar ishlatiladi.
- **Instagram postlari** (ixtiyoriy) — post havolalarini qo'ying: kalit so'z faqat
  shu postlar ostida shu voronkaga olib keladi. Bo'sh — istalgan post.
- **Qo'llanma PDF** va **sotuv xabarlari** — har voronkaning o'zi.
- **Matnlar** — bo'sh maydon umumiy matnni ishlatadi (maydonda kulrang ko'rinadi).
- **Havolalar** — Telegram kanal posti uchun `?start=tgc_<nom>`, reklama/bio uchun
  `?start=f_<nom>`; sozlamalarda nusxa olish tugmasi bor.

Qoidalar:
- Bir xil kalit so'z bir xil postlar uchun ikkita faol voronkada bo'lolmaydi — tizim
  saqlashga ruxsat bermaydi. Turli postlar uchun bir xil so'z ishlatish mumkin.
- Bitta ota-ona bir nechta voronkadan o'tishi mumkin: ism va telefon qayta
  so'ralmaydi, har voronka o'z qo'llanmasini yuboradi. Suhbatga esa bitta yoziladi —
  boshqa voronkadan yozilsa, vaqti o'zgaradi.
- Nofaol voronka yangi mijoz qabul qilmaydi, boshlaganlar oxirigacha o'tadi.
- Mijozi bor voronkani o'chirib bo'lmaydi — uni **arxivlang** (nofaol qiling).
  Asosiy voronkani o'chirib yoki nofaol qilib bo'lmaydi.
- Yangi voronkani mavjudidan **nusxa** qilib ochish mumkin: matnlar, sotuv xabarlari
  va PDF ko'chadi (kalit so'zlar va postlar — yo'q).
- Google Sheets'da oxirgi «Voronka» ustuni qo'shiladi (mavjud qatorlar keyingi
  yangilanishda to'ladi). **«O» ustuni «Voronka» uchun ajratilgan** — unga o'z
  ma'lumotingizni yozmang. Agar u yerda boshqa narsa bo'lsa, tizim uni o'chirmaydi:
  «Voronka» yozilmaydi va Telegramga ogohlantirish keladi.
