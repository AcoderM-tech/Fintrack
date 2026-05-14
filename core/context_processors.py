from django.core.cache import cache
from django.conf import settings
from core.models import Notification, FamilyMember, UserProfile
from core.i18n import translate as _i18n_translate, get_request_lang
from core.family_utils import get_active_family, get_family_role, ROLE_LABELS


def menu_notifications(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    active_family = get_active_family(request)

    # Notification throttle — faqat 5 daqiqada bir marta refresh
    cache_ttl = getattr(settings, "NOTIFICATION_REFRESH_CACHE_SECONDS", 300)
    cache_key = f"notif_refresh:{request.user.id}:{active_family.id if active_family else 0}"
    if not cache.get(cache_key):
        try:
            from core.notifications import refresh_debt_due_notifications, refresh_low_balance_notifications
            refresh_debt_due_notifications(request.user, family=active_family)
            refresh_low_balance_notifications(request.user, family=active_family)
            cache.set(cache_key, 1, cache_ttl)
        except Exception:
            pass

    if active_family:
        base_qs = Notification.objects.filter(user=request.user, family=active_family)
    else:
        base_qs = Notification.objects.filter(user=request.user, family__isnull=True)

    unread_count = base_qs.filter(is_read=False).count()
    qs = base_qs.only("id", "title", "message", "level", "created_at", "notif_type", "data", "is_read")

    def _fmt_int(val):
        try:
            return f"{int(val):,}"
        except Exception:
            return str(val)

    def _localize_notification(notif, lang):
        if lang == "uz":
            return None

        import re

        data_work = dict(notif.data or {})
        orig_data = dict(data_work)

        def _parse_int_any(text):
            if not text:
                return None
            m = re.search(r"(\d[\d\s,\.]*)", str(text))
            if not m:
                return None
            raw = re.sub(r"[^\d]", "", m.group(1) or "")
            if not raw:
                return None
            try:
                return int(raw)
            except Exception:
                return None

        def _parse_percent(text):
            if not text:
                return None
            m = re.search(r"(\d{1,3})\s*%", str(text))
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None

        def _after_colon(text):
            if not text:
                return ""
            s = str(text)
            if ":" in s:
                return s.split(":", 1)[1].strip()
            return ""

        def _extract_money(label, text):
            """Find number after a label like 'Sarflangan' or 'Limit' in Uzbek/RU/EN-ish strings."""
            if not text:
                return None
            s = str(text)
            # Allow both ":" and "—" etc after label.
            m = re.search(rf"{re.escape(label)}\s*[:\-—]?\s*(\d[\d\s,\.]*)", s, flags=re.IGNORECASE)
            if not m:
                return None
            return _parse_int_any(m.group(1))

        # Backfill missing data for old notifications (so templates can be localized).
        if notif.notif_type == "budget_exceeded":
            data_work.setdefault("category", _after_colon(notif.title))
            data_work.setdefault("percent", _parse_percent(notif.message))
            data_work.setdefault("spent", _extract_money("Sarflangan", notif.message))
            data_work.setdefault("limit", _extract_money("limit", notif.message))

            if not data_work.get("category"):
                m = re.search(r"^(.*?)\s+limiti\b", str(notif.message or ""), flags=re.IGNORECASE)
                if m:
                    data_work["category"] = (m.group(1) or "").strip().strip(" :-—")
        elif notif.notif_type == "spending_spike":
            data_work.setdefault("category", _after_colon(notif.title))
            data_work.setdefault("percent", _parse_percent(notif.message))
        elif notif.notif_type == "low_balance":
            data_work.setdefault("account", _after_colon(notif.title))
            data_work.setdefault("balance", _extract_money("Balans", notif.message))
            data_work.setdefault("threshold", _extract_money("Limit", notif.message))

            if not data_work.get("account"):
                m = re.search(r"^(.*?)\s+hisob", str(notif.message or ""), flags=re.IGNORECASE)
                if m:
                    data_work["account"] = (m.group(1) or "").strip().strip(" :-—")

            if not data_work.get("threshold"):
                msg = (notif.message or "").lower()
                if "ming" in msg:
                    m = re.search(r"(\d[\d\s,\.]*)\s*ming", msg)
                    if m:
                        base = _parse_int_any(m.group(1))
                        if base is not None:
                            data_work["threshold"] = base * 1000
        elif notif.notif_type == "debt_due":
            if "person" not in data_work or not data_work.get("person"):
                m = re.search(r"^(.*?)\s+(?:bo'yicha|uchun)\s+qarz", str(notif.message or ""), flags=re.IGNORECASE)
                if m:
                    data_work["person"] = (m.group(1) or "").strip()
            if "days_left" not in data_work or data_work.get("days_left") in ("", None):
                m = re.search(r"(\d+)\s*kun", str(notif.message or ""), flags=re.IGNORECASE)
                if m:
                    try:
                        data_work["days_left"] = int(m.group(1))
                    except Exception:
                        pass
        else:
            return None

        # Drop empty keys (setdefault may introduce empty strings)
        for k in list(data_work.keys()):
            if data_work[k] in ("", None):
                data_work.pop(k, None)

        # If we managed to fill anything new, persist it to make future renders consistent.
        if data_work and data_work != orig_data:
            try:
                Notification.objects.filter(id=notif.id).update(data=data_work)
            except Exception:
                pass

        title_tpl = None
        message_tpl = None
        if notif.notif_type == "budget_exceeded":
            title_tpl = "Byudjet oshdi: {category}"
            if all(k in data_work for k in ("category", "percent", "spent", "limit")):
                message_tpl = "{category} byudjeti {percent}% ga yetdi. Sarflangan: {spent} UZS, limit: {limit} UZS."
            elif all(k in data_work for k in ("category", "percent")):
                message_tpl = "{category} limiti {percent}% ishlatildi."
        elif notif.notif_type == "spending_spike":
            title_tpl = "Xarajat keskin oshdi: {category}"
            if all(k in data_work for k in ("category", "percent")):
                message_tpl = "{category} xarajatlari o'tgan oyga nisbatan {percent}% ko'paydi."
        elif notif.notif_type == "low_balance":
            title_tpl = "Past balans: {account}"
            if all(k in data_work for k in ("balance", "threshold")):
                message_tpl = "Balans {balance} UZS. Limit: {threshold} UZS."
            elif "threshold" in data_work:
                message_tpl = "Balans {threshold} UZS dan past."
        elif notif.notif_type == "debt_due":
            title_tpl = "Qarz muddati yaqin"
            if all(k in data_work for k in ("person", "days_left")):
                message_tpl = "{person} bo'yicha qarz muddati {days_left} kun qoldi."
            elif "person" in data_work:
                message_tpl = "{person} uchun qarz muddati yaqinlashmoqda."
        else:
            return None

        data_fmt = dict(data_work)
        for key in ("spent", "limit", "balance", "threshold"):
            if key in data_fmt:
                data_fmt[key] = _fmt_int(data_fmt[key])

        # Translate placeholders where safe (system categories/demo account names only).
        try:
            from core.i18n import translate_category as _tcat, translate_account_name as _tacc
            if "category" in data_fmt:
                data_fmt["category"] = _tcat(str(data_fmt["category"]), lang)
            if "account" in data_fmt:
                data_fmt["account"] = _tacc(str(data_fmt["account"]), lang)
        except Exception:
            pass
        try:
            title = _i18n_translate(title_tpl, lang).format(**data_fmt) if title_tpl else _i18n_translate(notif.title, lang)
        except Exception:
            # If data is missing keys, translate the raw stored title directly
            try:
                title = _i18n_translate(notif.title, lang)
            except Exception:
                title = notif.title
        try:
            message = _i18n_translate(message_tpl, lang).format(**data_fmt) if message_tpl else _i18n_translate(notif.message, lang)
        except Exception:
            # If data is missing keys, translate the raw stored message directly
            try:
                message = _i18n_translate(notif.message, lang)
            except Exception:
                message = notif.message
        return title, message

    # Avatar
    avatar_url = None
    try:
        profile = request.user.profile
        if profile.avatar:
            avatar_url = profile.avatar.url
    except Exception:
        pass

    lang = get_request_lang(request)
    notifications = list(qs.order_by("-created_at")[:10])
    for n in notifications:
        localized = _localize_notification(n, lang)
        if localized:
            n.display_title, n.display_message = localized
        else:
            # For uz or unrecognized types, use raw stored values
            n.display_title = n.title
            n.display_message = n.message

    return {
        "menu_notifications": notifications,
        "notif_unread_count": unread_count,
        "user_avatar_url": avatar_url,
    }


def finance_scope(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    memberships = FamilyMember.objects.filter(user=request.user).select_related("family").only(
        "id", "role", "family_id", "family__name", "family__created_by_id",
    )
    active_family = None
    role = None
    if request.session.get("finance_scope", "personal") == "family":
        last_family_id = request.session.get("finance_family_id")
        if last_family_id:
            for m in memberships:
                if m.family_id == last_family_id:
                    active_family = m.family
                    role = m.role
                    break
    if not role and active_family:
        role = get_family_role(request.user, active_family)

    last_family = active_family
    if not last_family and memberships.exists():
        preferred = None
        for m in memberships:
            if m.role == 'father':
                preferred = m
                break
        last_family = preferred.family if preferred else memberships.first().family

    lang = get_request_lang(request)
    role_label = _i18n_translate(ROLE_LABELS.get(role), lang) if role else None
    if active_family and role in ("son", "daughter") and active_family.created_by_id == request.user.id:
        role_label = _i18n_translate("Bosh", lang)

    url_name = ""
    try:
        if request.resolver_match:
            url_name = request.resolver_match.url_name or ""
    except Exception:
        url_name = ""
    scope = request.session.get("finance_scope", "personal")
    nav_open_transactions = scope == "personal" and "transaction" in url_name
    nav_open_analysis = scope == "personal" and (
        url_name == "analytics" or url_name == "calendar" or "budget" in url_name
    )
    nav_open_family = url_name in ("family", "family_stats") or (
        url_name == "analytics" and scope == "family"
    )

    return {
        "finance_scope": scope,
        "active_family": active_family,
        "family_role": role,
        "family_role_label": role_label,
        "family_memberships": memberships,
        "has_family_membership": memberships.exists(),
        "last_family": last_family,
        "last_family_id": last_family.id if last_family else None,
        "nav_open_transactions": nav_open_transactions,
        "nav_open_analysis": nav_open_analysis,
        "nav_open_family": nav_open_family,
    }