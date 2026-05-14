from core.i18n import translate as _i18n_translate, get_request_lang
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Account
from core.i18n import translate as _i18n_translate, get_request_lang
from core.family_utils import (
    get_active_family,
    get_family_role,
    accounts_queryset,
    handle_scope_param,
    can_manage_family_finance,
)
import json
import re


def _localized_choices(choices, lang):
    return [(value, _i18n_translate(label, lang)) for value, label in choices]

def _normalize_card_number(raw):
    digits = re.sub(r"\D", "", raw or "")
    digits = digits[:16]
    if not digits:
        return ""
    return " ".join(digits[i:i+4] for i in range(0, len(digits), 4))


@login_required
def account_list(request):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    accounts = accounts_queryset(request.user, family=family, role=role)
    
    rates = {'UZS': 1, 'USD': 12700, 'EUR': 13800, 'RUB': 140}
    total_balance = sum(
        float(acc.balance) * rates.get(acc.currency, 1)
        for acc in accounts if acc.include_in_total
    )
    
    return render(request, 'accounts_app/list.html', {
        'accounts': accounts,
        'total_balance': total_balance,
    })


@login_required
def account_create(request):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    lang = get_request_lang(request)
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate('Oilaviy hisoblarni faqat Ota/Ona boshqarishi mumkin.', get_request_lang(request)))
        return redirect('account_list')

    if request.method == 'POST':
        card_number = _normalize_card_number(request.POST.get('card_number', ''))
        Account.objects.create(
            user=request.user,
            family=family,
            name=request.POST.get('name'),
            account_type=request.POST.get('account_type', 'card'),
            currency=request.POST.get('currency', 'UZS'),
            balance=request.POST.get('balance', 0),
            initial_balance=request.POST.get('balance', 0),
            color=request.POST.get('color', '#6366f1'),
            icon=request.POST.get('icon', 'credit-card'),
            card_number=card_number,
            description=request.POST.get('description', ''),
        )
        messages.success(request, _i18n_translate("Hisob raqam muvaffaqiyatli qo'shildi!", get_request_lang(request)))
        return redirect('account_list')
    
    return render(request, 'accounts_app/form.html', {
        'title': _i18n_translate('Yangi hisob raqam', get_request_lang(request)),
        'account': None,
        'account_types': _localized_choices(Account.ACCOUNT_TYPES, lang),
        'currency_choices': _localized_choices(Account.CURRENCY_CHOICES, lang),
        'color_choices': _localized_choices(Account.COLOR_CHOICES, lang),
    })


@login_required
def account_edit(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    lang = get_request_lang(request)
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate('Oilaviy hisoblarni faqat Ota/Ona tahrirlashi mumkin.', get_request_lang(request)))
        return redirect('account_list')

    if family:
        account = get_object_or_404(Account, pk=pk, family=family)
    else:
        account = get_object_or_404(Account, pk=pk, user=request.user, family__isnull=True)
    
    if request.method == 'POST':
        account.name = request.POST.get('name')
        account.account_type = request.POST.get('account_type')
        account.currency = request.POST.get('currency')
        account.color = request.POST.get('color', '#6366f1')
        account.icon = request.POST.get('icon', 'credit-card')
        account.card_number = _normalize_card_number(request.POST.get('card_number', ''))
        account.description = request.POST.get('description', '')
        account.include_in_total = 'include_in_total' in request.POST
        account.save()
        messages.success(request, _i18n_translate('Hisob raqam yangilandi!', get_request_lang(request)))
        return redirect('account_list')
    
    return render(request, 'accounts_app/form.html', {
        'title': _i18n_translate('Hisob raqamni tahrirlash', get_request_lang(request)),
        'account': account,
        'account_types': _localized_choices(Account.ACCOUNT_TYPES, lang),
        'currency_choices': _localized_choices(Account.CURRENCY_CHOICES, lang),
        'color_choices': _localized_choices(Account.COLOR_CHOICES, lang),
    })


@login_required
def account_delete(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate("Oilaviy hisoblarni faqat Ota/Ona o'chirishi mumkin.", get_request_lang(request)))
        return redirect('account_list')

    if family:
        account = get_object_or_404(Account, pk=pk, family=family)
    else:
        account = get_object_or_404(Account, pk=pk, user=request.user, family__isnull=True)
    if request.method == 'POST':
        account.is_active = False
        account.save()
        messages.success(request, _i18n_translate("Hisob raqam o'chirildi!", get_request_lang(request)))
    return redirect('account_list')


@login_required
def account_detail(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family:
        account = get_object_or_404(Account, pk=pk, family=family)
    else:
        account = get_object_or_404(Account, pk=pk, user=request.user, family__isnull=True)

    transactions = account.transactions.all().select_related('category')[:50]
    
    return render(request, 'accounts_app/detail.html', {
        'account': account,
        'transactions': transactions,
    })


@login_required
def api_accounts(request):
    """API: accountlar ro'yxati JSON formatda"""
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    accounts = accounts_queryset(request.user, family=family, role=role).values(
        'id', 'name', 'balance', 'currency', 'color', 'icon', 'account_type'
    )
    return JsonResponse({'accounts': list(accounts)})
