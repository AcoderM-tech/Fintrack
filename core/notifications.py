from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from accounts_app.models import Account
from budgets.models import Budget
from debts.models import Debt
from transactions.models import Transaction
from core.models import Notification


def _notify(user, notif_type, title, message, level="info", key=None, data=None, related=None, dedupe_days=30, family=None):
    now = timezone.now()
    if key:
        qs = Notification.objects.filter(
            user=user, key=key, created_at__gte=now - timedelta(days=dedupe_days)
        )
        if family:
            qs = qs.filter(family=family)
        else:
            qs = qs.filter(family__isnull=True)
        exists = qs.exists()
        if exists:
            return None

    # Try AI message first, fallback to static if AI is unavailable
    try:
        from core.ai import generate_notification_message
        message = generate_notification_message(notif_type, data or {}, message)
    except Exception:
        pass

    kwargs = {
        "user": user,
        "family": family,
        "notif_type": notif_type,
        "title": title,
        "message": message,
        "level": level,
        "key": key or "",
        "data": data or None,
    }
    if related:
        kwargs["related_object_type"] = related.get("type", "")
        kwargs["related_object_id"] = related.get("id")
    return Notification.objects.create(**kwargs)


def check_budget_exceeded(tx):
    if tx.transaction_type != "expense" or not tx.category_id:
        return None

    month = tx.date.month
    year = tx.date.year
    if tx.family_id:
        budget = Budget.objects.filter(
            family=tx.family,
            month=month,
            year=year,
            budget_type="expense",
            category=tx.category,
        ).first()
    else:
        budget = Budget.objects.filter(
            user=tx.user,
            family__isnull=True,
            month=month,
            year=year,
            budget_type="expense",
            category=tx.category,
        ).first()
    if not budget:
        return None

    if tx.family_id:
        total = Transaction.objects.filter(
            family=tx.family,
            transaction_type="expense",
            category=tx.category,
            date__year=year,
            date__month=month,
        ).aggregate(total=Sum("amount"))["total"] or 0
    else:
        total = Transaction.objects.filter(
            user=tx.user,
            family__isnull=True,
            transaction_type="expense",
            category=tx.category,
            date__year=year,
            date__month=month,
        ).aggregate(total=Sum("amount"))["total"] or 0

    if total < budget.amount:
        return None

    pct = int((float(total) / float(budget.amount)) * 100) if budget.amount else 100
    level = "danger" if pct >= 110 else "warning"
    key = f"budget_exceeded:{budget.id}:{year}-{month}"
    return _notify(
        tx.user,
        "budget_exceeded",
        f"Byudjet oshdi: {budget.name}",
        f"{budget.name} byudjeti {pct}% ga yetdi. Sarflangan: {int(total):,} UZS, limit: {int(budget.amount):,} UZS.",
        level=level,
        key=key,
        related={"type": "budget", "id": budget.id},
        family=tx.family,
        data={
            "category": budget.name,
            "percent": pct,
            "spent": int(total),
            "limit": int(budget.amount),
            "month": f"{year}-{month:02d}",
        },
        dedupe_days=60,
    )


