"""
FinTrack — Demo ma'lumotlar seed skripti (v2)
=============================================
Ishlatish:
    cd fintrack_mobile
    python seed_demo.py

Nima yaratadi:
  - 2 ta foydalanuvchi (demo / demo2)
  - 7 ta hisob
  - 12 ta kategoriya
  - 6 oylik tranzaksiyalar (150+ yozuv)
  - Joriy oy byudjetlari
  - 5 ta qarz + to'lovlar
  - 1 ta oila guruhi
"""

import os, calendar
from decimal import Decimal
from datetime import date, timedelta
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fintrack.settings')

import django
try:
    django.setup()
except RuntimeError:
    pass

from django.contrib.auth.models import User
from django.db import transaction as db_transaction
from django.db.models import F

from accounts_app.models import Account
from transactions.models import Transaction, Category
from budgets.models import Budget
from debts.models import Debt, DebtPayment
from core.models import FamilyGroup, FamilyMember


def p(msg):   print(f"  {msg}")
def hr(msg):  print(f"\n{'='*52}\n  {msg}\n{'='*52}")

def last_day(y, m):
    return calendar.monthrange(y, m)[1]

def rnd_date(y, m, lo=1, hi=None):
    hi = min(hi or last_day(y, m), last_day(y, m))
    lo = max(1, min(lo, hi))
    return date(y, m, random.randint(lo, hi))

