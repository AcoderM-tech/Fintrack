from core.i18n import translate as _i18n_translate, get_request_lang, translate_category as _i18n_translate_cat
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, Case, When, DecimalField, IntegerField
from django.http import JsonResponse
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from .models import Transaction, Category
from accounts_app.models import Account
from core.ai import get_ai_tips, get_ai_source, auto_assign_category
from core.i18n import get_request_lang, format_month_year
from core.family_utils import (
    get_active_family,
    get_family_role,
    handle_scope_param,
    scope_queryset,
    categories_queryset,
    accounts_queryset,
    can_manage_family_finance,
)
import json
import urllib.request
import urllib.error


@login_required
def transaction_list(request):
    lang = get_request_lang(request)
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    transactions = scope_queryset(
        Transaction.objects.select_related('category', 'account', 'to_account'),
        user=user,
        family=family,
        role=role,
    )

    # Filtrlar
    t_type = request.GET.get('type', '')
    category_id = request.GET.get('category', '')
    account_id = request.GET.get('account', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search = request.GET.get('search', '')

    if t_type:
        transactions = transactions.filter(transaction_type=t_type)
    if category_id:
        transactions = transactions.filter(category_id=category_id)
    if account_id:
        transactions = transactions.filter(Q(account_id=account_id) | Q(to_account_id=account_id))
    if date_from:
        transactions = transactions.filter(date__gte=date_from)
    if date_to:
        transactions = transactions.filter(date__lte=date_to)
    if search:
        transactions = transactions.filter(description__icontains=search)

    summary_qs = transactions
    summary = summary_qs.aggregate(
        total_expense=Sum(
            Case(
                When(transaction_type='expense', then='amount'),
                default=Decimal('0'),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        ),
        total_income=Sum(
            Case(
                When(transaction_type='income', then='amount'),
                default=Decimal('0'),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )
        ),
        expense_count=Sum(
            Case(
                When(transaction_type='expense', then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
        income_count=Sum(
            Case(
                When(transaction_type='income', then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
    )
    total_expense = summary.get('total_expense') or 0
    total_income = summary.get('total_income') or 0
    expense_count = summary.get('expense_count') or 0
    income_count = summary.get('income_count') or 0
    avg_expense = int(float(total_expense) / expense_count) if expense_count else 0
    avg_income = int(float(total_income) / income_count) if income_count else 0
    top_cat = summary_qs.filter(transaction_type='expense').values('category__name').annotate(
        total=Sum('amount')
    ).order_by('-total').first()

    ai_tips = get_ai_tips(request, "transactions", {
        'count': summary_qs.count(),
        'total_expense': int(total_expense),
        'total_income': int(total_income),
        'top_category': _i18n_translate_cat((top_cat or {}).get('category__name') or '', lang),
        'expense_count': expense_count,
        'income_count': income_count,
        'avg_expense': avg_expense,
        'avg_income': avg_income,
    }, max_items=3)
    ai_source = get_ai_source(request, "transactions")

    # Pagination — 25 per page (replaces the old [:100] hard limit)
    from django.core.paginator import Paginator
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    transactions = page_obj

    categories = categories_queryset(user, family=family, role=role)
    accounts = accounts_queryset(user, family=family, role=role)

    return render(request, 'transactions/list.html', {
        'transactions': transactions,
        'page_obj': page_obj,
        'paginator': paginator,
        'categories': categories,
        'accounts': accounts,
        'filters': {
            'type': t_type, 'category': category_id,
            'account': account_id, 'date_from': date_from,
            'date_to': date_to, 'search': search,
        },
        'ai_tips': ai_tips,
        'ai_source': ai_source,
        'ai_topic': 'transactions',
    })


@login_required
def transaction_create(request):
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate('Oilaviy tranzaksiyalarni faqat Ota/Ona boshqarishi mumkin.', get_request_lang(request)))
        return redirect('transaction_list')

    accounts = accounts_queryset(user, family=family, role=role)
    categories = categories_queryset(user, family=family, role=role)
    t_type = request.GET.get('type', 'expense')

    if request.method == 'POST':
        t_type = request.POST.get('transaction_type', 'expense')
        amount = request.POST.get('amount', 0)
        account_id = request.POST.get('account')
        to_account_id = request.POST.get('to_account', '')
        category_id = request.POST.get('category', '')
        description = request.POST.get('description', '')
        date = request.POST.get('date', timezone.now().date())
        exchange_rate = request.POST.get('exchange_rate', 1)
        converted_amount = request.POST.get('converted_amount', '')
        notes = request.POST.get('notes', '')

        if family:
            account = get_object_or_404(Account, pk=account_id, family=family) if account_id else None
            to_account = Account.objects.filter(pk=to_account_id, family=family).first() if to_account_id else None
            category = Category.objects.filter(
                Q(family=family) | Q(is_default=True),
                pk=category_id
            ).first() if category_id else None
        else:
            account = get_object_or_404(Account, pk=account_id, user=user, family__isnull=True) if account_id else None
            to_account = Account.objects.filter(pk=to_account_id, user=user, family__isnull=True).first() if to_account_id else None
            category = Category.objects.filter(
                Q(user=user) | Q(is_default=True),
                family__isnull=True,
                pk=category_id
            ).first() if category_id else None

        tx = Transaction(
            user=user,
            family=family,
            transaction_type=t_type,
            amount=Decimal(str(amount or 0)),
            currency=account.currency if account else 'UZS',
            account=account,
            to_account=to_account,
            category=category,
            description=description,
            date=date,
            exchange_rate=Decimal(str(exchange_rate or 1)),
            converted_amount=Decimal(str(converted_amount)) if converted_amount not in (None, '') else None,
            notes=notes,
        )
        try:
            tx.save()
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, msg)
            return render(request, 'transactions/form.html', {
                'title': 'Yangi tranzaksiya',
                'accounts': accounts,
                'categories': categories,
                'transaction': tx,
                'default_type': t_type,
                'today': timezone.now().date().isoformat(),
            })
        else:
            messages.success(request, _i18n_translate("Tranzaksiya muvaffaqiyatli qo'shildi!", get_request_lang(request)))
            return redirect('transaction_list')

    return render(request, 'transactions/form.html', {
        'title': 'Yangi tranzaksiya',
        'accounts': accounts,
        'categories': categories,
        'transaction': None,
        'default_type': t_type,
        'today': timezone.now().date().isoformat(),
    })


@login_required
def transaction_edit(request, pk):
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate('Oilaviy tranzaksiyalarni faqat Ota/Ona tahrirlashi mumkin.', get_request_lang(request)))
        return redirect('transaction_list')

    if family:
        transaction = get_object_or_404(Transaction, pk=pk, family=family)
    else:
        transaction = get_object_or_404(Transaction, pk=pk, user=user, family__isnull=True)

    if request.method == 'POST':
        t_type = request.POST.get('transaction_type')
        amount = request.POST.get('amount', 0)
        account_id = request.POST.get('account')
        to_account_id = request.POST.get('to_account', '')
        category_id = request.POST.get('category', '')

        if family:
            new_account = Account.objects.filter(pk=account_id, family=family).first()
            new_to_account = Account.objects.filter(pk=to_account_id, family=family).first() if to_account_id else None
        else:
            new_account = Account.objects.filter(pk=account_id, user=user, family__isnull=True).first()
            new_to_account = Account.objects.filter(pk=to_account_id, user=user, family__isnull=True).first() if to_account_id else None

        transaction.transaction_type = t_type
        transaction.amount = Decimal(str(amount or 0))
        transaction.account = new_account
        transaction.to_account = new_to_account
        if family:
            category = Category.objects.filter(
                Q(family=family) | Q(is_default=True),
                pk=category_id
            ).first() if category_id else None
        else:
            category = Category.objects.filter(
                Q(user=user) | Q(is_default=True),
                family__isnull=True,
                pk=category_id
            ).first() if category_id else None
        transaction.category = category
        transaction.description = request.POST.get('description', '')
        transaction.date = request.POST.get('date')
        transaction.exchange_rate = Decimal(str(request.POST.get('exchange_rate', 1) or 1))
        conv = request.POST.get('converted_amount') or None
        transaction.converted_amount = Decimal(str(conv)) if conv not in (None, '') else None
        transaction.notes = request.POST.get('notes', '')
        try:
            transaction.save()
        except ValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, msg)
        else:
            messages.success(request, _i18n_translate('Tranzaksiya yangilandi!', get_request_lang(request)))
            return redirect('transaction_list')

    accounts = accounts_queryset(user, family=family, role=role)
    categories = categories_queryset(user, family=family, role=role)

    return render(request, 'transactions/form.html', {
        'title': 'Tranzaksiyani tahrirlash',
        'transaction': transaction,
        'accounts': accounts,
        'categories': categories,
        'default_type': transaction.transaction_type,
        'today': timezone.now().date().isoformat(),
    })


@login_required
def transaction_delete(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate("Oilaviy tranzaksiyalarni faqat Ota/Ona o'chirishi mumkin.", get_request_lang(request)))
        return redirect('transaction_list')

    if family:
        transaction = get_object_or_404(Transaction, pk=pk, family=family)
    else:
        transaction = get_object_or_404(Transaction, pk=pk, user=request.user, family__isnull=True)
    if request.method == 'POST':
        transaction.delete()
        messages.success(request, _i18n_translate("Tranzaksiya o'chirildi!", get_request_lang(request)))
    return redirect('transaction_list')


@login_required
def calendar_view(request):
    """Kalendar ko'rinish"""
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    lang = get_request_lang(request)
    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))

    transactions = scope_queryset(
        Transaction.objects.filter(
            date__year=year,
            date__month=month
        ).select_related('category'),
        user=user,
        family=family,
        role=role,
    )

    # Kunlar bo'yicha guruhlash (yengil server-side kalendar uchun)
    days_data = {}
    for t in transactions:
        day = t.date.day
        if day not in days_data:
            days_data[day] = {'expense': 0, 'income': 0}
        if t.transaction_type == 'expense':
            days_data[day]['expense'] += float(t.amount)
        elif t.transaction_type == 'income':
            days_data[day]['income'] += float(t.amount)

    import calendar
    cal = calendar.monthcalendar(year, month)

    transactions_data = []
    for t in transactions:
        transactions_data.append({
            'id': t.id,
            'date': t.date.isoformat(),
            'type': t.transaction_type,
            'amount': float(t.amount),
            'currency': t.currency,
            'description': t.description or '',
            'category': _i18n_translate_cat(t.category.name, lang) if t.category else '',
            'account': t.account.name if t.account else '',
        })
    context = {
        'calendar': cal,
        'days_data': days_data,
        'transactions_data': transactions_data,
        'year': year,
        'month': month,
        'month_name': format_month_year(year, month, lang),
        'today': today,
        'prev_month': (month - 1) if month > 1 else 12,
        'prev_year': year if month > 1 else year - 1,
        'next_month': (month + 1) if month < 12 else 1,
        'next_year': year if month < 12 else year + 1,
    }
    return render(request, 'transactions/calendar.html', context)


@login_required
def api_suggest_category(request):
    """AI: tavsif asosida kategoriya taklif qilish"""
    handle_scope_param(request)
    description = request.GET.get('desc', '').strip()
    t_type = request.GET.get('type', 'expense')
    user = request.user
    family = get_active_family(request)

    if t_type != 'expense' or not description:
        return JsonResponse({'suggested': None})

    auto_cat = auto_assign_category(user, description, family=family)
    if auto_cat:
        return JsonResponse({'suggested': {'id': auto_cat.id, 'name': auto_cat.name, 'icon': auto_cat.icon}})

    if family:
        categories_qs = Category.objects.filter(Q(family=family) | Q(is_default=True))
    else:
        categories_qs = Category.objects.filter(Q(user=user) | Q(is_default=True), family__isnull=True)
    if t_type in ('expense', 'income'):
        categories_qs = categories_qs.filter(Q(category_type=t_type) | Q(category_type='both'))

    categories = list(categories_qs)
    categories_by_name = {c.name.lower(): c for c in categories}

    # Rule-based kategoriya aniqlash
    rules = {
        'oziq': ['oziq', 'ovqat', 'dokon', 'bozor', 'non', 'go\'sht', 'sabzavot', 'supermarket'],
        'transport': ['taksi', 'avtobus', 'metro', 'benzin', 'yoqilg\'i', 'mashina', 'transport'],
        'kommunal': ['gaz', 'suv', 'elektr', 'kommunal', 'uy to\'lov'],
        'salomatlik': ['dori', 'dorixona', 'shifoxona', 'klinika', 'doctor', 'shifokor'],
        'ta\'lim': ['kurs', 'dars', 'kitob', 'talim', 'maktab', 'universitet'],
        'ko\'ngilochar': ['kino', 'restoran', 'cafe', 'kafé', 'o\'yin', 'dam'],
        'internet': ['internet', 'telefon', 'sim', 'uzum', 'beeline'],
    }

    category_map = {
        'oziq': 'Oziq-ovqat',
        'transport': 'Transport',
        'kommunal': 'Kommunal',
        'salomatlik': 'Salomatlik',
        'ta\'lim': 'Ta\'lim',
        'ko\'ngilochar': 'Ko\'ngilochar',
        'internet': 'Internet/Telefon',
    }

    suggested = None
    desc_lower = description.lower()
    for key, keywords in rules.items():
        if any(kw in desc_lower for kw in keywords):
            cat_name = category_map.get(key, '').lower()
            cat = categories_by_name.get(cat_name)
            if cat:
                suggested = {'id': cat.id, 'name': cat.name, 'icon': cat.icon}
            break

    if not suggested and description and settings.GEMINI_API_KEY:
        cat_name = _gemini_category_name(description, [c.name for c in categories])
        if cat_name:
            cat = categories_by_name.get(cat_name.lower())
            if cat:
                suggested = {'id': cat.id, 'name': cat.name, 'icon': cat.icon}

    return JsonResponse({'suggested': suggested})


def _gemini_category_name(description, category_names):
    """Gemini API orqali kategoriya nomini tanlash."""
    if not category_names or not settings.GEMINI_API_KEY:
        return None

    prompt = (
        "You categorize personal finance transactions.\n"
        f"Description: {description}\n"
        "Choose exactly one category name from this list. "
        "If none fits, return NONE.\n"
        "Categories:\n- " + "\n- ".join(category_names)
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 20},
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent"
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": settings.GEMINI_API_KEY,
    }

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return None

    text = (
        body.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
        .strip()
    )
    if not text:
        return None

    first_line = text.splitlines()[0].strip().strip('"')
    if first_line.upper() == "NONE":
        return None

    for name in category_names:
        if first_line.lower() == name.lower():
            return name
    return None