def check_spending_spike(tx, spike_ratio=1.4):
    if tx.transaction_type != "expense" or not tx.category_id:
        return None

    year = tx.date.year
    month = tx.date.month
    prev_month = month - 1
    prev_year = year
    if prev_month <= 0:
        prev_month = 12
        prev_year -= 1

    if tx.family_id:
        cur_total = Transaction.objects.filter(
            family=tx.family,
            transaction_type="expense",
            category=tx.category,
            date__year=year,
            date__month=month,
        ).aggregate(total=Sum("amount"))["total"] or 0
    else:
        cur_total = Transaction.objects.filter(
            user=tx.user,
            family__isnull=True,
            transaction_type="expense",
            category=tx.category,
            date__year=year,
            date__month=month,
        ).aggregate(total=Sum("amount"))["total"] or 0

    if tx.family_id:
        prev_total = Transaction.objects.filter(
            family=tx.family,
            transaction_type="expense",
            category=tx.category,
            date__year=prev_year,
            date__month=prev_month,
        ).aggregate(total=Sum("amount"))["total"] or 0
    else:
        prev_total = Transaction.objects.filter(
            user=tx.user,
            family__isnull=True,
            transaction_type="expense",
            category=tx.category,
            date__year=prev_year,
            date__month=prev_month,
        ).aggregate(total=Sum("amount"))["total"] or 0

    if prev_total <= 0:
        return None

    if float(cur_total) <= float(prev_total) * spike_ratio:
        return None

    pct = int(((float(cur_total) - float(prev_total)) / float(prev_total)) * 100)
    key = f"spike:{tx.category_id}:{year}-{month}"
    return _notify(
        tx.user,
        "spending_spike",
        f"Xarajat keskin oshdi: {tx.category.name}",
        f"{tx.category.name} xarajatlari o'tgan oyga nisbatan {pct}% ko'paydi.",
        level="warning",
        key=key,
        related={"type": "category", "id": tx.category_id},
        family=tx.family,
        data={
            "category": tx.category.name,
            "percent": pct,
            "month": f"{year}-{month:02d}",
        },
        dedupe_days=45,
    )


def check_low_balance(account: Account):
    if not account or account.low_balance_threshold <= 0:
        return None
    if account.balance > account.low_balance_threshold:
        return None

    key = f"low_balance:{account.id}:{timezone.now().date()}"
    return _notify(
        account.user,
        "low_balance",
        f"Past balans: {account.name}",
        f"Balans {int(account.balance):,} UZS. Limit: {int(account.low_balance_threshold):,} UZS.",
        level="danger",
        key=key,
        related={"type": "account", "id": account.id},
        family=account.family,
        data={
            "account": account.name,
            "balance": int(account.balance),
            "threshold": int(account.low_balance_threshold),
        },
        dedupe_days=1,
    )


def check_debt_due(debt: Debt, days_before=7):
    if not debt or not debt.due_date:
        return None
    if debt.status not in ("open", "partial"):
        return None
    today = timezone.now().date()
    days_left = (debt.due_date - today).days
    if days_left < 0 or days_left > days_before:
        return None

    key = f"debt_due:{debt.id}:{debt.due_date.isoformat()}"
    return _notify(
        debt.user,
        "debt_due",
        "Qarz muddati yaqin",
        f"{debt.person_name} bo'yicha qarz muddati {days_left} kun qoldi.",
        level="warning",
        key=key,
        related={"type": "debt", "id": debt.id},
        family=debt.family,
        data={
            "person": debt.person_name,
            "days_left": days_left,
            "due_date": debt.due_date.isoformat(),
        },
        dedupe_days=30,
    )


def handle_transaction_notifications(tx):
    if not tx:
        return
    check_budget_exceeded(tx)
    check_spending_spike(tx)
    if tx.account_id:
        check_low_balance(tx.account)
    if tx.to_account_id:
        check_low_balance(tx.to_account)


def refresh_debt_due_notifications(user, days_before=7, family=None, role=None):
    today = timezone.now().date()
    if family:
        debts = Debt.objects.filter(
            family=family,
            status__in=["open", "partial"],
            due_date__isnull=False,
            due_date__gte=today,
            due_date__lte=today + timedelta(days=days_before),
        )
    else:
        debts = Debt.objects.filter(
            user=user,
            family__isnull=True,
            status__in=["open", "partial"],
            due_date__isnull=False,
            due_date__gte=today,
            due_date__lte=today + timedelta(days=days_before),
        )
    for d in debts:
        check_debt_due(d, days_before=days_before)


def refresh_low_balance_notifications(user, family=None, role=None):
    if family:
        qs = Account.objects.filter(family=family, is_active=True)
    else:
        qs = Account.objects.filter(user=user, family__isnull=True, is_active=True)
    for acc in qs:
        check_low_balance(acc)
