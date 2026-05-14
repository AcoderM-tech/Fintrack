import re

from django import template
from django.conf import settings
from django.utils.html import format_html
from core.i18n import translate as _translate

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, text):
    """Template translation helper: {% t "Dashboard" %}"""
    request = context.get("request")
    lang = None

    if request:
        # 1. request.LANGUAGE_CODE (middleware tomonidan qo'yiladi)
        lang = getattr(request, "LANGUAGE_CODE", None)

        # 2. Cookie
        if not lang or lang == "uz":
            cookie_lang = request.COOKIES.get("fintrack_lang", "").strip().lower()
            if cookie_lang in ("ru", "en", "uz"):
                lang = cookie_lang

        # 3. Sessiya
        if not lang or lang == "uz":
            session_lang = ""
            try:
                session_lang = (request.session.get("django_language") or "").strip().lower()
            except Exception:
                pass
            if session_lang in ("ru", "en", "uz"):
                lang = session_lang

        # 4. UserProfile
        if not lang or lang == "uz":
            try:
                profile_lang = (request.user.profile.language or "").strip().lower()
                if profile_lang in ("ru", "en", "uz"):
                    lang = profile_lang
            except Exception:
                pass

    return _translate(text, lang or "uz")


@register.filter
def currency_symbol(currency_code):
    symbols = {'UZS': "so'm", 'USD': '$', 'EUR': '€', 'RUB': '₽'}
    return symbols.get(currency_code, currency_code)


@register.filter
def money_format(value, currency='UZS'):
    try:
        v = float(value)
        if currency == 'UZS':
            return f"{v:,.0f} so'm"
        elif currency == 'USD':
            return f"${v:,.2f}"
        elif currency == 'EUR':
            return f"€{v:,.2f}"
        elif currency == 'RUB':
            return f"{v:,.0f} ₽"
        return f"{v:,.2f} {currency}"
    except (TypeError, ValueError):
        return str(value)


