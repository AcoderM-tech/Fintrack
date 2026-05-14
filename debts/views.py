from core.i18n import translate as _i18n_translate, get_request_lang
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Debt, DebtPayment
from accounts_app.models import Account
from core.ai import get_ai_tips, get_ai_source
from core.family_utils import (
    get_active_family,
    get_family_role,
    handle_scope_param,
    scope_queryset,
    accounts_queryset,
    can_manage_family_finance,
)


@login_required
def debt_list(request):
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    debt_type = request.GET.get('type', '')

    debts = scope_queryset(
        Debt.objects.select_related('account', 'user').all(),
        user=user, family=family, role=role,
    )
    if debt_type:
        debts = debts.filter(debt_type=debt_type)

    given_debts = debts.filter(debt_type='given')
    taken_debts = debts.filter(debt_type='taken')

    total_given_open = sum(float(d.remaining_amount) for d in given_debts.filter(status__in=['open', 'partial']))
    total_taken_open = sum(float(d.remaining_amount) for d in taken_debts.filter(status__in=['open', 'partial']))

    today = timezone.now().date()
    overdue_given = given_debts.filter(status='open', due_date__lt=today).count()
    overdue_taken = taken_debts.filter(status='open', due_date__lt=today).count()
    given_count = given_debts.count()
    taken_count = taken_debts.count()
    net_debt = int(total_taken_open - total_given_open)

    ai_tips = get_ai_tips(request, "debts", {
        'total_given': int(total_given_open),
        'total_taken': int(total_taken_open),
        'overdue': overdue_given + overdue_taken,
        'given_count': given_count,
        'taken_count': taken_count,
        'net_debt': net_debt,
    }, max_items=3)
    ai_source = get_ai_source(request, "debts")

    return render(request, 'debts/list.html', {
        'given_debts': given_debts,
        'taken_debts': taken_debts,
        'total_given_open': total_given_open,
        'total_taken_open': total_taken_open,
        'ai_tips': ai_tips,
        'ai_source': ai_source,
        'ai_topic': 'debts',
    })


@login_required
def debt_create(request):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate('Oilaviy qarzlarni faqat Ota/Ona boshqarishi mumkin.', get_request_lang(request)))
        return redirect('debt_list')

    if request.method == 'POST':
        account_id = request.POST.get('account', '')
        if family:
            account = Account.objects.filter(pk=account_id, family=family).first() if account_id else None
        else:
            account = Account.objects.filter(pk=account_id, user=request.user, family__isnull=True).first() if account_id else None

        Debt.objects.create(
            user=request.user,
            family=family,
            debt_type=request.POST.get('debt_type'),
            person_name=request.POST.get('person_name'),
            person_phone=request.POST.get('person_phone', ''),
            amount=request.POST.get('amount'),
            currency=request.POST.get('currency', 'UZS'),
            account=account,
            description=request.POST.get('description', ''),
            date=request.POST.get('date'),
            due_date=request.POST.get('due_date') or None,
        )
        messages.success(request, _i18n_translate('Qarz muvaffaqiyatli qayd etildi!', get_request_lang(request)))
        return redirect('debt_list')

    accounts = accounts_queryset(request.user, family=family, role=role)
    return render(request, 'debts/form.html', {
        'accounts': accounts,
        'today': timezone.now().date().isoformat(),
    })


@login_required
def debt_payment(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate("Oilaviy to'lovlarni faqat Ota/Ona boshqarishi mumkin.", get_request_lang(request)))
        return redirect('debt_list')

    if family:
        debt = get_object_or_404(Debt, pk=pk, family=family)
    else:
        debt = get_object_or_404(Debt, pk=pk, user=request.user, family__isnull=True)

    if request.method == 'POST':
        amount = request.POST.get('amount')
        date = request.POST.get('date', timezone.now().date())
        notes = request.POST.get('notes', '')

        DebtPayment.objects.create(
            debt=debt,
            amount=amount,
            date=date,
            notes=notes,
        )
        messages.success(request, _i18n_translate("To'lov qayd etildi! Qolgan summa:", get_request_lang(request)) + f' {debt.remaining_amount} {debt.currency}')
        return redirect('debt_list')

    return render(request, 'debts/payment.html', {
        'debt': debt,
        'today': timezone.now().date().isoformat(),
    })


@login_required
def debt_close(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate('Oilaviy qarzni faqat Ota/Ona yopishi mumkin.', get_request_lang(request)))
        return redirect('debt_list')

    if family:
        debt = get_object_or_404(Debt, pk=pk, family=family)
    else:
        debt = get_object_or_404(Debt, pk=pk, user=request.user, family__isnull=True)
    if request.method == 'POST':
        debt.status = 'closed'
        debt.paid_amount = debt.amount
        debt.save()
        messages.success(request, _i18n_translate('Qarz yopiq deb belgilandi!', get_request_lang(request)))
    return redirect('debt_list')


@login_required
def debt_delete(request, pk):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    if family and not can_manage_family_finance(role, request.user, family):
        messages.error(request, _i18n_translate("Oilaviy qarzni faqat Ota/Ona o'chirishi mumkin.", get_request_lang(request)))
        return redirect('debt_list')

    if family:
        debt = get_object_or_404(Debt, pk=pk, family=family)
    else:
        debt = get_object_or_404(Debt, pk=pk, user=request.user, family__isnull=True)
    if request.method == 'POST':
        debt.delete()
        messages.success(request, _i18n_translate("Qarz o'chirildi!", get_request_lang(request)))
    return redirect('debt_list')
