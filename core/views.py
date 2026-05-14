from core.i18n import (
    translate as _i18n_translate,
    get_request_lang,
    format_month_year,
    translate_category as _translate_cat,
    translate_account_name as _translate_acc,
)
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, PasswordChangeForm
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils import translation
from django.views.decorators.http import require_POST
from django.conf import settings
from datetime import datetime
import json
from decimal import Decimal
from django.core.exceptions import ValidationError
# Django session key for language preference
LANGUAGE_SESSION_KEY = "django_language"

from accounts_app.models import Account
from transactions.models import Transaction, Category
from budgets.models import Budget
from debts.models import Debt
from core.models import UserProfile, FamilyGroup, FamilyMember, FamilyJoinRequest
from core.ai import get_ai_tips, get_ai_source, chat_reply, get_ai_provider, get_ai_provider_label
from core.decorators import role_required
from core.family_utils import (
    get_active_family,
    get_family_role,
    handle_scope_param,
    scope_queryset,
    accounts_queryset,
    can_manage_family_finance,
    is_family_admin,
    ensure_scope,
    get_user_gender,
    get_parent_role_for_gender,
    get_child_role_for_gender,
    is_role_allowed_for_user,
    is_family_parent,
    is_family_head,
    ROLE_LABELS,
)


def landing(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'landing.html')


def handler404(request, exception):
    try:
        return render(request, '404.html', status=404)
    except Exception:
        from django.http import HttpResponse
        return HttpResponse(
            '<html><body><h1>404 - Sahifa topilmadi</h1>'
            '<p><a href="/">Bosh sahifaga qaytish</a></p></body></html>',
            status=404,
        )


@require_POST
def set_language(request):
    lang = (request.POST.get("language") or "").strip().lower()
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    if lang not in dict(getattr(settings, "LANGUAGES", [])):
        return redirect(next_url)

    request.session[LANGUAGE_SESSION_KEY] = lang
    request.session.modified = True

    # Til o'zgarganda AI tips keshini tozala — eski tildagi tavsiyalar ko'rinmasin
    request.session.pop("ai_tips_cache", None)
    request.session.pop("ai_source", None)

    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.language = lang
        profile.save()

    translation.activate(lang)
    response = redirect(next_url)
    # Cookie orqali ham saqlash — login/logout da sessiya o'zgarsa ham til saqlansin
    response.set_cookie(
        "fintrack_lang",
        lang,
        max_age=365 * 24 * 3600,
        httponly=False,
        samesite="Lax",
    )
    return response


