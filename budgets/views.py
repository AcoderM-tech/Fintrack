from core.i18n import translate as _i18n_translate, get_request_lang
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum
from .models import Budget
from transactions.models import Category, Transaction
from core.ai import get_ai_tips, get_ai_source
from core.i18n import translate as _i18n_translate, get_request_lang, format_month_year
from core.family_utils import (
    get_active_family,
    get_family_role,
    handle_scope_param,
    scope_queryset,
    categories_queryset,
    can_manage_family_finance,
)


@login_required
def budget_list(request):
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    today = timezone.now().date()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))

    budgets = scope_queryset(
        Budget.objects.filter(month=month, year=year).select_related('category'),
        user=user,
        family=family,
        role=role,
    )

    tx_base = scope_queryset(
        Transaction.objects.filter(date__month=month, date__year=year),
        user=user,
        family=family,
        role=role,
    )
    agg_rows = tx_base.values('category_id', 'transaction_type').annotate(total=Sum('amount'))
    cat_totals = {
        (row['category_id'], row['transaction_type']): row['total'] or 0
        for row in agg_rows
    }
    type_totals = {
        row['transaction_type']: row['total'] or 0
        for row in tx_base.values('transaction_type').annotate(total=Sum('amount'))
    }

    budget_data = []
    for b in budgets:
        if b.budget_type == 'expense':
            actual = cat_totals.get((b.category_id, 'expense'), 0) if b.category_id else type_totals.get('expense', 0)
        else:
            actual = cat_totals.get((b.category_id, 'income'), 0) if b.category_id else type_totals.get('income', 0)
        if b.amount:
            percentage = min(int((actual / b.amount) * 100), 100)
        else:
            percentage = 0
        remaining = b.amount - actual
        budget_data.append({
            'budget': b,
            'actual': actual,
            'remaining': remaining,
            'percentage': percentage,
        })

    categories = categories_queryset(user, family=family, role=role)

    lang = get_request_lang(request)
    month_name = format_month_year(year, month, lang)
    month_prompt_tpl = _i18n_translate("{month} uchun byudjet yarating", lang)
    try:
        month_prompt = month_prompt_tpl.format(month=month_name)
    except Exception:
        month_prompt = f"{month_name} {month_prompt_tpl}"

    count = len(budget_data)
    near_limit = sum(1 for item in budget_data if item['percentage'] >= 75 and item['budget'].budget_type == 'expense')
    over_limit = sum(1 for item in budget_data if item['percentage'] >= 100 and item['budget'].budget_type == 'expense')
    total_planned = sum(float(item['budget'].amount) for item in budget_data)
    total_actual = sum(float(item['actual']) for item in budget_data)
    avg_pct = int(sum(item['percentage'] for item in budget_data) / count) if count else 0
    max_pct = max((item['percentage'] for item in budget_data), default=0)

    ai_tips = get_ai_tips(request, "budgets", {
        'count': count,
        'near_limit': near_limit,
        'over_limit': over_limit,
        'total_planned': int(total_planned),
        'total_actual': int(total_actual),
        'avg_pct': avg_pct,
        'max_pct': int(max_pct),
    }, max_items=3)
    ai_source = get_ai_source(request, "budgets")

    context = {
        'budget_data': budget_data,
        'categories': categories,
        'month': month,
        'year': year,
        'month_name': month_name,
        'month_prompt': month_prompt,
        'prev_month': (month - 1) if month > 1 else 12,
        'prev_year': year if month > 1 else year - 1,
        'next_month': (month + 1) if month < 12 else 1,
        'next_year': year if month < 12 else year + 1,
        'ai_tips': ai_tips,
        'ai_source': ai_source,
        'ai_topic': 'budgets',
    }
    return render(request, 'budgets/list.html', context)


@login_required
def budget_create(request):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate('Oilaviy byudjetni faqat Ota/Ona boshqarishi mumkin.', get_request_lang(request)))
        return redirect('budget_list')

    if request.method == 'POST':
        user = request.user
        category_id = request.POST.get('category', '')
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

        Budget.objects.create(
            user=user,
            family=family,
            name=request.POST.get('name'),
            category=category,
            budget_type=request.POST.get('budget_type', 'expense'),
            amount=request.POST.get('amount'),
            currency=request.POST.get('currency', 'UZS'),
            month=request.POST.get('month'),
            year=request.POST.get('year'),
        )
        messages.success(request, _i18n_translate('Byudjet muvaffaqiyatli yaratildi!', get_request_lang(request)))
        return redirect('budget_list')

    today = timezone.now().date()
    categories = categories_queryset(request.user, family=family, role=role)

    return render(request, 'budgets/form.html', {
        'categories': categories,
        'today': today,
    })


@login_required
def budget_delete(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate("Oilaviy byudjetni faqat Ota/Ona o'chirishi mumkin.", get_request_lang(request)))
        return redirect('budget_list')

    if family:
        budget = get_object_or_404(Budget, pk=pk, family=family)
    else:
        budget = get_object_or_404(Budget, pk=pk, user=request.user, family__isnull=True)
    if request.method == 'POST':
        budget.delete()
        messages.success(request, _i18n_translate("Byudjet o'chirildi!", get_request_lang(request)))
    return redirect('budget_list')
