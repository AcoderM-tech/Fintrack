from core.i18n import translate as _i18n_translate, get_request_lang, translate_category as _translate_cat
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Case, When, DecimalField, Q
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone
from django.core.cache import cache
from datetime import datetime, timedelta, date
from decimal import Decimal
import json

from transactions.models import Transaction
from core.models import FamilyMember
from core.ai import get_ai_tips, get_ai_source, build_financial_insights
from core.i18n import translate as _i18n_translate, get_request_lang, format_month_year, format_day_month, get_month_name
from core.family_utils import (
    get_active_family,
    get_family_role,
    handle_scope_param,
    scope_queryset,
)


@login_required
def analytics_dashboard(request):
    handle_scope_param(request)
    user = request.user
    family = get_active_family(request)
    role = get_family_role(user, family) if family else None
    lang = get_request_lang(request)
    today = timezone.now().date()
    family_stats_blocked = bool(family and role in ('son', 'daughter'))

    period = request.GET.get('period', 'monthly')
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))

    # Davrni aniqlash
    if period == 'daily':
        date_from = today
        date_to = today
    elif period == 'weekly':
        date_from = today - timedelta(days=7)
        date_to = today
    elif period == 'monthly':
        date_from = today.replace(day=1, month=month, year=year)
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        date_to = today.replace(day=last_day, month=month, year=year)
    elif period == 'yearly':
        date_from = datetime(year, 1, 1).date()
        date_to = datetime(year, 12, 31).date()
    else:
        date_from = today - timedelta(days=30)
        date_to = today

    base_source = Transaction.objects.filter(
        date__gte=date_from,
        date__lte=date_to
    )
    if family and role in ('father', 'mother'):
        member_ids = FamilyMember.objects.filter(family=family).values_list('user_id', flat=True)
        base_qs = base_source.filter(
            Q(family=family) | Q(family__isnull=True, user_id__in=member_ids)
        )
    else:
        base_qs = scope_queryset(
            base_source,
            user=user,
            family=family,
            role=role,
        )

    if family_stats_blocked:
        context = {
            'total_expense': Decimal('0'),
            'total_income': Decimal('0'),
            'net': Decimal('0'),
            'cat_expense': [],
            'cat_income': [],
            'chart_data_json': json.dumps([]),
            'pie_data_json': json.dumps([]),
            'income_pie_json': json.dumps([]),
            'cat_compare': [],
            'period': period,
            'year': year,
            'month': month,
            'month_name': "",
            'date_from': date_from,
            'date_to': date_to,
            'ai_tips': [],
            'ai_source': None,
            'ai_topic': 'analytics',
            'ai_finance': None,
            'family_stats_blocked': True,
            'family_role': role,
        }
        return render(request, 'analytics/dashboard.html', context)

    cache_key = f"analytics:data:{user.id}:{family.id if family else 0}:{role or ''}:{period}:{year}:{month}:{date_from}:{date_to}:{lang}"
    cached = cache.get(cache_key)

    if cached:
        total_expense = cached["total_expense"]
        total_income = cached["total_income"]
        net = cached["net"]
        cat_expense = cached["cat_expense"]
        cat_income = cached["cat_income"]
        cat_compare = cached["cat_compare"]
        chart_days = cached["chart_days"]
        pie_data = cached["pie_data"]
        income_pie_data = cached["income_pie_data"]
    else:
        # Umumiy statistika (bir query)
        totals = base_qs.aggregate(
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
        )
        total_expense = totals.get('total_expense') or Decimal('0')
        total_income = totals.get('total_income') or Decimal('0')
        net = total_income - total_expense

        # Kategoriya bo'yicha xarajatlar
        cat_expense = list(base_qs.filter(transaction_type='expense').values(
            'category__name', 'category__icon', 'category__color'
        ).annotate(total=Sum('amount')).order_by('-total'))

        cat_income = list(base_qs.filter(transaction_type='income').values(
            'category__name', 'category__icon', 'category__color'
        ).annotate(total=Sum('amount')).order_by('-total'))

        # Kategoriya bo'yicha xarajat vs daromad taqqoslash
        other_label = _i18n_translate('Boshqa', lang)
        compare_map = {}
        for item in cat_expense:
            raw_name = item['category__name'] or other_label
            name = _translate_cat(raw_name, lang)
            compare_map.setdefault(name, {
                'name': name,
                'icon': item['category__icon'] or 'tag',
                'color': item['category__color'] or '#64748b',
                'expense': Decimal('0'),
                'income': Decimal('0'),
            })
            compare_map[name]['expense'] = item['total'] or Decimal('0')

        for item in cat_income:
            raw_name = item['category__name'] or other_label
            name = _translate_cat(raw_name, lang)
            if name not in compare_map:
                compare_map[name] = {
                    'name': name,
                    'icon': item['category__icon'] or 'tag',
                    'color': item['category__color'] or '#10b981',
                    'expense': Decimal('0'),
                    'income': Decimal('0'),
                }
            compare_map[name]['income'] = item['total'] or Decimal('0')
            if not compare_map[name].get('icon'):
                compare_map[name]['icon'] = item['category__icon'] or 'tag'

        cat_compare = []
        for item in compare_map.values():
            item['net'] = (item['income'] or Decimal('0')) - (item['expense'] or Decimal('0'))
            item['volume'] = (item['income'] or Decimal('0')) + (item['expense'] or Decimal('0'))
            cat_compare.append(item)
        cat_compare.sort(key=lambda x: x['volume'], reverse=True)

        # Chart data: kunlik trend (oxirgi 30 kun yoki tanlangan davr)
        if period == 'yearly':
            grouped = base_qs.annotate(month=TruncMonth('date')).values('month').annotate(
                expense=Sum(
                    Case(
                        When(transaction_type='expense', then='amount'),
                        default=Decimal('0'),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                ),
                income=Sum(
                    Case(
                        When(transaction_type='income', then='amount'),
                        default=Decimal('0'),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                ),
            ).order_by('month')
            grouped_map = {row['month'].month: row for row in grouped if row['month']}
            chart_days = []
            for m in range(1, 13):
                row = grouped_map.get(m, {})
                chart_days.append({
                    'date': get_month_name(m, lang, short=True),
                    'expense': float(row.get('expense') or 0),
                    'income': float(row.get('income') or 0),
                })
        else:
            # Kunlik (monthly/weekly/daily) - yagona query
            grouped = base_qs.annotate(day=TruncDay('date')).values('day').annotate(
                expense=Sum(
                    Case(
                        When(transaction_type='expense', then='amount'),
                        default=Decimal('0'),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                ),
                income=Sum(
                    Case(
                        When(transaction_type='income', then='amount'),
                        default=Decimal('0'),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                ),
            ).order_by('day')
            grouped_map = {}
            for row in grouped:
                day_value = row.get('day')
                if not day_value:
                    continue
                if isinstance(day_value, datetime):
                    day_value = day_value.date()
                grouped_map[day_value] = row
            chart_days = []
            current = date_from
            end_date = date_to if period == 'monthly' else min(date_to, date_from + timedelta(days=30))
            while current <= end_date:
                row = grouped_map.get(current, {})
                chart_days.append({
                    'date': current.strftime('%d') if period == 'monthly' else format_day_month(current, lang),
                    'expense': float(row.get('expense') or 0),
                    'income': float(row.get('income') or 0),
                })
                current += timedelta(days=1)

        # Kategoriya pie chart data
        pie_data = [
            {
                'name': _translate_cat(item['category__name'] or other_label, lang),
                'icon': item['category__icon'] or 'tag',
                'color': item['category__color'] or '#64748b',
                'value': float(item['total']),
            }
            for item in cat_expense
        ]

        income_pie_data = [
            {
                'name': _translate_cat(item['category__name'] or other_label, lang),
                'icon': item['category__icon'] or 'tag',
                'color': item['category__color'] or '#10b981',
                'value': float(item['total']),
            }
            for item in cat_income
        ]

        cache.set(cache_key, {
            "total_expense": total_expense,
            "total_income": total_income,
            "net": net,
            "cat_expense": cat_expense,
            "cat_income": cat_income,
            "cat_compare": cat_compare,
            "chart_days": chart_days,
            "pie_data": pie_data,
            "income_pie_data": income_pie_data,
        }, 300)

    from datetime import datetime as dt
    month_name = format_month_year(year, month, lang) if period == 'monthly' else str(year)

    top_expense_cat = _translate_cat(cat_expense[0]['category__name'] or '', lang) if cat_expense else None
    income_val = float(total_income)
    expense_val = float(total_expense)
    expense_ratio = int((expense_val / income_val) * 100) if income_val > 0 else 0
    ai_tips = get_ai_tips(request, "analytics", {
        'total_income': int(total_income),
        'total_expense': int(total_expense),
        'net': int(net),
        'top_expense_category': top_expense_cat,
        'expense_ratio_pct': expense_ratio,
        'period': period,
    }, max_items=3)
    ai_source = get_ai_source(request, "analytics")
    ai_cache_key = f"analytics:ai:{user.id}:{family.id if family else 0}:{role or ''}:{lang}"
    ai_finance = cache.get(ai_cache_key)
    if ai_finance is None:
        ai_finance = build_financial_insights(user, family=family, role=role, lang=lang)
        cache.set(ai_cache_key, ai_finance, 3600)

    context = {
        'total_expense': total_expense,
        'total_income': total_income,
        'net': net,
        'cat_expense': cat_expense,
        'cat_income': cat_income,
        'chart_data_json': json.dumps(chart_days),
        'pie_data_json': json.dumps(pie_data),
        'income_pie_json': json.dumps(income_pie_data),
        'cat_compare': cat_compare,
        'period': period,
        'year': year,
        'month': month,
        'month_name': month_name,
        'date_from': date_from,
        'date_to': date_to,
        'ai_tips': ai_tips,
        'ai_source': ai_source,
        'ai_topic': 'analytics',
        'ai_finance': ai_finance,
        'other_label': _i18n_translate('Boshqa', lang),
        'family_stats_blocked': False,
        'family_role': role,
    }
    return render(request, 'analytics/dashboard.html', context)