def _build_ai_context(user, family=None, role=None):
    lang = get_request_lang(request=None)
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year

    accounts = accounts_queryset(user, family=family, role=role)
    rates = getattr(settings, 'CURRENCY_RATES', {'UZS': 1})
    total_balance = sum(
        float(acc.balance) * rates.get(acc.currency, 1)
        for acc in accounts if acc.include_in_total
    )

    monthly_transactions = scope_queryset(
        Transaction.objects.filter(
            date__month=current_month,
            date__year=current_year
        ),
        user=user,
        family=family,
        role=role,
    )
    monthly_expense = monthly_transactions.filter(
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    monthly_income = monthly_transactions.filter(
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    top_cat_row = monthly_transactions.filter(transaction_type='expense').values(
        'category__name'
    ).annotate(total=Sum('amount')).order_by('-total').first()

    budgets = scope_queryset(
        Budget.objects.filter(month=current_month, year=current_year),
        user=user,
        family=family,
        role=role,
    )
    # Precompute actuals in one query to avoid N+1 in get_percentage()
    _ai_budgets = list(budgets)
    _ai_cat_ids = [b.category_id for b in _ai_budgets if b.category_id]
    if _ai_cat_ids:
        _ai_actuals = scope_queryset(
            Transaction.objects.filter(
                transaction_type='expense',
                date__month=current_month,
                date__year=current_year,
                category_id__in=_ai_cat_ids,
            ),
            user=user, family=family, role=role,
        ).values('category_id').annotate(total=Sum('amount'))
        _ai_actual_map = {r['category_id']: float(r['total'] or 0) for r in _ai_actuals}
        for _b in _ai_budgets:
            _b._precomputed_actual = _ai_actual_map.get(_b.category_id, 0.0)
    budgets_near_limit = sum(
        1 for b in _ai_budgets if b.budget_type == 'expense' and b.get_percentage() >= 75
    )
    budgets_over_limit = sum(
        1 for b in _ai_budgets if b.budget_type == 'expense' and b.get_percentage() >= 100
    )

    overdue_debts = scope_queryset(
        Debt.objects.filter(status='open', due_date__lt=today),
        user=user,
        family=family,
        role=role,
    ).count()

    income_val = float(monthly_income)
    expense_val = float(monthly_expense)
    savings_rate = int(((income_val - expense_val) / income_val) * 100) if income_val > 0 else 0
    expense_ratio = int((expense_val / income_val) * 100) if income_val > 0 else 0

    return {
        'total_balance': int(total_balance),
        'monthly_income': int(monthly_income),
        'monthly_expense': int(monthly_expense),
        'net': int(float(monthly_income) - float(monthly_expense)),
        'top_expense_category': _translate_cat((top_cat_row or {}).get('category__name') or '', lang),
        'budgets_near_limit': budgets_near_limit,
        'budgets_over_limit': budgets_over_limit,
        'budgets_count': len(_ai_budgets),
        'overdue_debts': overdue_debts,
        'savings_rate_pct': savings_rate,
        'expense_ratio_pct': expense_ratio,
        'monthly_tx_count': monthly_transactions.count(),
    }


@login_required
def dashboard(request):
    """Asosiy dashboard"""
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    lang = get_request_lang(request)
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year

    # Accountlar
    accounts = accounts_queryset(user, family=family, role=role)
    
    # Umumiy balans (UZS ga o'girib)
    rates = {'UZS': 1, 'USD': 12700, 'EUR': 13800, 'RUB': 140}
    total_balance = sum(
        float(acc.balance) * rates.get(acc.currency, 1)
        for acc in accounts if acc.include_in_total
    )

    # Bu oy uchun statistika
    monthly_transactions = scope_queryset(
        Transaction.objects.filter(
            date__month=current_month,
            date__year=current_year
        ),
        user=user,
        family=family,
        role=role,
    )
    
    monthly_expense = monthly_transactions.filter(
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    monthly_income = monthly_transactions.filter(
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # So'nggi tranzaksiyalar
    recent_transactions = scope_queryset(
        Transaction.objects.select_related('category', 'account'),
        user=user,
        family=family,
        role=role,
    )[:10]

    # Qarzlar
    open_debts_given = scope_queryset(
        Debt.objects.filter(debt_type='given', status__in=['open', 'partial']),
        user=user,
        family=family,
        role=role,
    )
    open_debts_taken = scope_queryset(
        Debt.objects.filter(debt_type='taken', status__in=['open', 'partial']),
        user=user,
        family=family,
        role=role,
    )

    total_given = sum(float(d.remaining_amount) for d in open_debts_given)
    total_taken = sum(float(d.remaining_amount) for d in open_debts_taken)

    # Byudjetlar
    budgets = scope_queryset(
        Budget.objects.filter(month=current_month, year=current_year).select_related('category'),
        user=user,
        family=family,
        role=role,
    )

    # ── Precompute budget actuals in ONE query (fixes N+1) ──────────────────
    budget_list = list(budgets)
    _cat_ids = [b.category_id for b in budget_list if b.category_id]
    if _cat_ids:
        _actual_rows = scope_queryset(
            Transaction.objects.filter(
                transaction_type='expense',
                date__month=current_month,
                date__year=current_year,
                category_id__in=_cat_ids,
            ),
            user=user, family=family, role=role,
        ).values('category_id').annotate(total=Sum('amount'))
        _actual_map = {r['category_id']: float(r['total'] or 0) for r in _actual_rows}
    else:
        _actual_map = {}
    for _b in budget_list:
        _b._precomputed_actual = _actual_map.get(_b.category_id, 0.0)
    budgets = budget_list  # use list from now on (already evaluated)

    # Kategoriya bo'yicha xarajatlar (bu oy)
    cat_expenses = list(monthly_transactions.filter(
        transaction_type='expense'
    ).values('category__name', 'category__icon', 'category__color').annotate(
        total=Sum('amount')
    ).order_by('-total')[:5])

    # Income vs Expense (this month)
    income_expense_chart = {
        'labels': [_i18n_translate('Daromad', lang), _i18n_translate('Xarajat', lang)],
        'values': [float(monthly_income), float(monthly_expense)],
    }

    # Expenses by category (this month)
    cat_expense_chart = list(monthly_transactions.filter(
        transaction_type='expense'
    ).values('category__name', 'category__color').annotate(
        total=Sum('amount')
    ).order_by('-total'))
    other_label = _i18n_translate('Boshqa', lang)
    expense_by_category = [
        {
            'name': _translate_cat(item['category__name'] or other_label, lang),
            'value': float(item['total'] or 0),
            'color': item['category__color'] or '#64748b',
        }
        for item in cat_expense_chart
    ]

    # Monthly expense trend (last 6 months) — single query with TruncMonth
    from django.db.models.functions import TruncMonth as _TruncMonth
    from datetime import date as _date

    # Calculate start of the window (6 months ago, 1st of that month)
    _sm, _sy = current_month - 5, current_year
    while _sm <= 0:
        _sm += 12
        _sy -= 1
    _trend_start = _date(_sy, _sm, 1)

    _trend_rows = scope_queryset(
        Transaction.objects.filter(
            transaction_type='expense',
            date__gte=_trend_start,
        ),
        user=user, family=family, role=role,
    ).annotate(
        _month=_TruncMonth('date')
    ).values('_month').annotate(
        total=Sum('amount')
    ).order_by('_month')

    _trend_map = {}
    for _row in _trend_rows:
        _mo = _row['_month']
        if hasattr(_mo, 'month'):
            _trend_map[(_mo.year, _mo.month)] = float(_row['total'] or 0)

    monthly_trend = []
    for i in range(5, -1, -1):
        m = current_month - i
        y = current_year
        while m <= 0:
            m += 12
            y -= 1
        monthly_trend.append({
            'label': format_month_year(y, m, lang, short=True),
            'value': _trend_map.get((y, m), 0.0),
        })

    # Account balance breakdown
    account_breakdown = [
        {
            'name': _translate_acc(acc.name, lang),
            'value': float(acc.balance),
            'color': acc.color or '#6366f1',
        }
        for acc in accounts
    ]

    # Ogohlantirish: byudjet limitiga yaqin
    alerts = []
    for budget in budgets:
        pct = budget.get_percentage()
        if pct >= 90 and budget.budget_type == 'expense':
            alerts.append({
                'type': 'danger',
                'msg': _i18n_translate("Diqqat: {budget}: byudjetning {pct}% sarflandi!", lang).format(
                    budget=budget.name,
                    pct=pct,
                ),
            })
        elif pct >= 75 and budget.budget_type == 'expense':
            alerts.append({
                'type': 'warning',
                'msg': _i18n_translate("Eslatma: {budget}: byudjetning {pct}% sarflandi", lang).format(
                    budget=budget.name,
                    pct=pct,
                ),
            })
    
    # Muddati o'tgan qarzlar
    for debt in open_debts_given:
        if debt.is_overdue:
            alerts.append({
                'type': 'warning',
                'msg': _i18n_translate("Muddat o'tdi: {person}dan olishi kerak bo'lgan qarz muddati o'tdi!", lang).format(
                    person=debt.person_name,
                ),
            })

    top_cat = cat_expenses[0]['category__name'] if cat_expenses else None
    budgets_near_limit = sum(
        1 for b in budgets if b.budget_type == 'expense' and b.get_percentage() >= 75
    )
    overdue_debts = scope_queryset(
        Debt.objects.filter(status='open', due_date__lt=today),
        user=user,
        family=family,
        role=role,
    ).count()

    income_val = float(monthly_income)
    expense_val = float(monthly_expense)
    savings_rate = int(((income_val - expense_val) / income_val) * 100) if income_val > 0 else 0
    expense_ratio = int((expense_val / income_val) * 100) if income_val > 0 else 0
    budgets_over_limit = sum(
        1 for b in budgets if b.budget_type == 'expense' and b.get_percentage() >= 100
    )
    budgets_count = len(budgets)
    monthly_tx_count = monthly_transactions.count()

    ai_tips = get_ai_tips(request, "dashboard", {
        'total_balance': int(total_balance),
        'monthly_income': int(monthly_income),
        'monthly_expense': int(monthly_expense),
        'net': int(float(monthly_income) - float(monthly_expense)),
        'top_expense_category': _translate_cat(top_cat or '', lang),
        'budgets_near_limit': budgets_near_limit,
        'budgets_over_limit': budgets_over_limit,
        'budgets_count': budgets_count,
        'overdue_debts': overdue_debts,
        'savings_rate_pct': savings_rate,
        'expense_ratio_pct': expense_ratio,
        'monthly_tx_count': monthly_tx_count,
    }, max_items=4)
    ai_source = get_ai_source(request, "dashboard")

    context = {
        'accounts': accounts,
        'total_balance': total_balance,
        'monthly_expense': monthly_expense,
        'monthly_income': monthly_income,
        'net_worth': float(monthly_income) - float(monthly_expense),
        'recent_transactions': recent_transactions,
        'open_debts_given': open_debts_given[:3],
        'open_debts_taken': open_debts_taken[:3],
        'total_given': total_given,
        'total_taken': total_taken,
        'budgets': budgets,
        'cat_expenses': cat_expenses,
        'income_expense_json': json.dumps(income_expense_chart),
        'expense_by_category_json': json.dumps(expense_by_category),
        'monthly_trend_json': json.dumps(monthly_trend),
        'account_breakdown_json': json.dumps(account_breakdown),
        'alerts': alerts,
        'current_month': format_month_year(today.year, today.month, lang),
        'ai_tips': ai_tips,
        'ai_source': ai_source,
        'ai_topic': 'dashboard',
        'active_family': family,
        'family_role': role,
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def ai_assistant(request):
    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    ctx = _build_ai_context(request.user, family=family, role=role)
    ai_tips = get_ai_tips(request, "dashboard", ctx)
    ai_source = get_ai_source(request, "dashboard")
    chat_history = request.session.get('ai_chat_history', [])
    provider = get_ai_provider(request)
    provider_label = get_ai_provider_label(request)
    provider_online = provider not in ("offline", "")

    return render(request, 'core/ai_assistant.html', {
        'ai_tips': ai_tips,
        'ai_source': ai_source,
        'chat_history': chat_history,
        'ai_context': ctx,
        'ai_provider': provider,
        'ai_provider_label': provider_label,
        'ai_provider_online': provider_online,
        'openai_label': getattr(settings, "OPENAI_LABEL", "ChatGPT"),
        'ai_topic': 'assistant',
        'active_family': family,
        'family_role': role,
    })


@login_required
def ai_chat(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    message = request.POST.get('message', '').strip()
    if not message:
        return JsonResponse({'error': 'Empty message'}, status=400)

    handle_scope_param(request)
    family = get_active_family(request)
    role = get_family_role(request.user, family) if family else None
    history = request.session.get('ai_chat_history', [])
    ctx = _build_ai_context(request.user, family=family, role=role)
    provider = get_ai_provider(request)
    lang = getattr(request, "LANGUAGE_CODE", None)
    reply, source, error = chat_reply(message, ctx, history, lang=lang)
    if source in ("groq", "openai", "anthropic", "gemini"):
        request.session["ai_provider_active"] = source
        request.session.modified = True
    if error:
        err_lower = error.lower()
        if "http 429" in err_lower or "quota" in err_lower:
            error = "AI limiti tugadi. Billing/limitni tekshiring yoki keyinroq urinib ko'ring."
        elif "http 401" in err_lower or "http 403" in err_lower:
            if provider == "groq":
                error = "API kalitida muammo bor. GROQ_API_KEY ni tekshiring."
            elif provider == "openai":
                error = "API kalitida muammo bor. OPENAI_API_KEY ni tekshiring."
            elif provider == "anthropic":
                error = "API kalitida muammo bor. ANTHROPIC_API_KEY ni tekshiring."
            elif provider == "gemini":
                error = "API kalitida muammo bor. GEMINI_API_KEY ni tekshiring."
            else:
                error = "API kalitida muammo bor. API key ni tekshiring."
        elif "http 404" in err_lower or "not found" in err_lower:
            if provider == "groq":
                error = "Model topilmadi. GROQ_MODEL nomini tekshiring."
            elif provider == "openai":
                error = "Model topilmadi. OPENAI_MODEL nomini tekshiring."
            elif provider == "anthropic":
                error = "Model topilmadi. ANTHROPIC_MODEL nomini tekshiring."
            elif provider == "gemini":
                error = "Model topilmadi. GEMINI_MODEL nomini tekshiring."
            else:
                error = "Model topilmadi. Model nomini tekshiring."

    history.append({'role': 'user', 'text': message})
    history.append({'role': 'assistant', 'text': reply})
    request.session['ai_chat_history'] = history[-30:]
    request.session.modified = True

    resp = {'reply': reply, 'source': source}
    if error:
        resp['error'] = error
    return JsonResponse(resp)


@login_required
def profile_view(request):
    """Profil sahifasi - avatar, til, valyuta, jinsi sozlamalari"""
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    password_open = False
    form_username = None
    form_email = None

    if request.method == 'POST':
        has_error = False
        password_error = False
        password_changed = False

        # Avatar yuklash
        if 'avatar' in request.FILES:
            avatar_file = request.FILES['avatar']
            from django.conf import settings as _s
            max_size = getattr(_s, 'MAX_UPLOAD_SIZE', 2 * 1024 * 1024)
            allowed_ext = getattr(_s, 'ALLOWED_IMAGE_EXTENSIONS', ['.jpg', '.jpeg', '.png', '.webp'])
            import os as _os
            ext = _os.path.splitext(avatar_file.name)[1].lower()
            if avatar_file.size > max_size:
                messages.error(request, _i18n_translate("Rasm hajmi {n} MB dan oshmasligi kerak.", get_request_lang(request)).format(n=max_size//(1024*1024)))
            elif ext not in allowed_ext:
                messages.error(request, _i18n_translate("Faqat JPG, PNG, WEBP formatlar qo'llab-quvvatlanadi.", get_request_lang(request)))
            else:
                # Eski avatarni o'chirish
                if profile.avatar:
                    try:
                        profile.avatar.delete(save=False)
                    except Exception:
                        pass
                profile.avatar = avatar_file

        # Avatar o'chirish
        if request.POST.get('remove_avatar') == '1' and profile.avatar:
            try:
                profile.avatar.delete(save=False)
            except Exception:
                pass
            profile.avatar = None

        profile.phone = request.POST.get('phone', '').strip()
        gender = (request.POST.get('gender') or '').strip().lower()
        if gender in ('male', 'female'):
            profile.gender = gender
        profile.default_currency = request.POST.get('default_currency', 'UZS')
        lang_to_set = None
        language = request.POST.get('language', 'uz')
        if language in ('uz', 'ru', 'en'):
            profile.language = language
            request.session[LANGUAGE_SESSION_KEY] = language
            request.session.modified = True
            request.LANGUAGE_CODE = language
            translation.activate(language)
            lang_to_set = language
        profile.save()

        user = request.user
        user.first_name = request.POST.get('first_name', '').strip()[:150]
        user.last_name = request.POST.get('last_name', '').strip()[:150]
        # Username (login) update
        form_username = (request.POST.get('username') or '').strip()
        if form_username and form_username != user.username:
            username_field = user._meta.get_field('username')
            try:
                cleaned_username = username_field.clean(form_username, user)
            except ValidationError as exc:
                has_error = True
                msg = exc.messages[0] if exc.messages else "Login noto'g'ri formatda."
                messages.error(request, msg)
            else:
                from django.contrib.auth.models import User as _User
                if _User.objects.filter(username__iexact=cleaned_username).exclude(pk=user.pk).exists():
                    has_error = True
                    messages.error(request, _i18n_translate("Bu login allaqachon ishlatilmoqda.", get_request_lang(request)))
                else:
                    user.username = cleaned_username
        elif not form_username:
            form_username = user.username
        # Email unikal tekshiruvi
        form_email = request.POST.get('email', '').strip()
        from django.contrib.auth.models import User as _User
        if form_email and _User.objects.filter(email=form_email).exclude(pk=user.pk).exists():
            has_error = True
            messages.error(request, _i18n_translate("Bu email allaqachon ishlatilmoqda.", get_request_lang(request)))
        else:
            user.email = form_email
        user.save()

        current_password = (request.POST.get('current_password') or '').strip()
        new_password1 = (request.POST.get('new_password1') or '').strip()
        new_password2 = (request.POST.get('new_password2') or '').strip()
        if current_password or new_password1 or new_password2:
            password_form = PasswordChangeForm(
                user=request.user,
                data={
                    'old_password': current_password,
                    'new_password1': new_password1,
                    'new_password2': new_password2,
                },
            )
            if password_form.is_valid():
                updated_user = password_form.save()
                update_session_auth_hash(request, updated_user)
                password_changed = True
                messages.success(request, _i18n_translate("Parol muvaffaqiyatli yangilandi.", get_request_lang(request)))
            else:
                password_error = True
                password_open = True
                for errs in password_form.errors.values():
                    for err in errs:
                        messages.error(request, err)

        if password_error or has_error:
            response = render(
                request,
                'core/profile.html',
                {
                    'profile': profile,
                    'password_open': password_open,
                    'form_username': form_username,
                    'form_email': form_email,
                },
            )
            if lang_to_set:
                response.set_cookie(
                    "fintrack_lang",
                    lang_to_set,
                    max_age=365 * 24 * 3600,
                    httponly=False,
                    samesite="Lax",
                )
            return response

        if not password_changed:
            messages.success(request, _i18n_translate('Profil muvaffaqiyatli yangilandi!', get_request_lang(request)))
        response = redirect('profile')
        if lang_to_set:
            response.set_cookie(
                "fintrack_lang",
                lang_to_set,
                max_age=365 * 24 * 3600,
                httponly=False,
                samesite="Lax",
            )
        return response

    return render(
        request,
        'core/profile.html',
        {
            'profile': profile,
            'password_open': password_open,
            'form_username': form_username,
            'form_email': form_email,
        },
    )

@login_required
def family_view(request):
    """Oila guruhi sahifasi"""
    handle_scope_param(request)
    user = request.user
    gender = get_user_gender(user)
    lang = get_request_lang(request)
    active_family = get_active_family(request)
    active_role = get_family_role(user, active_family) if active_family else None

    def _role_conflict(target_user, role, exclude_family=None):
        member_qs = FamilyMember.objects.filter(user=target_user, role=role)
        if exclude_family:
            member_qs = member_qs.exclude(family=exclude_family)
        if member_qs.exists():
            return True
        pending_qs = FamilyJoinRequest.objects.filter(user=target_user, role=role, status='pending')
        if exclude_family:
            pending_qs = pending_qs.exclude(family=exclude_family)
        return pending_qs.exists()
    
    memberships = FamilyMember.objects.filter(user=user).select_related('family')

    # Auto-activate first membership if not active yet
    if not active_family and memberships.exists():
        preferred = memberships.filter(role='father').first() or memberships.first()
        first_family = preferred.family
        ensure_scope(request, scope="family", family_id=first_family.id)
        active_family = first_family
        active_role = get_family_role(user, active_family)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create':
            if not gender:
                messages.error(request, _i18n_translate("Avval profilingizda jinsni tanlang.", get_request_lang(request)))
                return redirect('profile')
            member_count = FamilyMember.objects.filter(user=user).count()
            if member_count >= 2:
                messages.error(request, _i18n_translate("Siz maksimal 2 ta oilaga a'zo bo'la olasiz.", get_request_lang(request)))
                return redirect('family')
            name = request.POST.get('name', '')
            if name:
                role = get_parent_role_for_gender(gender)
                if not role:
                    messages.error(request, _i18n_translate("Jinsga mos rol aniqlanmadi.", get_request_lang(request)))
                    return redirect('family')
                if _role_conflict(user, role):
                    label = _i18n_translate(ROLE_LABELS.get(role, role), lang)
                    messages.error(request, f"Siz faqat bitta oilada {label} " + _i18n_translate("bo'la olasiz", lang) + ".")
                    return redirect('family')
                group = FamilyGroup.objects.create(name=name, created_by=user)
                FamilyMember.objects.create(family=group, user=user, role=role)
                ensure_scope(request, scope="family", family_id=group.id)
                messages.success(request, f"'{name}' " + _i18n_translate("guruhi yaratildi! Taklif kodi:", get_request_lang(request)) + f" {group.invite_code}")
        
        elif action == 'join':
            if not gender:
                messages.error(request, _i18n_translate("Avval profilingizda jinsni tanlang.", get_request_lang(request)))
                return redirect('profile')
            member_count = FamilyMember.objects.filter(user=user).count()
            pending_count = FamilyJoinRequest.objects.filter(user=user, status='pending').count()
            if member_count + pending_count >= 2:
                messages.error(request, _i18n_translate("Siz maksimal 2 ta oilaga a'zo bo'la olasiz.", get_request_lang(request)))
                return redirect('family')
            code = request.POST.get('invite_code', '').strip().upper()
            try:
                group = FamilyGroup.objects.get(invite_code=code)
                if not group.invite_active:
                    messages.error(request, _i18n_translate("Taklif hozircha yopiq. Ota/Ona tomonidan ruxsat berilishi kerak.", get_request_lang(request)))
                    return redirect('family')
                if FamilyMember.objects.filter(family=group, user=user).exists():
                    messages.info(request, f"Siz allaqachon '{group.name}' " + _i18n_translate("guruhidasiz", get_request_lang(request)) + ".")
                elif FamilyJoinRequest.objects.filter(family=group, user=user, status='pending').exists():
                    messages.info(request, _i18n_translate("So'rov yuborilgan. Ota/Ona tasdiqlashini kuting.", get_request_lang(request)))
                else:
                    role = get_child_role_for_gender(gender)
                    if not role:
                        messages.error(request, _i18n_translate("Jinsga mos rol aniqlanmadi.", get_request_lang(request)))
                        return redirect('family')
                    if _role_conflict(user, role):
                        label = _i18n_translate(ROLE_LABELS.get(role, role), lang)
                        messages.error(request, f"Siz faqat bitta oilada {label} " + _i18n_translate("bo'la olasiz", lang) + ".")
                        return redirect('family')
                    FamilyJoinRequest.objects.create(family=group, user=user, role=role, status='pending')
                    messages.success(request, _i18n_translate("So'rov yuborildi. Ota/Ona tasdiqlashini kuting.", get_request_lang(request)))
            except FamilyGroup.DoesNotExist:
                messages.error(request, _i18n_translate("Noto'g'ri taklif kodi!", get_request_lang(request)))

        elif action == 'set_role':
            family_id = request.POST.get('family_id')
            member_id = request.POST.get('member_id')
            new_role = request.POST.get('role')
            family = FamilyGroup.objects.filter(id=family_id, members=user).first()
            if not family:
                messages.error(request, _i18n_translate("Guruh topilmadi.", get_request_lang(request)))
                return redirect('family')
            my_role = get_family_role(user, family)
            if not is_family_parent(my_role):
                messages.error(request, _i18n_translate("Faqat Ota yoki Ona rolidagi a'zo rolni o'zgartira oladi.", get_request_lang(request)))
                return redirect('family')
            member = FamilyMember.objects.filter(id=member_id, family=family).first()
            if member:
                if member.user_id == family.created_by_id and new_role in ('son', 'daughter'):
                    messages.error(request, _i18n_translate("Oila rahbari ota/ona rolida bo'lishi kerak.", get_request_lang(request)))
                    return redirect('family')
                if not is_role_allowed_for_user(member.user, new_role):
                    messages.error(request, _i18n_translate("Jinsga mos bo'lmagan rolni tanlab bo'lmaydi.", get_request_lang(request)))
                    return redirect('family')
                if _role_conflict(member.user, new_role, exclude_family=family):
                    label = _i18n_translate(ROLE_LABELS.get(new_role, new_role), lang)
                    messages.error(request, f"Bu foydalanuvchi allaqachon boshqa oilada {label} " + _i18n_translate("rolida", lang) + ".")
                    return redirect('family')
                if new_role in ('father', 'mother'):
                    exists_parent = FamilyMember.objects.filter(
                        family=family,
                        role=new_role
                    ).exclude(id=member.id).exists()
                    if exists_parent:
                        messages.error(request, _i18n_translate("Bu rol oilada allaqachon mavjud.", get_request_lang(request)))
                        return redirect('family')
                member.role = new_role
                member.save(update_fields=['role'])
                messages.success(request, _i18n_translate("Rol yangilandi.", get_request_lang(request)))
            else:
                messages.error(request, _i18n_translate("A'zo topilmadi.", get_request_lang(request)))

        elif action == 'remove_member':
            family_id = request.POST.get('family_id')
            member_id = request.POST.get('member_id')
            family = FamilyGroup.objects.filter(id=family_id, members=user).first()
            if not family:
                messages.error(request, _i18n_translate("Guruh topilmadi.", get_request_lang(request)))
                return redirect('family')
            my_role = get_family_role(user, family)
            if not is_family_parent(my_role):
                messages.error(request, _i18n_translate("Faqat Ota yoki Ona rolidagi a'zo a'zoni o'chira oladi.", get_request_lang(request)))
                return redirect('family')
            member = FamilyMember.objects.filter(id=member_id, family=family).first()
            if member and member.user_id != user.id:
                member.delete()
                messages.success(request, _i18n_translate("A'zo o'chirildi.", get_request_lang(request)))
            else:
                messages.error(request, _i18n_translate("A'zo o'chirib bo'lmadi.", get_request_lang(request)))

        elif action == 'approve_request':
            req_id = request.POST.get('request_id')
            req = FamilyJoinRequest.objects.filter(id=req_id, status='pending').select_related('family', 'user').first()
            if not req:
                messages.error(request, _i18n_translate("So'rov topilmadi.", get_request_lang(request)))
                return redirect('family')
            my_role = get_family_role(user, req.family)
            if not is_family_parent(my_role):
                messages.error(request, _i18n_translate("Faqat Ota yoki Ona rolidagi a'zo tasdiqlay oladi.", get_request_lang(request)))
                return redirect('family')
            member_count = FamilyMember.objects.filter(user=req.user).count()
            pending_count = FamilyJoinRequest.objects.filter(
                user=req.user,
                status='pending'
            ).exclude(id=req.id).count()
            if member_count + pending_count >= 2:
                messages.error(request, _i18n_translate("Bu foydalanuvchi maksimal 2 ta oilaga a'zo bo'la oladi.", get_request_lang(request)))
                return redirect('family')
            if not is_role_allowed_for_user(req.user, req.role):
                messages.error(request, _i18n_translate("Jinsga mos bo'lmagan rolni tasdiqlab bo'lmaydi.", get_request_lang(request)))
                return redirect('family')
            if _role_conflict(req.user, req.role, exclude_family=req.family):
                label = _i18n_translate(ROLE_LABELS.get(req.role, req.role), lang)
                messages.error(request, f"Bu foydalanuvchi allaqachon boshqa oilada {label} " + _i18n_translate("rolida", lang) + ".")
                return redirect('family')
            FamilyMember.objects.get_or_create(family=req.family, user=req.user, defaults={'role': req.role})
            req.status = 'approved'
            req.save(update_fields=['status'])
            messages.success(request, f"{req.user.username} " + _i18n_translate("guruhga qo'shildi.", get_request_lang(request)))

        elif action == 'reject_request':
            req_id = request.POST.get('request_id')
            req = FamilyJoinRequest.objects.filter(id=req_id, status='pending').select_related('family', 'user').first()
            if not req:
                messages.error(request, _i18n_translate("So'rov topilmadi.", get_request_lang(request)))
                return redirect('family')
            my_role = get_family_role(user, req.family)
            if not is_family_parent(my_role):
                messages.error(request, _i18n_translate("Faqat Ota yoki Ona rolidagi a'zo rad eta oladi.", lang))
                return redirect('family')
            req.status = 'rejected'
            req.save(update_fields=['status'])
            messages.success(request, _i18n_translate("So'rov rad etildi.", get_request_lang(request)))

        elif action == 'invite_regen':
            family_id = request.POST.get('family_id')
            family = FamilyGroup.objects.filter(id=family_id, members=user).first()
            if not family:
                messages.error(request, _i18n_translate("Guruh topilmadi.", get_request_lang(request)))
                return redirect('family')
            if not is_family_head(user, family):
                messages.error(request, _i18n_translate("Faqat oila rahbari (Ota/Ona) taklif kodini yangilashi mumkin.", get_request_lang(request)))
                return redirect('family')
            family.invite_code = ''
            family.invite_active = True
            family.save()
            messages.success(request, _i18n_translate("Yangi taklif kodi yaratildi.", get_request_lang(request)))

        elif action == 'invite_deactivate':
            family_id = request.POST.get('family_id')
            family = FamilyGroup.objects.filter(id=family_id, members=user).first()
            if not family:
                messages.error(request, _i18n_translate("Guruh topilmadi.", get_request_lang(request)))
                return redirect('family')
            if not is_family_head(user, family):
                messages.error(request, _i18n_translate("Faqat oila rahbari (Ota/Ona) taklifni o'chira oladi.", get_request_lang(request)))
                return redirect('family')
            family.invite_active = False
            family.save(update_fields=['invite_active'])
            messages.success(request, _i18n_translate("Taklif o'chirildi.", get_request_lang(request)))

        elif action == 'invite_activate':
            family_id = request.POST.get('family_id')
            family = FamilyGroup.objects.filter(id=family_id, members=user).first()
            if not family:
                messages.error(request, _i18n_translate("Guruh topilmadi.", get_request_lang(request)))
                return redirect('family')
            if not is_family_head(user, family):
                messages.error(request, _i18n_translate("Faqat oila rahbari (Ota/Ona) taklifni yoqa oladi.", get_request_lang(request)))
                return redirect('family')
            family.invite_active = True
            if not family.invite_code:
                family.invite_code = ''
            family.save()
            messages.success(request, _i18n_translate("Taklif yoqildi.", get_request_lang(request)))

        elif action == 'delete_group':
            family_id = request.POST.get('family_id')
            family = FamilyGroup.objects.filter(id=family_id, members=user).first()
            if not family:
                messages.error(request, _i18n_translate("Guruh topilmadi.", get_request_lang(request)))
                return redirect('family')
            if not is_family_head(user, family):
                messages.error(request, _i18n_translate("Faqat oila rahbari (Ota/Ona) guruhni o'chira oladi.", get_request_lang(request)))
                return redirect('family')
            family.delete()
            # Reset scope if deleted active family
            if active_family and active_family.id == family_id:
                ensure_scope(request, scope="personal")
            messages.success(request, _i18n_translate("Guruh o'chirildi.", get_request_lang(request)))
        
        return redirect('family')
    
    admin_families = FamilyGroup.objects.filter(
        memberships__user=user,
        memberships__role__in=['father', 'mother'],
    ).distinct()

    member_summaries = []
    if active_family:
        members_qs = FamilyMember.objects.filter(family=active_family).select_related('user')
        month_expenses = Transaction.objects.filter(
            family=active_family,
            transaction_type='expense',
            date__year=timezone.now().year,
            date__month=timezone.now().month,
        ).values('user_id').annotate(total=Sum('amount'))
        expense_map = {row['user_id']: row['total'] or Decimal('0') for row in month_expenses}
        balance_rows = Account.objects.filter(
            family=active_family,
            include_in_total=True,
        ).values('user_id').annotate(total=Sum('balance'))
        balance_map = {row['user_id']: row['total'] or Decimal('0') for row in balance_rows}

        for m in members_qs:
            can_view_financials = is_family_parent(active_role) or m.user_id == user.id
            member_summaries.append({
                'member': m,
                'monthly_spent': expense_map.get(m.user_id, Decimal('0')),
                'balance': balance_map.get(m.user_id, Decimal('0')),
                'can_view_financials': can_view_financials,
            })

    context = {
        'memberships': memberships,
        'active_family': active_family,
        'family_role': active_role,
        'gender': gender,
        'create_role_label': _i18n_translate(ROLE_LABELS.get(get_parent_role_for_gender(gender)), lang) if gender else None,
        'join_role_label': _i18n_translate(ROLE_LABELS.get(get_child_role_for_gender(gender)), lang) if gender else None,
        'pending_requests': FamilyJoinRequest.objects.filter(
            family__in=admin_families,
            status='pending',
        ).select_related('family', 'user'),
        'member_summaries': member_summaries,
    }
    return render(request, 'core/family.html', context)


@login_required
def set_finance_scope(request):
    scope = request.GET.get("scope", "personal")
    family_id = request.GET.get("family_id")
    next_url = request.GET.get("next") or "dashboard"
    ensure_scope(request, scope=scope, family_id=family_id)
    return redirect(next_url)


@login_required
def family_member_stats(request):
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    if not family:
        messages.info(request, _i18n_translate("Avval oila guruhini tanlang yoki yarating.", get_request_lang(request)))
        return redirect('family')

    role = get_family_role(user, family)
    lang = get_request_lang(request)
    can_view_stats = role in ('father', 'mother')
    members_qs = FamilyMember.objects.none()
    is_admin = is_family_admin(role, user, family)
    if can_view_stats:
        members_qs = FamilyMember.objects.filter(family=family).select_related('user')

    member_id = request.GET.get('member')
    selected_member = None
    if can_view_stats and member_id:
        selected_member = members_qs.filter(id=member_id).first()

    stats = {
        "total_income": 0,
        "total_expense": 0,
        "net": 0,
        "top_category": None,
        "member_name": None,
    }
    pie_data = []
    trend_data = []

    if selected_member:
        from django.db.models import Sum
        from datetime import datetime
        from transactions.models import Transaction

        txs = Transaction.objects.filter(user=selected_member.user).filter(
            Q(family=family) | Q(family__isnull=True)
        )

        total_income = txs.filter(transaction_type='income').aggregate(total=Sum('amount'))['total'] or 0
        total_expense = txs.filter(transaction_type='expense').aggregate(total=Sum('amount'))['total'] or 0
        stats["total_income"] = float(total_income)
        stats["total_expense"] = float(total_expense)
        stats["net"] = float(total_income) - float(total_expense)
        stats["member_name"] = selected_member.user.get_full_name() or selected_member.user.username

        top_cat = txs.filter(transaction_type='expense').values('category__name').annotate(
            total=Sum('amount')
        ).order_by('-total').first()
        stats["top_category"] = _translate_cat((top_cat or {}).get('category__name') or '', lang)

        cat_rows = txs.filter(transaction_type='expense').values(
            'category__name', 'category__color'
        ).annotate(total=Sum('amount')).order_by('-total')
        other_label = _i18n_translate('Boshqa', lang)
        pie_data = [
            {
                'name': _translate_cat(row['category__name'] or other_label, lang),
                'value': float(row['total'] or 0),
                'color': row['category__color'] or '#64748b',
            }
            for row in cat_rows
        ]

        # Last 6 months expense trend
        today = timezone.now().date()
        current_month = today.month
        current_year = today.year
        for i in range(5, -1, -1):
            m = current_month - i
            y = current_year
            while m <= 0:
                m += 12
                y -= 1
            m_exp = txs.filter(
                transaction_type='expense',
                date__year=y,
                date__month=m
            ).aggregate(total=Sum('amount'))['total'] or 0
            trend_data.append({
                'label': format_month_year(y, m, lang, short=True),
                'value': float(m_exp),
            })

    context = {
        'family': family,
        'role': role,
        'members': members_qs,
        'selected_member': selected_member,
        'is_admin': is_admin,
        'can_view_stats': can_view_stats,
        'stats': stats,
        'pie_data_json': json.dumps(pie_data),
        'trend_data_json': json.dumps(trend_data),
    }
    return render(request, 'core/family_stats.html', context)