def prev_months(n=6):
    today = date.today()
    result = []
    for i in range(n - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        result.append((y, m))
    return result


def create_tx(user, tx_type, amount, currency, account,
              category, description, dt, family=None,
              to_account=None, notes=""):
    """
    Model.save() validation larini chetlab o'tib to'g'ridan-to'g'ri
    bulk_create bilan yozadi, keyin balansni F() bilan yangilaydi.
    Balans hech qachon manfiy bo'lmaydi.
    """
    obj = Transaction(
        user=user, family=family,
        transaction_type=tx_type,
        amount=Decimal(str(amount)),
        currency=currency,
        account=account,
        to_account=to_account,
        category=category,
        description=description,
        date=dt, notes=notes,
        exchange_rate=Decimal("1"),
    )
    Transaction.objects.bulk_create([obj])

    amt = Decimal(str(amount))
    if tx_type == "income":
        Account.objects.filter(pk=account.pk).update(balance=F("balance") + amt)
    elif tx_type == "expense":
        Account.objects.filter(pk=account.pk).update(balance=F("balance") - amt)
    elif tx_type == "transfer":
        Account.objects.filter(pk=account.pk).update(balance=F("balance") - amt)
        if to_account:
            Account.objects.filter(pk=to_account.pk).update(balance=F("balance") + amt)


@db_transaction.atomic
def seed():
    hr("FinTrack Demo Seed boshlandi")
    today  = date.today()
    months = prev_months(6)

    # ── 1. FOYDALANUVCHILAR ───────────────────────────────────────────────────
    hr("1. Foydalanuvchilar")

    def make_user(uname, first, last, email, pwd):
        u, created = User.objects.get_or_create(
            username=uname,
            defaults=dict(first_name=first, last_name=last, email=email)
        )
        if created:
            u.set_password(pwd)
            u.save()
            p(f"✓ Yaratildi : {uname}  paroli: {pwd}")
        else:
            p(f"→ Mavjud    : {uname}")
        return u

    u1 = make_user("demo",  "Jasur",  "Toshmatov", "demo@fintrack.uz",  "Demo1234!")
    u2 = make_user("demo2", "Malika", "Yusupova",  "demo2@fintrack.uz", "Demo1234!")

    # ── 2. OILA ───────────────────────────────────────────────────────────────
    hr("2. Oila guruhi")

    fam, fc = FamilyGroup.objects.get_or_create(
        name="Toshmatov oilasi",
        defaults=dict(created_by=u1, invite_code="DEMO2024")
    )
    p(("✓ Yaratildi : " if fc else "→ Mavjud    : ") +
      fam.name + f"  (kod: {fam.invite_code})")
    FamilyMember.objects.get_or_create(family=fam, user=u1, defaults={"role": "father"})
    FamilyMember.objects.get_or_create(family=fam, user=u2, defaults={"role": "mother"})
    p("✓ Jasur = ota,  Malika = ona")

    # ── 3. KATEGORIYALAR ──────────────────────────────────────────────────────
    hr("3. Kategoriyalar")

    CAT_DATA = [
        ("Oziq-ovqat",         "expense", "shopping-cart",   "#f59e0b"),
        ("Transport",          "expense", "car",             "#3b82f6"),
        ("Kommunal",           "expense", "home",            "#8b5cf6"),
        ("Ko'ngilochar",       "expense", "music",           "#ec4899"),
        ("Internet/Telefon",   "expense", "wifi",            "#06b6d4"),
        ("Kiyim-kechak",       "expense", "shirt",           "#ef4444"),
        ("Sog'liq",            "expense", "heart",           "#10b981"),
        ("Ta'lim",             "expense", "book",            "#f97316"),
        ("Restoran",           "expense", "tools-kitchen-2", "#d97706"),
        ("Maosh",              "income",  "wallet",          "#22c55e"),
        ("Qo'shimcha daromad", "income",  "trending-up",     "#16a34a"),
        ("Dividend",           "income",  "chart-bar",       "#15803d"),
    ]

    cats = {}
    for name, ctype, icon, color in CAT_DATA:
        cat, created = Category.objects.get_or_create(
            name=name, is_default=True,
            defaults=dict(category_type=ctype, icon=icon, color=color)
        )
        cats[name] = cat
        if created:
            p(f"✓ {name}")

    def c(name):
        return cats.get(name) or Category.objects.filter(
            name=name, is_default=True).first()

    # ── 4. HISOBLAR ───────────────────────────────────────────────────────────
    hr("4. Hisoblar")

    def make_acc(user, name, atype, currency, bal, color, icon, family=None):
        acc, created = Account.objects.get_or_create(
            user=user, name=name,
            defaults=dict(
                account_type=atype, currency=currency,
                balance=Decimal(str(bal)),
                initial_balance=Decimal(str(bal)),
                color=color, icon=icon,
                family=family, is_active=True,
            )
        )
        if created:
            p(f"✓ {user.first_name}: {name} ({currency}) = {bal:>12,}")
        return acc

    # Katta boshlang'ich balans — 6 oy xarajatlaridan keyin ham musbat qoladi
    a_card1 = make_acc(u1, "Asosiy karta",  "card",    "UZS", 80_000_000, "#6366f1", "credit-card")
    a_cash1 = make_acc(u1, "Naqd pul",      "cash",    "UZS", 10_000_000, "#10b981", "cash")
    a_save1 = make_acc(u1, "Jamg'arma",     "savings", "UZS", 15_000_000, "#f59e0b", "piggy-bank")
    a_usd1  = make_acc(u1, "Dollar hisob",  "bank",    "USD",        500, "#3b82f6", "building-bank")
    a_card2 = make_acc(u2, "Malika karta",  "card",    "UZS", 50_000_000, "#ec4899", "credit-card")
    a_cash2 = make_acc(u2, "Naqd pul",      "cash",    "UZS",  5_000_000, "#14b8a6", "cash")
    a_fam   = make_acc(u1, "Oilaviy hisob", "card",    "UZS", 30_000_000, "#8b5cf6", "users",
                       family=fam)

    # ── 5. TRANZAKSIYALAR ─────────────────────────────────────────────────────
    hr("5. Tranzaksiyalar (6 oy)")

    if Transaction.objects.filter(user=u1, description__startswith="[DEMO]").exists():
        p("→ Allaqachon mavjud — o'tkazib yuborilmoqda")
    else:
        tx_count = 0

        for y, m in months:
            is_cur = (y == today.year and m == today.month)
            ld = last_day(y, m)

            def day(lo, hi):
                d = rnd_date(y, m, lo, hi)
                return min(d, today) if is_cur else d

            # ── JASUR ──────────────────────────────────────────
            create_tx(u1, "income", 8_500_000, "UZS", a_card1,
                c("Maosh"), f"[DEMO] Maosh {y}/{m:02d}",
                date(y, m, min(5, ld)), notes="Asosiy ish joyi")
            tx_count += 1

            if m % 2 == 0:
                create_tx(u1, "income",
                    random.randint(800_000, 1_500_000), "UZS", a_card1,
                    c("Qo'shimcha daromad"),
                    f"[DEMO] Freelance {y}/{m:02d}", day(10, 20),
                    notes="Freelance loyiha")
                tx_count += 1

            jasur_exp = [
                ("Oziq-ovqat",       600_000,  900_000, a_card1,  6, 13),
                ("Oziq-ovqat",       200_000,  400_000, a_cash1, 18, 26),
                ("Transport",        150_000,  220_000, a_card1,  2, 28),
                ("Kommunal",         250_000,  320_000, a_card1, 13, 17),
                ("Internet/Telefon",  85_000,   95_000, a_card1, 19, 22),
                ("Ko'ngilochar",     100_000,  200_000, a_card1, 14, 26),
                ("Restoran",          80_000,  160_000, a_cash1,  9, 28),
                ("Sog'liq",          100_000,  250_000, a_card1,  4, 22),
            ]
            for cat_name, lo_s, hi_s, acc, d_lo, d_hi in jasur_exp:
                create_tx(u1, "expense",
                    random.randint(lo_s, hi_s), "UZS", acc,
                    c(cat_name), f"[DEMO] {cat_name} {y}/{m:02d}", day(d_lo, d_hi))
                tx_count += 1

            if m % 2 == 1:
                create_tx(u1, "expense",
                    random.randint(350_000, 600_000), "UZS", a_card1,
                    c("Kiyim-kechak"), f"[DEMO] Kiyim {y}/{m:02d}", day(10, 25))
                tx_count += 1

            create_tx(u1, "transfer", 500_000, "UZS", a_card1, None,
                f"[DEMO] Jamg'armaga {y}/{m:02d}", day(25, ld),
                to_account=a_save1, notes="Oylik tejash")
            tx_count += 1

            # ── MALIKA ─────────────────────────────────────────
            create_tx(u2, "income", 5_500_000, "UZS", a_card2,
                c("Maosh"), f"[DEMO] Malika maosh {y}/{m:02d}",
                date(y, m, min(3, ld)))
            tx_count += 1

            malika_exp = [
                ("Oziq-ovqat",   350_000, 500_000, a_card2,  5, 22),
                ("Ta'lim",       280_000, 320_000, a_card2,  7, 14),
                ("Ko'ngilochar",  80_000, 140_000, a_cash2, 14, 28),
                ("Sog'liq",      120_000, 200_000, a_card2,  8, 25),
                ("Kiyim-kechak", 200_000, 400_000, a_card2, 16, 26),
            ]
            for cat_name, lo_s, hi_s, acc, d_lo, d_hi in malika_exp:
                create_tx(u2, "expense",
                    random.randint(lo_s, hi_s), "UZS", acc,
                    c(cat_name),
                    f"[DEMO] {cat_name} (Malika) {y}/{m:02d}", day(d_lo, d_hi))
                tx_count += 1

            # ── OILAVIY ────────────────────────────────────────
            fam_exp = [
                ("Oziq-ovqat", 500_000, 700_000,  3, 12),
                ("Kommunal",   300_000, 400_000, 13, 17),
                ("Transport",  150_000, 250_000,  4, 26),
            ]
            for cat_name, lo_s, hi_s, d_lo, d_hi in fam_exp:
                create_tx(u1, "expense",
                    random.randint(lo_s, hi_s), "UZS", a_fam,
                    c(cat_name),
                    f"[DEMO] Oila {cat_name} {y}/{m:02d}", day(d_lo, d_hi),
                    family=fam)
                tx_count += 1

        p(f"✓ {tx_count} ta tranzaksiya yozildi")

    # ── 6. BYUDJETLAR ─────────────────────────────────────────────────────────
    hr("6. Byudjetlar (joriy oy)")

    cy, cm = today.year, today.month
    BUDGETS = [
        (u1, "Oziq-ovqat",       "expense", 1_200_000),
        (u1, "Transport",        "expense",   250_000),
        (u1, "Kommunal",         "expense",   350_000),
        (u1, "Ko'ngilochar",     "expense",   200_000),
        (u1, "Internet/Telefon", "expense",   100_000),
        (u1, "Kiyim-kechak",     "expense",   500_000),
        (u1, "Sog'liq",          "expense",   300_000),
        (u1, "Restoran",         "expense",   200_000),
        (u1, "Maosh",            "income",  8_500_000),
        (u2, "Oziq-ovqat",       "expense",   600_000),
        (u2, "Ta'lim",           "expense",   400_000),
        (u2, "Ko'ngilochar",     "expense",   150_000),
        (u2, "Kiyim-kechak",     "expense",   400_000),
        (u2, "Maosh",            "income",  5_500_000),
    ]

    b_count = 0
    for user, cat_name, btype, amount in BUDGETS:
        cat = c(cat_name)
        if not cat:
            continue
        _, created = Budget.objects.get_or_create(
            user=user, category=cat, month=cm, year=cy,
            defaults=dict(
                name=cat_name, budget_type=btype,
                amount=Decimal(str(amount)), currency="UZS"
            )
        )
        if created:
            b_count += 1
    p(f"✓ {b_count} ta byudjet yaratildi")

    # ── 7. QARZLAR ────────────────────────────────────────────────────────────
    hr("7. Qarzlar")

    DEBTS = [
        (u1, "given", "Azizbek Karimov",  "+998901234567", 2_000_000, -15,  30, "Biznes uchun qarz"),
        (u1, "given", "Sardor Umarov",    "+998935556677",   800_000,  -7,  14, "Vaqtinchalik qarz"),
        (u1, "taken", "Akbar Xolmatov",   "+998997778899", 3_000_000, -30,  60, "Mashina uchun"),
        (u2, "given", "Nilufar Rahimova", "+998901112233",   500_000,  -5,  20, "Do'stga yordam"),
        (u2, "taken", "Dildora Sobirova", "+998907654321", 1_500_000, -20,  45, "Shaxsiy ehtiyoj"),
    ]

    d_count = 0
    for user, dtype, name, phone, amount, days_ago, days_due, desc in DEBTS:
        if Debt.objects.filter(user=user, person_name=name,
                               description=f"[DEMO] {desc}").exists():
            continue

        acc = a_card1 if user == u1 else a_card2
        debt = Debt.objects.create(
            user=user, debt_type=dtype,
            person_name=name, person_phone=phone,
            amount=Decimal(str(amount)), currency="UZS",
            paid_amount=Decimal("0"), account=acc,
            description=f"[DEMO] {desc}",
            date=today + timedelta(days=days_ago),
            due_date=today + timedelta(days=days_due),
            status="open"
        )

        if dtype == "given":
            pay = round(amount * 0.25 / 10000) * 10000
            DebtPayment.objects.create(
                debt=debt,
                amount=Decimal(str(pay)),
                date=today - timedelta(days=random.randint(1, 5)),
                notes="[DEMO] Qisman to'lov"
            )
            p(f"✓ GIVEN : {name:<22} {amount:>10,} UZS  (to'lov: {pay:>8,})")
        else:
            p(f"✓ TAKEN : {name:<22} {amount:>10,} UZS")
        d_count += 1

    p(f"\n✓ Jami {d_count} ta qarz yozildi")

    # ── XULOSA ────────────────────────────────────────────────────────────────
    hr("SEED MUVAFFAQIYATLI YAKUNLANDI")

    for acc in [a_card1, a_cash1, a_save1, a_usd1, a_card2, a_fam]:
        acc.refresh_from_db()

    print(f"""
  👤 Login ma'lumotlari:
     demo   / Demo1234!   →  {u1.get_full_name()}
     demo2  / Demo1234!   →  {u2.get_full_name()}

  🏦 Joriy balanslar:
     Jasur:  Asosiy karta   {a_card1.balance:>14,.0f} UZS
             Naqd pul       {a_cash1.balance:>14,.0f} UZS
             Jamg'arma      {a_save1.balance:>14,.0f} UZS
             Dollar hisob   {a_usd1.balance:>14,.0f} USD
     Malika: Malika karta   {a_card2.balance:>14,.0f} UZS
     Oila:   Oilaviy hisob  {a_fam.balance:>14,.0f} UZS

  📊 Yaratilganlar:
     Tranzaksiyalar : {Transaction.objects.filter(user__in=[u1,u2]).count()} ta
     Byudjetlar     : {Budget.objects.filter(user__in=[u1,u2]).count()} ta
     Qarzlar        : {Debt.objects.filter(user__in=[u1,u2]).count()} ta

  🔗 Oila: "{fam.name}"  —  taklif kodi: {fam.invite_code}
    """)


seed()