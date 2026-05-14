from datetime import date, timedelta
from decimal import Decimal
import calendar
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from accounts_app.models import Account
from budgets.models import Budget
from debts.models import Debt, DebtPayment
from transactions.models import Category, Transaction
from core.models import UserProfile, FamilyGroup, FamilyMember, Notification, FamilyJoinRequest


class Command(BaseCommand):
    help = "Seed demo data for presentation (users, accounts, transactions, budgets, debts)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo", help="Demo username")
        parser.add_argument("--password", default="demo1234", help="Demo password")
        parser.add_argument("--reset", action="store_true", help="Clear existing demo data for this user")
        parser.add_argument("--no-family", action="store_true", help="Skip creating family demo data")
        parser.add_argument(
            "--purge-demo-users",
            action="store_true",
            help="Delete other demo users (*@fintrack.demo) to keep the DB clean",
        )

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]
        reset = options["reset"]
        with_family = not options["no_family"]
        purge_demo_users = options["purge_demo_users"]

        rng = random.Random(42)
        today = timezone.now().date()

        def month_date(month_offset, day):
            year = today.year
            month = today.month - month_offset
            while month <= 0:
                month += 12
                year -= 1
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, min(day, last_day))

        with db_transaction.atomic():
            if purge_demo_users:
                # Only remove users that were created by this seeder (safe for real users).
                User.objects.filter(email__endswith="@fintrack.demo").exclude(username=username).delete()

            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@fintrack.demo", "first_name": "Demo", "last_name": "User"},
            )
            if created:
                user.set_password(password)
                user.save()

            if reset and not created:
                Transaction.objects.filter(user=user).delete()
                Budget.objects.filter(user=user).delete()
                Debt.objects.filter(user=user).delete()
                Notification.objects.filter(user=user).delete()
                Category.objects.filter(user=user).delete()
                Account.objects.filter(user=user).delete()
                FamilyJoinRequest.objects.filter(user=user).delete()
                FamilyMember.objects.filter(user=user).delete()
                FamilyGroup.objects.filter(created_by=user).delete()
            elif not created:
                if Account.objects.filter(user=user).exists():
                    self.stdout.write(self.style.WARNING(f"User '{username}' already has data. Use --reset to recreate demo dataset."))
                    return

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone = "+998 90 123 45 67"
            profile.gender = "male"
            profile.default_currency = "UZS"
            profile.language = "uz"
            profile.save()

            # Categories
            categories = {}
            cat_defs = [
                ("Ish haqi", "income", "briefcase", "#22c55e"),
                ("Frilans", "income", "code", "#16a34a"),
                ("Sovg'a", "income", "gift", "#0ea5e9"),
                ("Oziq-ovqat", "expense", "shopping-cart", "#f59e0b"),
                ("Transport", "expense", "bus", "#3b82f6"),
                ("Kommunal", "expense", "bolt", "#f97316"),
                ("Ijara", "expense", "home", "#ef4444"),
                ("Ko'ngilochar", "expense", "movie", "#8b5cf6"),
                ("Sog'liq", "expense", "heart", "#ec4899"),
                ("Ta'lim", "expense", "book", "#06b6d4"),
                ("Kafe", "expense", "coffee", "#14b8a6"),
            ]
            for name, ctype, icon, color in cat_defs:
                cat = Category.objects.create(
                    user=user,
                    name=name,
                    category_type=ctype,
                    icon=icon,
                    color=color,
                    is_default=True,  # System/default category - will be translated in UI
                )
                categories[name] = cat

            # Accounts
            accounts = {}
            acct_defs = [
                ("Asosiy karta", "card", "UZS", Decimal("12800000"), "#3b82f6", "credit-card", "8600 1234 5678 9012"),
                ("Naqd pul", "cash", "UZS", Decimal("2500000"), "#10b981", "cash", ""),
                ("Jamg'arma", "savings", "UZS", Decimal("25000000"), "#6366f1", "coin", ""),
                ("USD karta", "card", "USD", Decimal("1500"), "#f59e0b", "currency-dollar", "4276 1122 3344 5566"),
            ]
            for name, atype, cur, initial, color, icon, card_no in acct_defs:
                acc = Account.objects.create(
                    user=user,
                    name=name,
                    account_type=atype,
                    currency=cur,
                    initial_balance=initial,
                    balance=initial,
                    color=color,
                    icon=icon,
                    card_number=card_no,
                )
                accounts[name] = acc

            # Helper to create transactions
            def add_tx(tx_type, amount, account, category, tx_date, desc="", to_account=None):
                Transaction.objects.create(
                    user=user,
                    transaction_type=tx_type,
                    amount=Decimal(str(amount)),
                    account=account,
                    to_account=to_account,
                    category=category,
                    description=desc,
                    date=tx_date,
                )

            # Transactions across last 6 months
            for m in range(0, 6):
                salary = rng.randint(8500000, 11500000)
                add_tx("income", salary, accounts["Asosiy karta"], categories["Ish haqi"], month_date(m, 3), "Oylik ish haqi")

                freelance = rng.randint(1200000, 2600000)
                add_tx("income", freelance, accounts["Naqd pul"], categories["Frilans"], month_date(m, 15), "Freelance")

                add_tx("expense", rng.randint(2200000, 2800000), accounts["Asosiy karta"], categories["Ijara"], month_date(m, 5), "Ijara to'lovi")
                add_tx("expense", rng.randint(300000, 520000), accounts["Asosiy karta"], categories["Kommunal"], month_date(m, 8), "Kommunal to'lovlar")
                add_tx("expense", rng.randint(200000, 420000), accounts["Asosiy karta"], categories["Transport"], month_date(m, 12), "Transport")
                add_tx("expense", rng.randint(300000, 650000), accounts["Asosiy karta"], categories["Ko'ngilochar"], month_date(m, 20), "Ko'ngilochar")
                add_tx("expense", rng.randint(200000, 500000), accounts["Asosiy karta"], categories["Sog'liq"], month_date(m, 22), "Sog'liq")
                add_tx("expense", rng.randint(180000, 360000), accounts["Asosiy karta"], categories["Ta'lim"], month_date(m, 26), "Ta'lim")

                for day in (10, 17, 24):
                    add_tx("expense", rng.randint(250000, 480000), accounts["Asosiy karta"], categories["Oziq-ovqat"], month_date(m, day), "Oziq-ovqat")

                add_tx("expense", rng.randint(60000, 120000), accounts["Naqd pul"], categories["Kafe"], month_date(m, 11), "Kafe")

                # Transfer to savings
                add_tx("transfer", rng.randint(900000, 1400000), accounts["Asosiy karta"], None, month_date(m, 28), "Jamg'armaga o'tkazma", to_account=accounts["Jamg'arma"])

                # USD activity
                add_tx("income", rng.randint(150, 260), accounts["USD karta"], categories["Sovg'a"], month_date(m, 13), "USD tushum")
                add_tx("expense", rng.randint(70, 140), accounts["USD karta"], categories["Transport"], month_date(m, 18), "USD xarajat")

            # Budgets for current month
            cur_month = today.month
            cur_year = today.year
            Budget.objects.create(user=user, name="Oziq-ovqat limiti", category=categories["Oziq-ovqat"], budget_type="expense", amount=Decimal("3000000"), currency="UZS", month=cur_month, year=cur_year)
            Budget.objects.create(user=user, name="Transport limiti", category=categories["Transport"], budget_type="expense", amount=Decimal("1200000"), currency="UZS", month=cur_month, year=cur_year)
            Budget.objects.create(user=user, name="Ijara limiti", category=categories["Ijara"], budget_type="expense", amount=Decimal("2800000"), currency="UZS", month=cur_month, year=cur_year)

            # Debts
            debt1 = Debt.objects.create(
                user=user,
                debt_type="given",
                person_name="Azizbek",
                person_phone="+998 90 222 11 00",
                amount=Decimal("2000000"),
                currency="UZS",
                account=accounts["Asosiy karta"],
                description="Qarz (do'st)",
                date=today - timedelta(days=20),
                due_date=today + timedelta(days=25),
                status="open",
            )
            debt2 = Debt.objects.create(
                user=user,
                debt_type="taken",
                person_name="Dilnoza",
                person_phone="+998 90 555 00 11",
                amount=Decimal("1500000"),
                currency="UZS",
                account=accounts["Naqd pul"],
                description="Qarz (oilaviy)",
                date=today - timedelta(days=40),
                due_date=today + timedelta(days=10),
                status="partial",
            )
            DebtPayment.objects.create(debt=debt2, amount=Decimal("500000"), date=today - timedelta(days=5), notes="Qisman qaytarildi")

            # Notifications
            demo_threshold = 300000
            Notification.objects.create(
                user=user,
                notif_type="low_balance",
                title=f"Past balans: {accounts['Naqd pul'].name}",
                message=f"Balans {int(accounts['Naqd pul'].balance):,} UZS. Limit: {demo_threshold:,} UZS.",
                level="warning",
                data={
                    "account": accounts["Naqd pul"].name,
                    "balance": int(accounts["Naqd pul"].balance),
                    "threshold": int(demo_threshold),
                },
            )

            demo_budget_name = "Oziq-ovqat limiti"
            demo_limit = 3000000
            demo_spent = int(demo_limit * 0.82)
            Notification.objects.create(
                user=user,
                notif_type="budget_exceeded",
                title=f"Byudjet oshdi: {demo_budget_name}",
                message=f"{demo_budget_name} byudjeti 82% ga yetdi. Sarflangan: {demo_spent:,} UZS, limit: {demo_limit:,} UZS.",
                level="info",
                data={
                    "category": demo_budget_name,
                    "percent": 82,
                    "spent": demo_spent,
                    "limit": demo_limit,
                    "month": f"{today.year}-{today.month:02d}",
                },
            )

            days_left = max(0, (debt1.due_date - today).days) if debt1.due_date else 0
            Notification.objects.create(
                user=user,
                notif_type="debt_due",
                title="Qarz muddati yaqin",
                message=f"{debt1.person_name} bo'yicha qarz muddati {days_left} kun qoldi.",
                level="danger",
                data={
                    "person": debt1.person_name,
                    "days_left": days_left,
                    "due_date": debt1.due_date.isoformat() if debt1.due_date else "",
                },
            )

            # Family demo (optional)
            if with_family:
                family, _ = FamilyGroup.objects.get_or_create(name="Demo Oila", created_by=user)
                FamilyMember.objects.get_or_create(family=family, user=user, role="father")

                fam_acc = Account.objects.create(
                    user=user,
                    family=family,
                    name="Oila karta",
                    account_type="card",
                    currency="UZS",
                    initial_balance=Decimal("5000000"),
                    balance=Decimal("5000000"),
                    color="#8b5cf6",
                    icon="users",
                )
                fam_cat = Category.objects.create(
                    family=family,
                    name="Oila xarajatlari",
                    category_type="expense",
                    icon="users",
                    color="#8b5cf6",
                )
                Transaction.objects.create(
                    user=user,
                    family=family,
                    transaction_type="expense",
                    amount=Decimal("450000"),
                    account=fam_acc,
                    category=fam_cat,
                    description="Oila xarajatlari",
                    date=today - timedelta(days=6),
                )
                Transaction.objects.create(
                    user=user,
                    family=family,
                    transaction_type="income",
                    amount=Decimal("1200000"),
                    account=fam_acc,
                    description="Oila daromadi",
                    date=today - timedelta(days=12),
                )

        self.stdout.write(self.style.SUCCESS(f"Demo data ready for user '{username}'."))