@register.filter
def compact_num(value, lang='uz'):
    """Compact number formatting: 1 200 -> 1.2 ming (uz), 1.2 тыс. (ru), 1.2K (en)."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)

    def fmt_plain(x):
        return f"{int(round(x)):,}".replace(",", " ")

    suffixes = {
        "uz": ("ming", "mln", "mlrd"),
        "ru": ("тыс.", "млн", "млрд"),
        "en": ("K", "M", "B"),
    }
    lang = (lang or "uz").lower()
    if lang not in suffixes:
        lang = "uz"
    s_thousand, s_million, s_billion = suffixes[lang]

    sign = "-" if n < 0 else ""
    n = abs(n)

    if n >= 1_000_000_000:
        val = n / 1_000_000_000
        suffix = s_billion
    elif n >= 1_000_000:
        val = n / 1_000_000
        suffix = s_million
    elif n >= 1_000:
        val = n / 1_000
        suffix = s_thousand
    else:
        return sign + fmt_plain(n)

    if val >= 100:
        num = f"{val:.0f}"
    elif val >= 10:
        num = f"{val:.1f}".rstrip("0").rstrip(".")
    else:
        num = f"{val:.2f}".rstrip("0").rstrip(".")

    if lang == "en":
        return f"{sign}{num}{suffix}"
    return f"{sign}{num} {suffix}"


@register.filter
def to_uzs(value, currency='UZS'):
    try:
        rates = getattr(settings, 'CURRENCY_RATES', {'UZS': 1, 'USD': 12700, 'EUR': 13800, 'RUB': 140})
        return float(value) * rates.get(currency, 1)
    except (TypeError, ValueError):
        return 0


@register.filter
def abs_val(value):
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return value


@register.filter
def pct_bar_color(pct):
    try:
        p = int(pct)
        if p >= 100:
            return 'danger'
        elif p >= 75:
            return 'warning'
        return 'success'
    except (TypeError, ValueError):
        return 'primary'


@register.filter(name="icon")
def icon_filter(value, size="md"):
    """Tabler icon helper. Usage: {{ "credit-card"|icon:"lg" }}."""
    name = (value or "tag")
    if not isinstance(name, str):
        name = str(name)
    name = re.sub(r"[^a-z0-9-]", "", name.lower()) or "tag"

    size = (size or "md")
    if not isinstance(size, str):
        size = str(size)
    size = size.lower()
    if size not in {"sm", "md", "lg", "xl"}:
        size = "md"

    return format_html('<span class="icon icon-{}"><i class="ti ti-{}"></i></span>', size, name)


@register.filter(name="split")
def split_filter(value, sep=","):
    if value is None:
        return []
    if sep is None:
        sep = ","
    return str(value).split(str(sep))


@register.filter(name="get_item")
def get_item_filter(value, key):
    if value is None:
        return None
    try:
        return value.get(key)
    except AttributeError:
        try:
            return value[key]
        except Exception:
            return None


@register.simple_tag(takes_context=True)
def user_avatar_tag(context, size=32):
    """Foydalanuvchi avatarini chiqarish (doira shakl)."""
    request = context.get('request')
    avatar_url = context.get('user_avatar_url')
    if not avatar_url and request and hasattr(request, 'user'):
        try:
            profile = request.user.profile
            if profile.avatar:
                avatar_url = profile.avatar.url
        except Exception:
            pass

    if avatar_url:
        return f'<img src="{avatar_url}" width="{size}" height="{size}" style="border-radius:50%;object-fit:cover;border:2px solid rgba(255,255,255,0.3);" alt="avatar">'
    # Initials fallback
    if request and hasattr(request, 'user'):
        u = request.user
        initials = ''
        if u.first_name:
            initials += u.first_name[0].upper()
        if u.last_name:
            initials += u.last_name[0].upper()
        if not initials:
            initials = u.username[:2].upper()
        return (
            f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:{size}px;height:{size}px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);'
            f'color:#fff;font-size:{max(10, size//3)}px;font-weight:600;border:2px solid rgba(255,255,255,0.3);">'
            f'{initials}</span>'
        )
    return ''


@register.simple_tag(takes_context=True)
def tcat(context, name):
    """Translate a category name if it is a system default category.
    User-created category names are returned as-is."""
    if not name:
        return name
    request = context.get("request")
    lang = "uz"
    if request:
        from core.i18n import get_request_lang
        lang = get_request_lang(request)
    from core.i18n import translate_category
    return translate_category(name, lang)


@register.simple_tag(takes_context=True)
def tacc(context, name):
    """Translate an account name if it is a demo/system name.
    User-defined account names are returned as-is."""
    if not name:
        return name
    request = context.get("request")
    lang = "uz"
    if request:
        from core.i18n import get_request_lang
        lang = get_request_lang(request)
    from core.i18n import translate_account_name
    return translate_account_name(name, lang)


@register.filter(name="tacc_filter")
def tacc_filter_fn(name, lang="uz"):
    """Filter version of tacc for use with | syntax: {{ acc.name|tacc_filter:lang }}"""
    from core.i18n import translate_account_name
    return translate_account_name(str(name) if name else "", lang)


@register.filter(name="tcat_filter")
def tcat_filter_fn(name, lang="uz"):
    """Filter version of tcat for use with | syntax: {{ cat.name|tcat_filter:lang }}"""
    from core.i18n import translate_category
    return translate_category(str(name) if name else "", lang)


@register.simple_tag(takes_context=True)
def url_replace(context, field, value):
    """
    Replace (or add) a single query param while preserving all others.
    Usage: {% url_replace 'page' page_obj.next_page_number %}
    """
    from django.utils.http import urlencode as _urlencode
    request = context.get('request')
    if not request:
        return f'?{field}={value}'
    params = request.GET.copy()
    params[field] = value
    return '?' + params.urlencode()
