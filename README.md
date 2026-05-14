# 💰 FinTrack — Shaxsiy va Oilaviy Moliyani Boshqarish Tizimi by AcoderM

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2-092E20?style=for-the-badge&logo=django&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge)

**Daromad, xarajat, qarz va byudjetlarni oson kuzating — oila bilan birga.**

</div>

---

## 📋 Mundarija

- [Loyiha haqida](#-loyiha-haqida)
- [Asosiy imkoniyatlar](#-asosiy-imkoniyatlar)
- [Texnologiyalar](#-texnologiyalar)
- [O'rnatish](#-ornatish)
- [Muhit o'zgaruvchilari](#-muhit-ozgaruvchilari)
- [Ishga tushirish](#-ishga-tushirish)
- [Loyiha tuzilmasi](#-loyiha-tuzilmasi)
- [Hissa qo'shish](#-hissa-qoshish)
- [Litsenziya](#-litsenziya)

---

## 🎯 Loyiha haqida

**FinTrack** — bu shaxsiy va oilaviy moliyani kuzatish uchun mo'ljallangan veb-ilova. Daromadlar, xarajatlar, qarzlar va byudjetlarni bir joyda boshqarish imkonini beradi. Oilaviy guruh tizimi orqali bir nechta foydalanuvchi birgalikda moliyaviy ma'lumotlarini kuzata oladi. AI assistent moliyaviy maslahatlar beradi.

---

## ✨ Asosiy imkoniyatlar

### 🏦 Hisob raqamlar
- Naqd pul, bank kartasi, bank hisob raqami, jamg'arma, investitsiya va kripto hisoblarni boshqarish
- Ko'p valyuta qo'llab-quvvatlash: **UZS, USD, EUR, RUB**
- Past balans ogohlantirish chegarasini belgilash
- Hisobni umumiy balansga qo'shish/chiqarish

### 💸 Tranzaksiyalar
- Daromad, xarajat va hisoblar o'rtasida o'tkazma
- Kategoriyalar bo'yicha tasniflash (maxsus ikonkalar bilan)
- Valyuta konvertatsiyasi (real kurs bilan)
- Tranzaksiya kalendari ko'rinishi
- Izoh va qo'shimcha eslatmalar

### 📊 Byudjet
- Kategoriya bo'yicha oylik byudjet belgilash
- Sarflangan va qolgan miqdorni real vaqtda kuzatish
- Oilaviy umumiy byudjet

### 💳 Qarzlar
- Berilgan va olingan qarzlarni alohida kuzatish
- Qisman to'lov va muddatlarni belgilash
- Holat: Ochiq / Qisman qaytarildi / Yopiq

### 👨‍👩‍👧‍👦 Oilaviy guruh
- Taklifnoma kodi orqali oilaga qo'shilish
- Rol tizimi: Ota, Ona, O'g'il, Qiz
- Oilaviy umumiy statistika va hisobot
- Qo'shilish so'rovlarini tasdiqlash/rad etish

### 🤖 AI Assistent
- Moliyaviy maslahat va tahlil
- Ko'p AI provayderlarni qo'llab-quvvatlash: **Groq, OpenAI, Anthropic, Gemini**
- `auto` rejimi — provayderlarni ketma-ket sinab ko'radi

### 📈 Analitika va Dashboard
- Daromad/xarajat dinamikasi grafigi
- Kategoriyalar bo'yicha taqsimot
- Oylik va yillik hisobotlar
- Oilaviy moliyaviy statistika

### 🔒 Xavfsizlik
- Login urinishlarini cheklash (rate limiting)
- Nofaollik holatida avtomatik chiqish (idle logout)
- HTTPS, HSTS, CSRF muhofazasi sozlamalari
- Redis kesh va sessiya qo'llab-quvvatlash

---

## 🛠 Texnologiyalar

| Qatlam | Texnologiya |
|--------|-------------|
| Backend | Django 5.2 |
| Ma'lumotlar bazasi | SQLite (dev) / PostgreSQL (prod) |
| Kesh / Sessiya | Redis (ixtiyoriy) |
| Static fayllar | WhiteNoise + Brotli |
| App server | Gunicorn |
| AI integratsiya | Groq, OpenAI, Anthropic, Gemini |
| Rasm ishlash | Pillow |
| Konfiguratsiya | python-decouple |

---

## ⚙️ O'rnatish

### Talablar

- Python 3.11+
- pip
- (Ixtiyoriy) PostgreSQL, Redis

### 1. Repozitoriyani klonlash

```bash
git clone https://github.com/AcoderM-tech/Fintrack.git
cd Fintrack
```

### 2. Virtual muhit yaratish

```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
```

### 3. Kutubxonalarni o'rnatish

```bash
pip install -r requirements.txt
```

### 4. Muhit o'zgaruvchilarini sozlash

```bash
cp .env.example .env
```

Keyin `.env` faylini tahrirlang (quyidagi bo'limga qarang).

### 5. Ma'lumotlar bazasini tayyorlash

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Static fayllarni yig'ish (production uchun)

```bash
python manage.py collectstatic
```

---

## 🔧 Muhit o'zgaruvchilari

`.env.example` faylidan nusxa ko'chiring va quyidagilarni to'ldiring:

```env
# Majburiy
SECRET_KEY=your-very-strong-secret-key

# Rejim
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# Ma'lumotlar bazasi (production uchun)
# DATABASE_URL=postgresql://user:password@localhost:5432/fintrack_db

# Redis (ixtiyoriy, production uchun tavsiya etiladi)
# REDIS_URL=redis://127.0.0.1:6379/1

# Valyuta kurslari (UZS ga nisbatan)
RATE_USD=12700
RATE_EUR=13800
RATE_RUB=140

# AI (kamida bittasini to'ldiring)
AI_PROVIDER=auto
GROQ_API_KEY=your-groq-key
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
GEMINI_API_KEY=your-gemini-key
```

---

## 🚀 Ishga tushirish

### Development

```bash
python manage.py runserver
```

Brauzerda oching: [http://127.0.0.1:8000](http://127.0.0.1:8000)

### Production (Gunicorn)

```bash
gunicorn fintrack.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

### Production sozlamalari

```env
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
```

---

## 📁 Loyiha tuzilmasi

```
fintrack/
├── fintrack/               # Asosiy Django konfiguratsiyasi
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── core/                   # Foydalanuvchi profili, oila guruhi, AI assistent
│   ├── models.py           # FamilyGroup, FamilyMember, UserProfile
│   ├── views.py
│   └── ai.py               # AI provayder integratsiyasi
├── accounts_app/           # Hisob raqamlar
├── transactions/           # Tranzaksiyalar va kategoriyalar
├── budgets/                # Byudjet rejalashtirish
├── debts/                  # Qarzlar
├── analytics/              # Tahlil va hisobotlar
├── templates/              # HTML shablonlar
├── static/                 # CSS, JS
├── requirements.txt
└── .env.example
```

---

## 🤝 Hissa qo'shish

Pull request va issue ochishni mamnuniyat bilan qabul qilamiz!

1. Repozitoriyani fork qiling
2. Yangi branch yarating: `git checkout -b feature/yangi-imkoniyat`
3. O'zgarishlarni commit qiling: `git commit -m "feat: yangi imkoniyat qo'shildi"`
4. Branch ni push qiling: `git push origin feature/yangi-imkoniyat`
5. Pull Request oching

---

## 📄 Litsenziya

Bu loyiha **MIT litsenziyasi** asosida tarqatiladi. Batafsil ma'lumot uchun [LICENSE](LICENSE) fayliga qarang.

---

<div align="center">
Made with ❤️ in Uzbekistan
</div>