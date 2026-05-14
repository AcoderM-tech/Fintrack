from decimal import Decimal
from datetime import date
import calendar

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts_app.models import Account
from transactions.models import Transaction, Category
from budgets.models import Budget
from debts.models import Debt, DebtPayment


def get_or_none(qs):
    try:
        return qs.first()
    except Exception:
        return None


def run():
    User = get_user_model()
    account = get_or_none(Account.objects.filter(is_active=True).order_by("id"))
    if not account:
        print("No active account found. Aborting.")
        return
    user = account.user

    if Transaction.objects.filter(user=user, description__startswith="Seed:").exists():
        print("Seed data already exists. Skipping.")
        return

    def cat(name):
        return (
            Category.objects.filter(user=user, name=name).first()
            or Category.objects.filter(name=name, is_default=True).first()
        )

    today = timezone.now().date()
    current_year = today.year
    current_month = today.month

    months = []
    for i in range(5, -1, -1):
        m = current_month - i
        y = current_year
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))

    # Monthly seed transactions
    for y, m in months:
        last_day = calendar.monthrange(y, m)[1]
        salary_day = min(5, last_day)
        food_day = min(10, last_day)
        transport_day = min(12, last_day)
        utilities_day = min(15, last_day)
        fun_day = min(20, last_day)
        phone_day = min(22, last_day)

        Transaction.objects.create(
            user=user,
            transaction_type="income",
            amount=Decimal("2500000"),
            currency=account.currency,
            account=account,
            category=cat("Maosh"),
            description=f"Seed: Maosh {y}-{m:02d}",
            date=date(y, m, salary_day),
            notes="Demo income",
        )

        Transaction.objects.create(
            user=user,
            transaction_type="expense",
            amount=Decimal("700000"),
            currency=account.currency,
            account=account,
            category=cat("Oziq-ovqat"),
            description=f"Seed: Oziq-ovqat {y}-{m:02d}",
            date=date(y, m, food_day),
            notes="Demo expense",
        )

        Transaction.objects.create(
            user=user,
            transaction_type="expense",
            amount=Decimal("200000"),
            currency=account.currency,
            account=account,
            category=cat("Transport"),
            description=f"Seed: Transport {y}-{m:02d}",
            date=date(y, m, transport_day),
            notes="Demo expense",
        )

        Transaction.objects.create(
            user=user,
            transaction_type="expense",
            amount=Decimal("150000"),
            currency=account.currency,
            account=account,
            category=cat("Kommunal"),
            description=f"Seed: Kommunal {y}-{m:02d}",
            date=date(y, m, utilities_day),
            notes="Demo expense",
        )

        Transaction.objects.create(
            user=user,
            transaction_type="expense",
            amount=Decimal("120000"),
            currency=account.currency,
            account=account,
            category=cat("Ko'ngilochar"),
            description=f"Seed: Ko'ngilochar {y}-{m:02d}",
            date=date(y, m, fun_day),
            notes="Demo expense",
        )

        Transaction.objects.create(
            user=user,
            transaction_type="expense",
            amount=Decimal("80000"),
            currency=account.currency,
            account=account,
            category=cat("Internet/Telefon"),
            description=f"Seed: Internet {y}-{m:02d}",
            date=date(y, m, phone_day),
            notes="Demo expense",
        )

    # Budgets for current month
    Budget.objects.bulk_create([
        Budget(user=user, category=cat("Oziq-ovqat"), name="Oziq-ovqat", budget_type="expense", amount=Decimal("900000"), currency=account.currency, month=current_month, year=current_year),
        Budget(user=user, category=cat("Transport"), name="Transport", budget_type="expense", amount=Decimal("250000"), currency=account.currency, month=current_month, year=current_year),
        Budget(user=user, category=cat("Kommunal"), name="Kommunal", budget_type="expense", amount=Decimal("200000"), currency=account.currency, month=current_month, year=current_year),
        Budget(user=user, category=cat("Ko'ngilochar"), name="Ko'ngilochar", budget_type="expense", amount=Decimal("180000"), currency=account.currency, month=current_month, year=current_year),
    ])

    # Debts + payments
    given = Debt.objects.create(
        user=user,
        debt_type="given",
        person_name="Azizbek",
        person_phone="+998901112233",
        amount=Decimal("1000000"),
        currency=account.currency,
        paid_amount=Decimal("0"),
        account=account,
        description="Seed: Qarzdor",
        date=today.replace(day=max(1, today.day - 10)),
        due_date=today.replace(day=min(28, today.day + 20)),
    )
    DebtPayment.objects.create(
        debt=given,
        amount=Decimal("200000"),
        date=today.replace(day=max(1, today.day - 2)),
        notes="Seed: Qisman to'lov",
    )

    Debt.objects.create(
        user=user,
        debt_type="taken",
        person_name="Dilshod",
        person_phone="+998907774455",
        amount=Decimal("500000"),
        currency=account.currency,
        paid_amount=Decimal("0"),
        account=account,
        description="Seed: Qarzdorlik",
        date=today.replace(day=max(1, today.day - 5)),
        due_date=today.replace(day=min(28, today.day + 30)),
    )

    print("Seed data created for user:", user.username)


run()
