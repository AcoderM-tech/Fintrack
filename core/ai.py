"""
FinTrack AI tavsiyalar moduli (AI provider).
Agar API key bo'lmasa yoki xato bo'lsa - fallback tavsiyalar qaytariladi.
"""

import json
import random
import re
import time
import urllib.error
import urllib.request
import difflib
import statistics
from collections import defaultdict
from datetime import timedelta

from django.conf import settings

_CACHE_TTL_SECONDS = 6 * 60 * 60
_HISTORY_LIMIT = 60
_CACHE_VERSION = "v3"
_MODELS_CACHE = {"expires": 0, "models": []}
_MODELS_CACHE_TTL = 6 * 60 * 60
_PROVIDER_DEFAULT_ORDER = ["groq", "openai", "anthropic", "gemini"]
LANGUAGE_SESSION_KEY = "django_language"


def _resolve_language(request=None, default="uz"):
    lang = None
    if request is not None:
        lang = getattr(request, "LANGUAGE_CODE", None)
        if not lang and hasattr(request, "user"):
            profile = getattr(request.user, "profile", None)
            lang = getattr(profile, "language", None)
        if not lang and hasattr(request, "session"):
            lang = request.session.get(LANGUAGE_SESSION_KEY)
    lang = (lang or default).lower()
    if lang not in ("uz", "ru", "en"):
        lang = default
    return lang

def _normalize_provider(name):
    name = (name or "").lower().strip()
    if name in ("chatgpt", "openai"):
        return "openai"
    if name in ("claude", "anthropic"):
        return "anthropic"
    if name in ("google", "gemini"):
        return "gemini"
    if name in ("groq",):
        return "groq"
    if name in ("auto", ""):
        return "auto"
    return name


def _provider_order():
    raw = getattr(settings, "AI_PROVIDER_ORDER", "") or ""
    if raw:
        order = [_normalize_provider(p) for p in raw.split(",") if p.strip()]
        return [p for p in order if p in _PROVIDER_DEFAULT_ORDER]
    return list(_PROVIDER_DEFAULT_ORDER)


def _provider_has_key(provider):
    provider = _normalize_provider(provider)
    if provider == "groq":
        return bool(getattr(settings, "GROQ_API_KEY", ""))
    if provider == "openai":
        return bool(getattr(settings, "OPENAI_API_KEY", ""))
    if provider == "anthropic":
        return bool(getattr(settings, "ANTHROPIC_API_KEY", ""))
    if provider == "gemini":
        return bool(getattr(settings, "GEMINI_API_KEY", ""))
    return False


def _available_providers():
    providers = []
    for provider in _provider_order():
        if _provider_has_key(provider):
            providers.append(provider)
    return providers


def _provider_candidates():
    return _available_providers()


def get_ai_provider(request=None):
    preferred = _normalize_provider(getattr(settings, "AI_PROVIDER", ""))
    if preferred and preferred != "auto":
        return preferred
    if request:
        active = _normalize_provider(request.session.get("ai_provider_active", ""))
        if active in _PROVIDER_DEFAULT_ORDER and _provider_has_key(active):
            return active
    candidates = _provider_candidates()
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return "auto"
    return "offline"


def get_ai_provider_label(request=None):
    provider = get_ai_provider(request)
    if provider == "groq":
        return "Groq"
    if provider == "openai":
        return getattr(settings, "OPENAI_LABEL", "") or "ChatGPT"
    if provider == "anthropic":
        return "Claude"
    if provider == "gemini":
        return "Gemini Flash 1.5"
    if provider == "auto":
        return "Auto"
    return "Offline"


_TIPS_CACHE_TTL = 2 * 60 * 60  # 2 soat — tavsiyalar shu vaqt ko'rsatiladi


def _data_fingerprint(data):
    """Ma'lumotlar o'zgarganini aniqlash uchun qisqa imzo."""
    keys = sorted(data.keys())
    parts = [f"{k}:{data[k]}" for k in keys]
    raw = "|".join(parts)
    h = 0
    for ch in raw:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return str(h)


def get_ai_tips(request, topic, data, max_items=5):
    """
    Tavsiyalarni kesh orqali qaytaradi.
    - 2 soat ichida bir xil tavsiyalar ko'rsatiladi.
    - Ma'lumotlar o'zganganda yoki til o'zgarganda yangi generatsiya.
    """
    if not request:
        return _generate_tips(None, topic, data, max_items)

    # Joriy til
    lang = _resolve_language(request)

    now = time.time()
    cache_store = request.session.get("ai_tips_cache", {}) or {}
    # Kesh kalitiga tilni qo'shamiz — til o'zgarganda yangi tavsiyalar chiqadi
    cache_key = f"{topic}:{lang}"
    cached = cache_store.get(cache_key)
    fingerprint = _data_fingerprint(data)

    if (
        cached
        and cached.get("tips")
        and cached.get("expires", 0) > now
        and cached.get("fingerprint") == fingerprint
    ):
        return cached["tips"]

    # Yangi generatsiya
    tips, source = _generate_tips(request, topic, data, max_items)

    cache_store[cache_key] = {
        "tips": tips,
        "source": source,
        "expires": now + _TIPS_CACHE_TTL,
        "fingerprint": fingerprint,
        "lang": lang,
    }
    request.session["ai_tips_cache"] = cache_store
    request.session.modified = True

    _set_ai_source(request, topic, source)
    return tips


def _generate_tips(request, topic, data, max_items):
    """AI yoki fallback orqali yangi tavsiyalar generatsiya qiladi."""
    lang = _resolve_language(request)
    preferred = _normalize_provider(getattr(settings, "AI_PROVIDER", ""))
    providers = [preferred] if preferred and preferred != "auto" else _provider_candidates()
    tips = None
    source = "offline"

    for provider in providers:
        if provider == "gemini":
            tips = _gemini_tips(topic, data, max_items, lang=lang)
        elif provider == "groq":
            tips = _groq_tips(topic, data, max_items, lang=lang)
        elif provider == "openai":
            tips = _openai_tips(topic, data, max_items, lang=lang)
        elif provider == "anthropic":
            tips = _anthropic_tips(topic, data, max_items, lang=lang)
        if tips:
            source = provider
            break

    if not tips:
        source = "fallback" if (providers and any(_provider_has_key(p) for p in providers)) else "offline"
        tips = _fallback_tips(topic, data, max_items, lang=lang)

    # Takrorlanishlarni olib tashlash (lekin historysiz)
    tips = _dedupe(tips, max_items)
    return tips, source


def get_ai_source(request, topic):
    if not request:
        return ""
    lang = _resolve_language(request)
    cache_store = request.session.get("ai_tips_cache", {}) or {}
    # Avval til bilan birga qara
    cache_key = f"{topic}:{lang}"
    cached = cache_store.get(cache_key) or cache_store.get(str(topic))
    if cached and cached.get("source"):
        return cached["source"]
    return (request.session.get("ai_source", {}) or {}).get(str(topic), "")


def _set_ai_source(request, topic, source):
    if not request:
        return
    src = request.session.get("ai_source", {}) or {}
    src[str(topic)] = source
    request.session["ai_source"] = src
    if source in _PROVIDER_DEFAULT_ORDER:
        request.session["ai_provider_active"] = source


def _gemini_tips(topic, data, max_items, lang="uz"):
    prompt = _build_prompt(topic, data, max_items, lang=lang)
    if not prompt:
        return None
    text = _gemini_generate(prompt)
    if not text:
        return None
    return _parse_lines(text, max_items)


def _groq_tips(topic, data, max_items, lang="uz"):
    prompt = _build_prompt(topic, data, max_items, lang=lang)
    if not prompt:
        return None
    text = _groq_generate(prompt)
    if not text:
        return None
    return _parse_lines(text, max_items)


def _openai_tips(topic, data, max_items, lang="uz"):
    prompt = _build_prompt(topic, data, max_items, lang=lang)
    if not prompt:
        return None
    text = _openai_generate(prompt)
    if not text:
        return None
    return _parse_lines(text, max_items)


def _anthropic_tips(topic, data, max_items, lang="uz"):
    prompt = _build_prompt(topic, data, max_items, lang=lang)
    if not prompt:
        return None
    text = _anthropic_generate(prompt)
    if not text:
        return None
    return _parse_lines(text, max_items)


def _model_candidates():
    primary = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash-001")
    fallback = getattr(settings, "GEMINI_MODEL_FALLBACK", "")
    models = []
    for value in (primary, fallback):
        if value and value not in models:
            models.append(value)

    api_key = getattr(settings, "GEMINI_API_KEY", "") or ""
    if not api_key:
        return models

    available = _list_models(api_key)
    if not available:
        return models

    filtered = [m for m in models if m in available]
    if filtered:
        return filtered

    picked = _pick_best_model(available)
    return [picked] if picked else models


def _list_models(api_key):
    now = time.time()
    if _MODELS_CACHE["models"] and _MODELS_CACHE["expires"] > now:
        return _MODELS_CACHE["models"]

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": api_key}
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    models = []
    for item in body.get("models", []):
        methods = item.get("supportedGenerationMethods") or item.get("supported_generation_methods") or []
        if "generateContent" not in methods:
            continue
        name = item.get("name", "")
        if name.startswith("models/"):
            name = name.split("/", 1)[1]
        if name:
            models.append(name)

    _MODELS_CACHE["models"] = models
    _MODELS_CACHE["expires"] = now + _MODELS_CACHE_TTL
    return models


def _pick_best_model(available):
    if not available:
        return None
    for keyword in ("flash", "pro"):
        for name in available:
            if keyword in name:
                return name
    return available[0] if available else None


def _extract_text(body):
    if not isinstance(body, dict):
        return ""
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(part.get("text"))
        elif isinstance(part, str):
            texts.append(part)
    return "".join(texts).strip()


def _gemini_generate(prompt, temperature=0.35, max_tokens=600):
    api_key = getattr(settings, "GEMINI_API_KEY", "") or ""
    if not api_key:
        return None
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    for model in _model_candidates():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=6) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return _extract_text(body)
        except Exception:
            continue
    return None


def _gemini_generate_with_error(prompt, temperature=0.6, max_tokens=800):
    api_key = getattr(settings, "GEMINI_API_KEY", "") or ""
    if not api_key:
        return None, "API key yo'q"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    last_error = None
    for model in _model_candidates():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = _extract_text(body)
            return (text or None), None
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                last_error = f"Model {model}: HTTP {e.code}: {err_body[:200]}"
            except Exception:
                last_error = f"Model {model}: HTTP {e.code}"
            continue
        except urllib.error.URLError as e:
            last_error = f"Network error: {getattr(e, 'reason', e)}"
            continue
        except Exception as e:
            last_error = f"Unknown error: {e}"
            continue

    return None, last_error or "AI xatosi"


def _groq_generate(prompt, temperature=0.35, max_tokens=600):
    api_key = getattr(settings, "GROQ_API_KEY", "") or ""
    if not api_key:
        return None
    model = getattr(settings, "GROQ_MODEL", "llama-3.1-8b-instant") or "llama-3.1-8b-instant"
    base_url = getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1") or "https://api.groq.com/openai/v1"
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception:
        return None


def _groq_generate_with_error(prompt, temperature=0.6, max_tokens=800):
    api_key = getattr(settings, "GROQ_API_KEY", "") or ""
    if not api_key:
        return None, "API key yo'q"
    model = getattr(settings, "GROQ_MODEL", "llama-3.1-8b-instant") or "llama-3.1-8b-instant"
    base_url = getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1") or "https://api.groq.com/openai/v1"
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return (text or None), None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            return None, f"HTTP {e.code}: {err_body[:200]}"
        except Exception:
            return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"Network error: {getattr(e, 'reason', e)}"
    except Exception as e:
        return None, f"Unknown error: {e}"


def _openai_generate(prompt, temperature=0.35, max_tokens=600):
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        return None
    model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    base_url = getattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1"
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception:
        return None


def _openai_generate_with_error(prompt, temperature=0.6, max_tokens=800):
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        return None, "API key yo'q"
    model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    base_url = getattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1"
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return (text or None), None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            return None, f"HTTP {e.code}: {err_body[:200]}"
        except Exception:
            return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"Network error: {getattr(e, 'reason', e)}"
    except Exception as e:
        return None, f"Unknown error: {e}"


def _anthropic_extract_text(body):
    if not isinstance(body, dict):
        return ""
    parts = body.get("content") or []
    texts = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(part.get("text"))
        elif isinstance(part, str):
            texts.append(part)
    return "".join(texts).strip()


def _anthropic_generate(prompt, temperature=0.35, max_tokens=600):
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key:
        return None
    model = getattr(settings, "ANTHROPIC_MODEL", "claude-3-haiku-20240307") or "claude-3-haiku-20240307"
    base_url = getattr(settings, "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1") or "https://api.anthropic.com/v1"
    url = base_url.rstrip("/") + "/messages"
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    try:
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return _anthropic_extract_text(body)
    except Exception:
        return None


def _anthropic_generate_with_error(prompt, temperature=0.6, max_tokens=800):
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key:
        return None, "API key yo'q"
    model = getattr(settings, "ANTHROPIC_MODEL", "claude-3-haiku-20240307") or "claude-3-haiku-20240307"
    base_url = getattr(settings, "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1") or "https://api.anthropic.com/v1"
    url = base_url.rstrip("/") + "/messages"
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    try:
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = _anthropic_extract_text(body)
        return (text or None), None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            return None, f"HTTP {e.code}: {err_body[:200]}"
        except Exception:
            return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"Network error: {getattr(e, 'reason', e)}"
    except Exception as e:
        return None, f"Unknown error: {e}"


def chat_reply(message, context=None, history=None, lang=None):
    """AI bilan chat javobi (AI)."""
    history = history or []
    context = context or {}

    prompt = _build_chat_prompt(message, context, history, lang=lang)
    preferred = _normalize_provider(getattr(settings, "AI_PROVIDER", ""))
    providers = [preferred] if preferred and preferred != "auto" else _provider_candidates()
    last_error = None

    if prompt:
        for provider in providers:
            if provider == "groq":
                text, err = _groq_generate_with_error(prompt, temperature=0.6, max_tokens=800)
            elif provider == "openai":
                text, err = _openai_generate_with_error(prompt, temperature=0.6, max_tokens=800)
            elif provider == "anthropic":
                text, err = _anthropic_generate_with_error(prompt, temperature=0.6, max_tokens=800)
            elif provider == "gemini":
                text, err = _gemini_generate_with_error(prompt, temperature=0.6, max_tokens=800)
            else:
                continue

            if text:
                return _clean_chat(text), provider, None
            if err:
                last_error = err

        error_msg = last_error or ("AI provider topilmadi" if not providers else "AI xatosi")
    else:
        error_msg = "Prompt build failed"

    if providers and any(_provider_has_key(p) for p in providers):
        source = "fallback"
    else:
        source = "offline"
    return _fallback_chat_reply(message, context, history, lang=lang), source, error_msg


def _build_chat_prompt(message, context, history, lang=None):
    lang = (lang or "uz").lower()
    nonce = random.randint(1000, 9999)
    if lang == "ru":
        base = (
            "Ты дружелюбный персональный финансовый помощник FinTrack. "
            "Отвечай только на русском языке, тёплым и понятным тоном. "
            "Дай полный, чёткий и полезный ответ. "
            "Используй контекст с цифрами, если нужно, и дай практические советы. "
            "В конце, если уместно, задай 1 короткий вопрос. "
            f"[Сессия: {nonce}]\n\n"
        )
    elif lang == "en":
        base = (
            "You are a friendly personal finance assistant in FinTrack. "
            "Reply only in English with a warm, clear tone. "
            "Give a complete, precise, and useful answer. "
            "Use the context numbers if needed and provide practical advice. "
            "End with 1 short question if it makes sense. "
            f"[Session: {nonce}]\n\n"
        )
    else:
        base = (
            "Sen FinTrack ilovasidagi do'stona shaxsiy moliya maslahatchiisan. "
            "Foydalanuvchi bilan o'zbek tilida, issiq va samimiy ohangda gaplash. "
            "Savolga to'liq, aniq va foydali javob ber. "
            "Agar moliyaviy ma'lumotlar kerak bo'lsa, kontekstdan foydalanib, "
            "konkret raqamlar va amaliy maslahatlar ber. "
            "Javob oxirida, agar mantiqiy bo'lsa, 1 ta qiziqarli savol qo'y. "
            "Javobni o'rtada uzmay, to'liq yoz. "
            f"[Sessiya: {nonce}]\n\n"
        )

    top_cat = context.get("top_expense_category") or "noma'lum"
    summary = (
        "Kontekst (ichki foydalanish, to'liq qaytarmang):\n"
        f"- Umumiy balans: {context.get('total_balance', 0):,} UZS\n"
        f"- Bu oy daromad: {context.get('monthly_income', 0):,} UZS\n"
        f"- Bu oy xarajat: {context.get('monthly_expense', 0):,} UZS\n"
        f"- Sof qoldiq: {context.get('net', 0):,} UZS\n"
        f"- Eng ko'p xarajat kategoriya: {top_cat}\n"
        f"- Limitga yaqin byudjetlar: {context.get('budgets_near_limit', 0)} ta\n"
        f"- Limitdan oshgan byudjetlar: {context.get('budgets_over_limit', 0)} ta\n"
        f"- Muddati o'tgan qarzlar: {context.get('overdue_debts', 0)} ta\n"
    )

    convo = "Suhbat tarixi:\n"
    for item in history[-8:]:
        role = "Foydalanuvchi" if item.get("role") == "user" else "AI"
        convo += f"{role}: {item.get('text','')}\n"

    user_line = f"Foydalanuvchi: {message}\nAI:"
    return base + summary + "\n" + convo + "\n" + user_line


def _clean_chat(text):
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _fallback_chat_reply(message, context, history, lang=None):
    lang = (lang or "uz").lower()
    if lang in ("ru", "en"):
        bal = context.get("total_balance", 0)
        inc = context.get("monthly_income", 0)
        exp = context.get("monthly_expense", 0)
        net = context.get("net", 0)

        def fmt(n):
            try:
                return f"{int(n):,}"
            except Exception:
                return str(n)

        if lang == "ru":
            return (
                f"Короткий срез: баланс {fmt(bal)} UZS, доход {fmt(inc)} UZS, расход {fmt(exp)} UZS, "
                f"чистый итог {fmt(net)} UZS. "
                "Если нужно, уточните: бюджет, расходы, долги или накопления?"
            )
        return (
            f"Quick snapshot: balance {fmt(bal)} UZS, income {fmt(inc)} UZS, expense {fmt(exp)} UZS, "
            f"net {fmt(net)} UZS. "
            "Ask me about budgets, expenses, debts, or savings."
        )
    msg = (message or "").lower()
    bal = context.get("total_balance", 0)
    inc = context.get("monthly_income", 0)
    exp = context.get("monthly_expense", 0)
    net = context.get("net", 0)
    top_cat = context.get("top_expense_category")
    near = context.get("budgets_near_limit", 0)
    over = context.get("budgets_over_limit", 0)
    overdue = context.get("overdue_debts", 0)

    def fmt(n):
        try:
            return f"{int(n):,}"
        except Exception:
            return str(n)

    if "byudjet" in msg:
        parts = [f"Byudjetlaringizni ko'rib chiqdim."]
        if over > 0:
            parts.append(f"{over} ta byudjet allaqachon limitdan oshib ketgan — bu kategoriyalardagi xarajatlarni qisqartirish zarur.")
        if near > 0:
            parts.append(f"Yana {near} ta byudjet limitga yaqinlashib qolgan, ularga diqqat qiling.")
        if over == 0 and near == 0:
            parts.append("Barcha byudjetlar me'yorida, davom eting!")
        parts.append("Qaysi kategoriya byudjeti ko'proq tashvish qilmoqda?")

    elif "qarz" in msg or "haqdor" in msg:
        parts = ["Qarzlaringiz haqida ma'lumot berdim."]
        if overdue > 0:
            parts.append(f"Hozir {overdue} ta qarzning muddati o'tib ketgan — ularni imkon qadar tezroq hal qilish sog'lom moliyaviy holat uchun muhim.")
        else:
            parts.append("Muddati o'tgan qarzingiz yo'q — bu yaxshi ko'rsatkich!")
        parts.append("Qarz jadvalini tuzib, oylik to'lovlarni aniq belgilab olishni tavsiya qilaman. Qaysi qarzdan boshlashni xohlaysiz?")

    elif "daromad" in msg or "maosh" in msg or "topish" in msg:
        parts = [f"Bu oy daromadingiz {fmt(inc)} UZS bo'lgan."]
        if inc > 0:
            savings_pct = round((net / inc) * 100) if inc > 0 else 0
            if savings_pct >= 20:
                parts.append(f"Daromadingizning {savings_pct}% ini tejayapsiz — bu ajoyib natija!")
            elif savings_pct > 0:
                parts.append(f"Daromadingizning {savings_pct}% ini tejayapsiz. Moliyaviy maqsadlar uchun kamida 20% tejashga harakat qiling.")
            else:
                parts.append("Hozircha daromadingizdan tejama chiqmayapti. Kichik xarajatlarni qisqartirib, oy boshida darhol jamg'arma ajratishni maslahat beraman.")
        parts.append("Daromad manbalaringizni ko'paytirish haqida o'ylayapsizmi?")

    elif "xarajat" in msg or "sarf" in msg:
        parts = [f"Bu oy xarajatlaringiz jami {fmt(exp)} UZS bo'lgan."]
        if top_cat:
            parts.append(f"Eng ko'p sarf {top_cat} kategoriyasiga ketmoqda — bu bo'yicha limit qo'yishni ko'rib chiqing.")
        if net < 0:
            parts.append(f"Xarajat daromaddan {fmt(abs(net))} UZS oshib ketgan. Keraksiz xarajatlarni topib, kesishni maslahat beraman.")
        else:
            parts.append(f"Sof qoldiq {fmt(net)} UZS — ijobiy holat.")
        parts.append("Qaysi xarajat kategoriyasini optimallashtirmoqchisiz?")

    elif "jamg'arma" in msg or "tejash" in msg or "yig'ish" in msg:
        parts = ["Jamg'arma bo'yicha maslahat beray."]
        if net > 0:
            rec = int(net * 0.3)
            parts.append(f"Hozirgi sof qoldiqingiz {fmt(net)} UZS. Bundan kamida {fmt(rec)} UZS ni jamg'arma hisobiga o'tkazishingiz mumkin.")
        else:
            parts.append("Hozir sof qoldiq manfiy, shuning uchun avval xarajatlarni kamaytirish kerak.")
        parts.append("Jamg'armani oy boshida darhol ajratish eng samarali usul. Oylik qancha miqdorni tejashni maqsad qilmoqchisiz?")

    elif "balans" in msg or "hisob" in msg or "pul" in msg:
        parts = [f"Umumiy balansingiz hozir {fmt(bal)} UZS."]
        parts.append(f"Bu oy daromad {fmt(inc)} UZS, xarajat {fmt(exp)} UZS, sof qoldiq {fmt(net)} UZS.")
        if top_cat:
            parts.append(f"Eng katta xarajat yo'nalishi: {top_cat}.")
        parts.append("Moliyaviy ahvolingiz haqida qaysi jihatini chuqurroq tahlil qilay?")

    else:
        parts = [f"Moliyaviy ahvolingizga qisqacha nazar: balans {fmt(bal)} UZS, bu oy sof qoldiq {fmt(net)} UZS."]
        if top_cat:
            parts.append(f"Eng ko'p xarajat {top_cat} bo'limiga ketmoqda.")
        if over > 0 or near > 0:
            parts.append(f"Byudjetlarda {over} ta oshgan, {near} ta yaqinlashgan holat bor — diqqat talab qiladi.")
        if overdue > 0:
            parts.append(f"Muddati o'tgan {overdue} ta qarz ham mavjud.")
        parts.append("Byudjet, xarajatlar, qarzlar yoki jamg'arma — qaysi mavzu bo'yicha yordam kerak?")

    return "\n\n".join(parts)


def _build_prompt(topic, data, max_items, lang="uz"):
    nonce = random.randint(1000, 9999)

    lang = (lang or "uz").lower()
    if lang == "ru":
        rule = (
            f"ПРАВИЛО: Напиши ровно {max_items} отдельных строк. "
            "Каждая строка = одна конкретная рекомендация или вывод. "
            "Пиши по делу; числа используй только если нужно. "
            "Не используй маркеры списка ('-', '*', числа). "
            "Каждая строка с новой строки. Пиши на русском. "
            f"[{nonce}]"
        )
    elif lang == "en":
        rule = (
            f"RULE: Write exactly {max_items} separate lines. "
            "Each line = one concrete recommendation or conclusion. "
            "Focus on what to do; use numbers only if needed. "
            "Do not use list markers ('-', '*', numbers). "
            "Each line on a new line. Write in English. "
            f"[{nonce}]"
        )
    else:
        rule = (
            f"QOIDA: Aynan {max_items} ta alohida satr yoz. "
            "Har satr = bitta original tavsiya yoki xulosa. "
            "Asosan NIMA QILISH KERAKLIGINI yoz, raqamlarni faqat kerak bo'lsa ishlatgin. "
            "Umumiy gaplar ('xarajatlarni kamaytiring', 'tejang') emas ? ANIQ, KONKRET maslahat ber. "
            "Ro'yxat belgisi ('-', '*', raqam) ISHLATMA. "
            "Har satr yangi qatorda. O'zbek tilida. "
            f"[{nonce}]"
        )

    if topic == "dashboard":
        inc = data.get("monthly_income", 0)
        exp = data.get("monthly_expense", 0)
        net = data.get("net", 0)
        ratio = data.get("expense_ratio_pct", 0)
        savings = data.get("savings_rate_pct", 0)
        top_cat = data.get("top_expense_category") or "noma'lum"
        over = data.get("budgets_over_limit", 0)
        near = data.get("budgets_near_limit", 0)
        overdue = data.get("overdue_debts", 0)

        situation = []
        if ratio >= 90:
            situation.append(f"xarajatlar daromadning {ratio}%ini tashkil qilmoqda — bu xavfli daraja")
        elif ratio >= 70:
            situation.append(f"xarajatlar daromadning {ratio}%i — nazorat kerak")
        if savings >= 20:
            situation.append(f"jamg'arma ulushi {savings}% — yaxshi natija")
        elif savings > 0:
            situation.append(f"jamg'arma ulushi atigi {savings}% — oshirish kerak")
        else:
            situation.append("jamg'arma yo'q — xarajatlardan ortiq qoldirish kerak")
        if over > 0:
            situation.append(f"{over} ta byudjet limitdan oshib ketgan")
        if near > 0:
            situation.append(f"{near} ta byudjet limitga yaqin")
        if overdue > 0:
            situation.append(f"{overdue} ta qarzning muddati o'tgan")
        if top_cat != "noma'lum":
            situation.append(f"eng katta xarajat yo'nalishi: {top_cat}")

        prompt_body = (
            f"Foydalanuvchining moliyaviy holati: {'; '.join(situation)}.\n"
            f"Bu oy sof qoldiq: {'ijobiy' if net >= 0 else 'manfiy'}.\n\n"
            "Yuqoridagi holatga qarab tavsiyalar ber:\n"
            f"Birinchi {max_items - 1} ta satr: konkret amaliy tavsiya (nima qilish kerak — xarajat qisqartirish, byudjet tuzatish, qarz to'lash, jamg'arma va h.k.).\n"
            "Oxirgi satr: foydalanuvchini o'ylantiruvchi 1 ta savol.\n"
        )

    elif topic == "budgets":
        count = data.get("count", 0)
        over = data.get("over_limit", 0)
        near = data.get("near_limit", 0)
        avg = data.get("avg_pct", 0)
        max_p = data.get("max_pct", 0)
        planned = data.get("total_planned", 0)
        actual = data.get("total_actual", 0)
        diff = actual - planned

        situation = []
        if over > 0:
            situation.append(f"{over} ta byudjet limitdan oshgan")
        if near > 0:
            situation.append(f"{near} ta byudjet 75%+ ga yetgan")
        if avg >= 80:
            situation.append(f"o'rtacha bajarilish {avg}% — kritik daraja")
        elif avg >= 50:
            situation.append(f"o'rtacha bajarilish {avg}%")
        if max_p >= 100:
            situation.append(f"biror kategoriya {max_p}%ga yetgan")
        if diff > 0:
            situation.append(f"reja summasidan {int(diff):,} UZS oshib ketilgan")
        elif diff < 0:
            situation.append(f"rejadan {int(abs(diff)):,} UZS tejab qolingan")

        prompt_body = (
            f"Byudjet holati ({count} ta byudjet): {'; '.join(situation) if situation else 'barcha byudjetlar yaxshi'}.\n\n"
            f"Birinchi {max_items - 1} ta satr: byudjetlarni yaxshilash bo'yicha aniq tavsiyalar.\n"
            "Oxirgi satr: foydalanuvchiga savol.\n"
        )

    elif topic == "debts":
        given = data.get("total_given", 0)
        taken = data.get("total_taken", 0)
        overdue = data.get("overdue", 0)
        net_debt = data.get("net_debt", 0)
        given_cnt = data.get("given_count", 0)
        taken_cnt = data.get("taken_count", 0)

        situation = []
        if overdue > 0:
            situation.append(f"{overdue} ta qarzning muddati o'tib ketgan — shoshilinch")
        if taken > given:
            situation.append(f"to'lash kerak bo'lgan qarz ({int(taken):,} UZS) olish kerakdan ko'p")
        elif given > taken:
            situation.append(f"olish kerak bo'lgan summa ({int(given):,} UZS) ko'p — undirish kerak")
        if taken_cnt > 3:
            situation.append(f"{taken_cnt} ta kreditdan to'lov borligini nazorat qilish kerak")

        default_debt = "qarzlar me'yorida"
        prompt_body = (
            f"Qarz holati: {'; '.join(situation) if situation else default_debt}.\n\n"
            f"Birinchi {max_items - 1} ta satr: qarzlarni boshqarish bo'yicha amaliy tavsiyalar.\n"
            "Oxirgi satr: foydalanuvchiga savol.\n"
        )

    elif topic == "analytics":
        inc = data.get("total_income", 0)
        exp = data.get("total_expense", 0)
        net = data.get("net", 0)
        ratio = data.get("expense_ratio_pct", 0)
        top_cat = data.get("top_expense_category") or "noma'lum"
        period_label = {"daily": "bugungi", "weekly": "haftalik", "monthly": "oylik", "yearly": "yillik"}.get(
            data.get("period", "monthly"), "oylik"
        )

        situation = []
        if ratio >= 90:
            situation.append(f"{period_label} xarajatlar daromadning {ratio}%i — xavfli")
        elif ratio >= 70:
            situation.append(f"{period_label} xarajat ulushi {ratio}% — nazorat kerak")
        else:
            situation.append(f"{period_label} xarajat ulushi {ratio}% — qoniqarli")
        if net < 0:
            situation.append("sof qoldiq manfiy — zudlik bilan choralar kerak")
        if top_cat != "noma'lum":
            situation.append(f"eng ko'p sarf {top_cat}ga ketmoqda")

        prompt_body = (
            f"Tahlil: {'; '.join(situation)}.\n\n"
            f"Birinchi {max_items - 1} ta satr: trend va ko'rsatkichlarga asoslangan amaliy tavsiyalar.\n"
            "Oxirgi satr: foydalanuvchiga analitik savol.\n"
        )

    elif topic == "transactions":
        count = data.get("count", 0)
        exp = data.get("total_expense", 0)
        inc = data.get("total_income", 0)
        avg_exp = data.get("avg_expense", 0)
        top_cat = data.get("top_category") or "noma'lum"
        exp_cnt = data.get("expense_count", 0)

        situation = []
        if top_cat != "noma'lum":
            situation.append(f"eng ko'p sarf {top_cat} kategoriyasiga ketmoqda")
        if avg_exp > 500000:
            situation.append(f"o'rtacha xarajat {int(avg_exp):,} UZS — yirik operatsiyalar bor")
        if exp_cnt > count * 0.7:
            situation.append("tranzaksiyalarning ko'pi xarajat — daromad manbalari kam")
        if exp > inc:
            situation.append("xarajat daromaddan oshib ketmoqda")

        prompt_body = (
            f"Tranzaksiyalar ({count} ta): {'; '.join(situation) if situation else 'normal holat'}.\n\n"
            f"Birinchi {max_items - 1} ta satr: tranzaksiyalar asosida tejamkorlik bo'yicha tavsiyalar.\n"
            "Oxirgi satr: foydalanuvchiga savol.\n"
        )

    else:
        return None

    return rule + prompt_body


def _parse_lines(text, max_items):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("-*0123456789.) \t").strip()
        if line:
            lines.append(line)

    # Agar bir qator bo'lsa, faqat jumlalarga bo'l (vergul/nuqtaverguldan emas)
    if len(lines) <= 1:
        blob = (lines[0] if lines else text).strip()
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", blob) if p.strip()]
        lines = parts or lines

    return lines[:max_items]


def _normalize_tip(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _dedupe(items, max_items):
    """Bir xil tavsiyalarni olib tashlaydi (history yo'q)."""
    out = []
    seen = set()
    for t in items or []:
        key = _normalize_tip(t)
        if not key or key in seen:
            continue
        out.append(t)
        seen.add(key)
        if len(out) >= max_items:
            break
    return out


def _fallback_tips(topic, data, max_items, lang="uz"):
    lang = (lang or "uz").lower()
    if lang in ("ru", "en"):
        from core.i18n import translate as _tr

        def fmt(n):
            try:
                return f"{int(n):,}"
            except Exception:
                return str(n)

        tips = []

        def add(uz_key, **kwargs):
            translated = _tr(uz_key, lang)
            if kwargs:
                try:
                    translated = translated.format(**kwargs)
                except Exception:
                    pass
            tips.append(translated)

        if topic == "dashboard":
            inc = data.get("monthly_income", 0)
            exp = data.get("monthly_expense", 0)
            net = data.get("net", 0)
            ratio = data.get("expense_ratio_pct", 0)
            savings = data.get("savings_rate_pct", 0)
            over = data.get("budgets_over_limit", 0)
            near = data.get("budgets_near_limit", 0)
            overdue = data.get("overdue_debts", 0)
            add("Daromad {income} UZS, xarajat {expense} UZS — xarajatlarni daromadning 70-80% oralig'ida ushlab turing.",
                income=fmt(inc), expense=fmt(exp))
            # Use translated static tips
            if savings < 10 and inc > 0:
                add("Tejash stavkasi past — oy boshida 10% jamg'arma ajrating.")
            elif savings >= 20:
                add("Tejash darajasi yaxshi — shu tempni saqlang.")
            if ratio >= 90:
                add("Xarajatlar daromadga yaqin — byudjetni siqish kerak.")
            if overdue > 0:
                add("Qarz yuklama yuqori — to'lov rejasini kuchaytiring.")
            add("Xarajat/daromad barqaror emas — barqarorlashtirish kerak.")
        elif topic == "budgets":
            over = data.get("over_limit", 0)
            near = data.get("near_limit", 0)
            avg = data.get("avg_pct", 0)
            count = data.get("count", 0)
            if over > 0 or avg >= 80:
                add("Xarajatlar daromaddan yuqori — 1 ta ixtiyoriy kategoriyani vaqtincha cheklang.")
            if near > 0:
                add("Xarajatlar daromadga yaqin — byudjetni siqish kerak.")
            if count == 0:
                add("Daromadingizning kamida 10% ini oy boshida jamg'armaga ajrating.")
            add("Xarajat/daromad barqaror emas — barqarorlashtirish kerak.")
        elif topic == "debts":
            overdue = data.get("overdue", 0)
            taken = data.get("total_taken", 0)
            given = data.get("total_given", 0)
            if overdue > 0:
                add("Qarz yuklama yuqori — to'lov rejasini kuchaytiring.")
            if taken > given:
                add("Xarajatlar daromaddan yuqori — 1 ta ixtiyoriy kategoriyani vaqtincha cheklang.")
            add("Tejash darajasi yaxshi — shu tempni saqlang.")
        elif topic == "analytics":
            inc = data.get("total_income", 0)
            exp = data.get("total_expense", 0)
            net = data.get("net", 0)
            ratio = data.get("expense_ratio_pct", 0)
            if net < 0 or ratio >= 80:
                add("Xarajatlar daromadga yaqin — byudjetni siqish kerak.")
            elif ratio <= 50 and inc > 0:
                add("Tejash darajasi yaxshi — shu tempni saqlang.")
            add("Xarajat/daromad barqaror emas — barqarorlashtirish kerak.")
        elif topic == "transactions":
            exp = data.get("total_expense", 0)
            inc = data.get("total_income", 0)
            if exp > inc and inc > 0:
                add("Xarajatlar daromaddan yuqori — 1 ta ixtiyoriy kategoriyani vaqtincha cheklang.")
            add("Tejash stavkasi past — oy boshida 10% jamg'arma ajrating.")
            add("Xarajat/daromad barqaror emas — barqarorlashtirish kerak.")
        else:
            add("Tejash stavkasi past — oy boshida 10% jamg'arma ajrating.")
            add("Xarajat/daromad barqaror emas — barqarorlashtirish kerak.")

        # Remove empty/duplicate
        seen = set()
        result = []
        for t in tips:
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return result[:max_items]

    """AI API ishlamasa — ma'lumotlarni tahlil qilib, amaliy tavsiyalar qaytaradi."""
    tips = []

    def add(msg):
        if msg:
            tips.append(msg)

    def fmt(num):
        try:
            return f"{int(num):,}"
        except Exception:
            return str(num)

    if topic == "dashboard":
        inc = data.get("monthly_income", 0)
        exp = data.get("monthly_expense", 0)
        net = data.get("net", 0)
        ratio = data.get("expense_ratio_pct", 0)
        savings = data.get("savings_rate_pct", 0)
        top_cat = data.get("top_expense_category")
        over = data.get("budgets_over_limit", 0)
        near = data.get("budgets_near_limit", 0)
        overdue = data.get("overdue_debts", 0)

        # Eng dolzarb muammodan boshlash
        if overdue > 0:
            add(f"Muddati o'tgan {overdue} ta qorzingiz bor — bugun egalariga xabar bering yoki to'lovni rejalashtiring.")
        if over > 0:
            add(f"{over} ta byudjet limitdan oshib ketgan — shu kategoriyalardagi xarajatlarni shu haftada qisqartiring.")
        if near > 0:
            add(f"{near} ta byudjet chegaraga yaqinlashdi — oy oxirigacha ehtiyot bo'ling.")

        # Jamg'arma va tejamkorlik
        if ratio >= 90:
            add("Xarajatlaringiz daromadingizning deyarli hammasini yeb qo'ymoqda — 1 ta keraksiz xarajatni toping va bugun to'xtating.")
        elif ratio >= 70:
            add(f"Xarajat ulushi yuqori. {top_cat or 'Asosiy kategoriya'}da ozgina tejasangiz, oyda ko'proq qoldiq bo'ladi.")
        
        if savings < 10 and inc > 0:
            rec = max(int(inc * 0.1), 10000)
            add(f"Oy boshida darhol {fmt(rec)} UZS ajratib, jamg'arma hisobiga o'tkazing — «qolsa tejaman» usuli ishlamaydi.")
        elif savings >= 20:
            add("Jamg'arma ulushingiz yaxshi — uni foizli hisob yoki investitsiyaga yo'naltirish vaqti keldi.")

        if top_cat:
            add(f"«{top_cat}» kategoriyasiga byudjet qo'ying — limit bo'lmasa, sezmasdan oshib ketiladi.")

        if net < 0:
            add(f"Bu oy xarajat daromaddan {fmt(abs(net))} UZS oshib ketdi — keyingi oy uchun hozirdanoq 3 ta ixtiyoriy xarajatni aniqlab, ularga limit qo'ying.")
        elif net > 0:
            add(f"Bu oylik {fmt(net)} UZS qoldiqning kamida 30%ini keyingi oy uchun favqulodda fond sifatida saqlang.")

        add("Moliyaviy qaysi maqsadga oy oxirigacha erishmoqchisiz?")

    elif topic == "budgets":
        over = data.get("over_limit", 0)
        near = data.get("near_limit", 0)
        avg = data.get("avg_pct", 0)
        count = data.get("count", 0)
        planned = data.get("total_planned", 0)
        actual = data.get("total_actual", 0)

        if over > 0:
            add(f"Limitdan oshgan {over} ta byudjetni ko'rib, ya rea summani oshiring, yoki xarajatni kamayting — oraliq yo'q.")
        if near > 0:
            add(f"{near} ta byudjet 75% dan oshgan — shu kategoriyalarda oy oxirigacha faqat zarur xarajat qiling.")
        if avg >= 80:
            add("Umumiy bajarilish juda yuqori — byudjet limitlarini 15-20% ga oshiring yoki xarajatlarni keskin qisqartiring.")
        elif avg < 30 and count > 0:
            add("Byudjetlaringiz hali juda past — yaxshi, lekin haqiqiy xarajat trendini aniqlash uchun 2-3 oy kuzating.")
        if actual > planned:
            add(f"Reja summasidan {fmt(actual - planned)} UZS oshib ketildi — keyingi oy rejani realistik qiling.")
        elif planned > 0 and actual < planned * 0.3:
            add("Xarajatlar rejadan ancha past — byudjetlar sizning haqiqiy xarajat modelingizni aks ettirmayapti, yangilang.")
        if count == 0:
            add("Birorta byudjet yo'q — hech bo'lmasa 3 ta asosiy kategoriya (oziq-ovqat, transport, ko'ngilochar) uchun limit qo'ying.")

        add("Qaysi kategoriyada eng ko'p ortiqcha xarajat ketmoqda?")

    elif topic == "debts":
        given = data.get("total_given", 0)
        taken = data.get("total_taken", 0)
        overdue = data.get("overdue", 0)
        net_debt = data.get("net_debt", 0)
        given_cnt = data.get("given_count", 0)
        taken_cnt = data.get("taken_count", 0)

        if overdue > 0:
            add(f"Muddati o'tgan {overdue} ta qarz bor — bugun egalariga murojaat qiling, kechikish munosabatlarni buzadi.")
        if taken > given:
            diff = int(taken - given)
            add(f"To'lash kerak bo'lgan qarz ko'proq — har oyda qo'shimcha {fmt(diff // 6)} UZS ajratib, 6 oyda to'liq yoping.")
        elif given > 0:
            add(f"Bergan qarzlaringizni eslatib turing — do'stona munosabatda ham belgilangan muddat muhim.")
        if taken_cnt > 2:
            add("Bir nechta qarzni boshqarish uchun ularni yozib, eng katta foizlisidan boshlang (avalanche usuli).")
        if taken == 0 and given == 0:
            add("Hozircha qarzlaringiz yo'q — bu ajoyib holat, shunday davom eting.")
        elif net_debt > 0:
            add("Qarz yukini kamaytirish uchun har oy daromadingizning 10-15%ini qarz to'loviga ajrating.")

        add("Qaysi qarzni birinchi yopish qulay?")

    elif topic == "analytics":
        inc = data.get("total_income", 0)
        exp = data.get("total_expense", 0)
        net = data.get("net", 0)
        ratio = data.get("expense_ratio_pct", 0)
        top_cat = data.get("top_expense_category")
        period = data.get("period", "monthly")

        if net < 0:
            add(f"Xarajat daromaddan {fmt(abs(net))} UZS oshib ketdi — shu davrdagi eng yirik 3 ta xarajatni aniqlang va keyin takrorlanmasligini ta'minlang.")
        elif ratio >= 80:
            add(f"Xarajat ulushi {ratio}% — byudjetning 50-60% ga tushirish uchun 1-2 ta katta kategoriyani optimallashtiring.")
        elif ratio <= 50 and inc > 0:
            add(f"Xarajat ulushi {ratio}% — yaxshi! Ortiqcha qoldiqni investitsiya yoki favqulodda fondga yo'naltiring.")

        if top_cat:
            add(f"«{top_cat}» kategoriyasi eng ko'p «yemoqda» — bu xarajatning bir qismini avtomatlashtirib, belgilangan limitda ushlab turing.")

        if period == "yearly":
            add("Yillik tahlildan ko'rinadi — bir tekis emas, maksimal xarajat oylarini aniqlang va ular uchun oldindan reja tuzing.")
        elif period == "monthly":
            add("Oylik trendni haftalik kuzating — oxirgi haftada xarajat keskin oshsa, darhol to'xtatish osonroq.")

        add("Qaysi oy/davr moliyaviy jihatdan eng qiyinchili bo'ldi?")

    elif topic == "transactions":
        count = data.get("count", 0)
        exp = data.get("total_expense", 0)
        inc = data.get("total_income", 0)
        avg_exp = data.get("avg_expense", 0)
        avg_inc = data.get("avg_income", 0)
        top_cat = data.get("top_category")
        exp_cnt = data.get("expense_count", 0)
        inc_cnt = data.get("income_count", 0)

        if top_cat:
            add(f"«{top_cat}» kategoriyasiga eng ko'p pul ketmoqda — unga oylik limit qo'ying, har xarid qilishdan oldin qoldiqni tekshiring.")
        if exp > inc and inc > 0:
            add("Xarajat daromaddan oshib ketmoqda — eng oddiy usul: 24 soat qoida — yirik xarid qilishdan oldin bir kun kuting.")
        if avg_exp > 500000:
            add(f"O'rtacha xarajat {fmt(avg_exp)} UZS — yirik to'lovlar bor. Ularga oldindan reja tuzilganmi?")
        if exp_cnt > 0 and inc_cnt == 0:
            add("Faqat xarajat tranzaksiyalari qayd etilgan — daromadlarni ham kiritishni unutmang, to'liq rasm ko'rinmaydi.")
        if count < 5:
            add("Juda kam tranzaksiya qayd etilgan — har xaridni hatto kichigini ham kiritish odatga aylantiring, oy oxirida taajjublanmaysiz.")
        elif count > 50:
            add(f"{count} ta tranzaksiyaning aksariyati xarajat — siz ko'p va tez-tez sarflayapsiz, oylik limit belgilang.")

        add("Qaysi xarajat siz kutmaganda ko'proq chiqqan?")

    else:
        add("Moliyaviy ma'lumotlar bor — tahlil qilishga tayyorman.")
        add("Qaysi bo'limni ko'rib chiqaylik?")

    question = tips[-1] if tips else None
    body = _dedupe(tips[:-1] if question else tips, max_items)
    random.shuffle(body)
    result = body + ([question] if question else [])
    return result[:max_items]


# =============================
# FinTrack Smart AI Engine
# =============================

_CATEGORY_KEYWORDS = {
    "Transport": [
        "taxi", "taksi", "uber", "yandex", "metro", "meteo", "bus", "avtobus",
        "автобус", "метро", "поезд", "train", "tram", "transport",
        "benzin", "yoqilg", "fuel", "gasoline", "parking", "parkovka",
        "mashina", "avto", "auto", "car",
    ],
    "Food": [
        "ovqat", "oziq", "oziq ovqat", "bozor", "dokon", "supermarket", "market",
        "non", "gosht", "go'sht", "meat", "bread", "lunch", "dinner", "breakfast",
        "burger", "pizza", "restaurant", "restoran", "kafe", "cafe", "fastfood",
        "kfc", "sushi", "lavash", "shawarma", "food", "еда", "продукт", "продукты",
        "ресторан", "кафе", "столовая", "delivery", "dostavka",
    ],
    "Utilities": [
        "kommunal", "electricity", "электр", "electr", "gaz", "gas", "suv", "water",
        "utility", "utilities", "коммунал", "коммуналка", "квитанция", "оплата",
        "internet", "telefon", "phone", "mobile", "sim", "wifi", "isp",
    ],
    "Shopping": [
        "kiyim", "koylak", "ko'ylak", "poyabzal", "shoe", "shoes", "clothes",
        "shopping", "магазин", "покупка", "купил", "mall", "kosmetika",
        "cosmetics", "аксессуар", "gift",
    ],
    "Health": [
        "dorixona", "dori", "apteka", "аптека", "hospital", "clinic", "klinika",
        "doctor", "shifokor", "medical", "med", "dentist", "stomatolog",
        "health", "анализ", "лекарство",
    ],
    "Education": [
        "ta'lim", "talim", "kurs", "dars", "university", "университет",
        "maktab", "school", "education", "kitob", "book", "учеб", "урок",
        "training", "seminar", "course",
    ],
    "Entertainment": [
        "kino", "movie", "cinema", "konsert", "concert", "театр", "theatre",
        "game", "o'yin", "games", "music", "музыка", "club", "bar",
        "ko'ngilochar", "entertainment",
    ],
    "Subscriptions": [
        "subscription", "подпис", "abonement", "abonent", "premium", "netflix",
        "spotify", "youtube", "telegram premium", "google one", "icloud",
        "cloud", "hosting", "renewal", "membership", "yandex plus",
    ],
}

_CATEGORY_DB_MAP = {
    "Transport": ["Transport", "Transportlar"],
    "Food": ["Oziq-ovqat", "Ovqat", "Food"],
    "Utilities": ["Kommunal", "Internet/Telefon", "Utilities"],
    "Shopping": ["Kiyim", "Uy-joy", "Shopping"],
    "Health": ["Salomatlik", "Health"],
    "Education": ["Ta'lim", "Education"],
    "Entertainment": ["Ko'ngilochar", "Entertainment"],
    "Subscriptions": ["Internet/Telefon", "Kommunal", "Subscriptions"],
    "Other": ["Boshqa xarajat", "Other"],
}


def _normalize_text(text):
    text = (text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text):
    return _normalize_text(text).split()


def _ngrams(tokens, n=2):
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def _best_keyword_score(norm_text, tokens, keywords):
    best = 0.0
    if not norm_text:
        return best
    grams = tokens + _ngrams(tokens, 2)
    for kw in keywords:
        kw_norm = _normalize_text(kw)
        if not kw_norm:
            continue
        if kw_norm in norm_text:
            return 1.0
        for g in grams:
            ratio = difflib.SequenceMatcher(None, kw_norm, g).ratio()
            if ratio > best:
                best = ratio
    return best


def classify_expense_description(description):
    """Return category key based on keywords + fuzzy matching."""
    norm = _normalize_text(description)
    if not norm:
        return "Other"
    tokens = norm.split()

    # Subscriptions override
    sub_score = _best_keyword_score(norm, tokens, _CATEGORY_KEYWORDS["Subscriptions"])
    if sub_score >= 0.88:
        return "Subscriptions"

    best_key = "Other"
    best_score = 0.0
    for key, keywords in _CATEGORY_KEYWORDS.items():
        if key == "Subscriptions":
            continue
        score = _best_keyword_score(norm, tokens, keywords)
        if score > best_score:
            best_score = score
            best_key = key

    return best_key if best_score >= 0.78 else "Other"


def resolve_category_for_user(user, category_key, category_type="expense", family=None):
    from django.db.models import Q
    from transactions.models import Category

    if family:
        qs = Category.objects.filter(Q(family=family) | Q(is_default=True))
    else:
        qs = Category.objects.filter(Q(user=user) | Q(is_default=True), family__isnull=True)
    if category_type:
        qs = qs.filter(Q(category_type=category_type) | Q(category_type="both"))

    for name in _CATEGORY_DB_MAP.get(category_key, []):
        cat = qs.filter(name__iexact=name).first()
        if cat:
            return cat

    # Fuzzy match to existing categories if names differ
    if qs.exists():
        best_cat = None
        best_ratio = 0.0
        for cat in qs:
            ratio = difflib.SequenceMatcher(None, category_key.lower(), cat.name.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_cat = cat
        if best_ratio >= 0.6:
            return best_cat

    return None


def auto_assign_category(user, description, family=None):
    key = classify_expense_description(description)
    return resolve_category_for_user(user, key, category_type="expense", family=family)


def _tx_scope(user, family=None, role=None):
    from transactions.models import Transaction
    from django.db.models import Q
    from core.models import FamilyMember
    qs = Transaction.objects.all()
    if family:
        if role in ("son", "daughter"):
            return qs.filter(family=family, user=user)
        member_ids = FamilyMember.objects.filter(family=family).values_list("user_id", flat=True)
        return qs.filter(
            Q(family=family) | Q(family__isnull=True, user_id__in=member_ids)
        )
    return qs.filter(user=user, family__isnull=True)


def _shift_month(year, month, delta):
    m = month + delta
    y = year
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return y, m


def analyze_spending_patterns(user, family=None, role=None, lang="uz"):
    """Return list of human-readable spending patterns."""
    from django.utils import timezone
    from django.db.models import Sum
    from core.i18n import translate as _tr

    lang = (lang or "uz").lower()
    insights = []
    today = timezone.now().date()
    cur_y, cur_m = today.year, today.month
    prev_y, prev_m = _shift_month(cur_y, cur_m, -1)

    cur_rows = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__year=cur_y, date__month=cur_m
    ).values("category__name").annotate(total=Sum("amount"))
    prev_rows = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__year=prev_y, date__month=prev_m
    ).values("category__name").annotate(total=Sum("amount"))

    other_label = _tr("Boshqa", lang)
    prev_map = {r["category__name"] or other_label: float(r["total"] or 0) for r in prev_rows}
    for r in cur_rows:
        name = r["category__name"] or other_label
        cur_total = float(r["total"] or 0)
        prev_total = prev_map.get(name, 0)
        if prev_total > 0 and cur_total > prev_total * 1.3:
            pct = int(((cur_total - prev_total) / prev_total) * 100)
            tpl = "Bu oy {category} xarajatlari o'tgan oyga nisbatan {percent}% ko'p."
            insights.append(_tr(tpl, lang).format(category=name, percent=pct))

    # Weekend vs weekday spending
    month_txs = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__year=cur_y, date__month=cur_m
    ).values("date", "amount")
    weekend_sum = 0.0
    weekday_sum = 0.0
    weekend_days = 0
    weekday_days = 0
    for row in month_txs:
        d = row["date"]
        if d.weekday() >= 5:
            weekend_sum += float(row["amount"] or 0)
            weekend_days += 1
        else:
            weekday_sum += float(row["amount"] or 0)
            weekday_days += 1
    if weekend_days and weekday_days:
        weekend_avg = weekend_sum / weekend_days
        weekday_avg = weekday_sum / weekday_days
        if weekend_avg > weekday_avg * 1.4:
            insights.append(_tr("Dam olish kunlari xarajatlaringiz hafta kunlariga nisbatan ancha yuqori.", lang))

    # Transport weekly trend (last 4 weeks)
    transport_names = set(_CATEGORY_DB_MAP.get("Transport", []))
    recent_txs = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__gte=today - timedelta(days=28),
        category__name__in=list(transport_names),
    ).values("date", "amount")
    weekly = defaultdict(float)
    for row in recent_txs:
        week = row["date"].isocalendar()[:2]  # (year, week)
        weekly[week] += float(row["amount"] or 0)
    weekly_vals = [weekly[k] for k in sorted(weekly.keys())]
    if len(weekly_vals) >= 3:
        increasing = all(weekly_vals[i] >= weekly_vals[i - 1] * 1.05 for i in range(1, len(weekly_vals)))
        if increasing:
            insights.append(_tr("Transport xarajatlari ketma-ket haftalarda oshib bormoqda.", lang))

    return insights[:5]


def detect_overspending(user, family=None, role=None, lang="uz"):
    """Return overspending warnings."""
    from django.utils import timezone
    from django.db.models import Sum
    from transactions.models import Transaction
    from budgets.models import Budget
    from core.i18n import translate as _tr

    lang = (lang or "uz").lower()
    warnings = []
    today = timezone.now().date()
    cur_y, cur_m = today.year, today.month

    # Budget-based warnings
    if family:
        budgets = Budget.objects.filter(family=family, month=cur_m, year=cur_y)
    else:
        budgets = Budget.objects.filter(user=user, family__isnull=True, month=cur_m, year=cur_y)
    for b in budgets:
        pct = b.get_percentage()
        if pct >= 100 and b.budget_type == "expense":
            tpl = "{budget} bo'yicha byudjet limitidan oshib ketdingiz ({percent}%)."
            warnings.append(_tr(tpl, lang).format(budget=b.name, percent=pct))
        elif pct >= 85 and b.budget_type == "expense":
            tpl = "{budget} byudjeti 85% dan oshdi — ehtiyot bo'ling."
            warnings.append(_tr(tpl, lang).format(budget=b.name))

    # Total expense vs 3-month average
    cur_total = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__year=cur_y, date__month=cur_m
    ).aggregate(total=Sum("amount"))["total"] or 0
    last3 = []
    for i in range(1, 4):
        y, m = _shift_month(cur_y, cur_m, -i)
        t = _tx_scope(user, family=family, role=role).filter(
            transaction_type="expense",
            date__year=y, date__month=m
        ).aggregate(total=Sum("amount"))["total"] or 0
        last3.append(float(t))
    if last3 and sum(last3) > 0:
        avg = sum(last3) / len(last3)
        if float(cur_total) > avg * 1.35:
            warnings.append(_tr("Bu oy umumiy xarajatlar o'rtacha darajadan 35% ko'p.", lang))

    return warnings[:5]


def generate_financial_advice(user, family=None, role=None, lang="uz"):
    """Return actionable advice strings."""
    from django.utils import timezone
    from django.db.models import Sum
    from core.i18n import translate as _tr

    lang = (lang or "uz").lower()
    advice = []
    today = timezone.now().date()
    cur_y, cur_m = today.year, today.month

    income = _tx_scope(user, family=family, role=role).filter(
        transaction_type="income",
        date__year=cur_y, date__month=cur_m
    ).aggregate(total=Sum("amount"))["total"] or 0
    expense = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__year=cur_y, date__month=cur_m
    ).aggregate(total=Sum("amount"))["total"] or 0
    income_val = float(income)
    expense_val = float(expense)

    if income_val > 0:
        savings = income_val - expense_val
        savings_rate = savings / income_val
        if savings_rate < 0.1:
            advice.append(_tr("Daromadingizning kamida 10% ini oy boshida jamg'armaga ajrating.", lang))
        elif savings_rate >= 0.2:
            advice.append(_tr("Jamg'arma ulushingiz yaxshi — uni investitsiya yoki favqulodda fondga yo'naltiring.", lang))

    # Top category reduction advice
    top_cat = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__year=cur_y, date__month=cur_m
    ).values("category__name").annotate(total=Sum("amount")).order_by("-total").first()
    if top_cat and top_cat.get("total"):
        other_label = _tr("Boshqa", lang)
        name = top_cat["category__name"] or other_label
        total = float(top_cat["total"])
        save = int(total * 0.2)
        tpl = "Agar {category} xarajatlarini 20% kamaytirsangiz, oyiga taxminan {save} UZS tejaysiz."
        advice.append(_tr(tpl, lang).format(category=name, save=f"{save:,}"))

    if expense_val > income_val and income_val > 0:
        advice.append(_tr("Xarajatlar daromaddan yuqori — 1 ta ixtiyoriy kategoriyani vaqtincha cheklang.", lang))

    return advice[:4]


def financial_health_score(user, family=None, role=None):
    """Return score (0-100) + label and breakdown."""
    from django.utils import timezone
    from django.db.models import Sum
    from transactions.models import Transaction
    from debts.models import Debt

    today = timezone.now().date()
    cur_y, cur_m = today.year, today.month

    income = _tx_scope(user, family=family, role=role).filter(
        transaction_type="income",
        date__year=cur_y, date__month=cur_m
    ).aggregate(total=Sum("amount"))["total"] or 0
    expense = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__year=cur_y, date__month=cur_m
    ).aggregate(total=Sum("amount"))["total"] or 0

    income_val = float(income)
    expense_val = float(expense)
    savings_rate = (income_val - expense_val) / income_val if income_val > 0 else -1
    expense_ratio = (expense_val / income_val) if income_val > 0 else 1.5

    if family:
        debt_total = Debt.objects.filter(
            family=family, debt_type="taken", status__in=["open", "partial"]
        ).aggregate(total=Sum("amount"))["total"] or 0
    else:
        debt_total = Debt.objects.filter(
            user=user, family__isnull=True, debt_type="taken", status__in=["open", "partial"]
        ).aggregate(total=Sum("amount"))["total"] or 0
    debt_ratio = float(debt_total) / income_val if income_val > 0 else 1.5

    # Stability based on last 6 months expense volatility
    monthly_expenses = []
    for i in range(5, -1, -1):
        y, m = _shift_month(cur_y, cur_m, -i)
        t = _tx_scope(user, family=family, role=role).filter(
            transaction_type="expense",
            date__year=y, date__month=m
        ).aggregate(total=Sum("amount"))["total"] or 0
        monthly_expenses.append(float(t))
    mean_exp = statistics.mean(monthly_expenses) if monthly_expenses else 0
    if mean_exp > 0 and len(monthly_expenses) > 1:
        exp_cv = statistics.pstdev(monthly_expenses) / mean_exp
    else:
        exp_cv = 0.5

    # Income stability
    monthly_income = []
    for i in range(5, -1, -1):
        y, m = _shift_month(cur_y, cur_m, -i)
        t = _tx_scope(user, family=family, role=role).filter(
            transaction_type="income",
            date__year=y, date__month=m
        ).aggregate(total=Sum("amount"))["total"] or 0
        monthly_income.append(float(t))
    mean_inc = statistics.mean(monthly_income) if monthly_income else 0
    if mean_inc > 0 and len(monthly_income) > 1:
        inc_cv = statistics.pstdev(monthly_income) / mean_inc
    else:
        inc_cv = 0.5

    savings_score = max(0, min(40, 40 * (savings_rate / 0.3))) if income_val > 0 else 0
    expense_score = max(0, min(20, 20 * (1 - min(expense_ratio, 1.5))))
    debt_score = max(0, min(20, 20 * (1 - min(debt_ratio, 1.5))))
    expense_stability_score = max(0, min(10, 10 * (1 - min(exp_cv, 1.0))))
    income_stability_score = max(0, min(10, 10 * (1 - min(inc_cv, 1.0))))

    score = int(round(savings_score + expense_score + debt_score + expense_stability_score + income_stability_score))
    score = max(0, min(100, score))

    if score >= 80:
        label = "A'lo"
    elif score >= 65:
        label = "Yaxshi"
    elif score >= 50:
        label = "O'rtacha"
    else:
        label = "Xavfli"
    # label is always stored in Uzbek (as i18n key); translated at display time via {% t %}

    return {
        "score": score,
        "label": label,
        "savings_rate_pct": int(max(0, savings_rate) * 100) if income_val > 0 else 0,
        "expense_ratio_pct": int(min(expense_ratio, 2) * 100) if income_val > 0 else 0,
        "debt_ratio_pct": int(min(debt_ratio, 2) * 100) if income_val > 0 else 0,
        "expense_stability_pct": int(max(0, 1 - min(exp_cv, 1.0)) * 100),
        "income_stability_pct": int(max(0, 1 - min(inc_cv, 1.0)) * 100),
    }


def detect_subscriptions(user, family=None, role=None):
    """Detect potential subscriptions from descriptions and repetition."""
    from django.utils import timezone

    today = timezone.now().date()
    since = today - timedelta(days=120)
    txs = _tx_scope(user, family=family, role=role).filter(
        transaction_type="expense",
        date__gte=since
    ).values("description", "amount", "date")

    subs = []
    seen = set()
    for row in txs:
        desc = (row["description"] or "").strip()
        if not desc:
            continue
        key = classify_expense_description(desc)
        if key == "Subscriptions":
            label = f"{desc} — {int(float(row['amount'])):,} UZS"
            if label not in seen:
                subs.append(label)
                seen.add(label)

    # Repeat detection
    grouped = defaultdict(list)
    for row in txs:
        norm = _normalize_text(row["description"])
        if not norm:
            continue
        grouped[(norm, int(float(row["amount"] or 0)))].append(row["date"])
    for (norm, amt), dates in grouped.items():
        if len(dates) >= 2:
            label = f"{norm[:40]} — {amt:,} UZS"
            if label not in seen:
                subs.append(label)
                seen.add(label)

    return subs[:5]


def build_financial_insights(user, family=None, role=None, lang="uz"):
    """Aggregate AI insights for dashboards."""
    lang = (lang or "uz").lower()
    health = financial_health_score(user, family=family, role=role)
    return {
        "patterns": analyze_spending_patterns(user, family=family, role=role, lang=lang),
        "overspending": detect_overspending(user, family=family, role=role, lang=lang),
        "advice": generate_financial_advice(user, family=family, role=role, lang=lang),
        "subscriptions": detect_subscriptions(user, family=family, role=role),
        "health_score": health["score"],
        "health_label": health["label"],
        "health_breakdown": health,
        "health_ai_summary": generate_health_ai_summary(health, lang=lang),
    }


def _health_ai_prompt(health):
    return (
        "Siz moliyaviy analitiksiz. Quyidagi ko'rsatkichlar asosida 2-3 gapli "
        "qisqa xulosa va 1 ta amaliy tavsiya yozing. Uzbek tilida. "
        "Ortiqcha gap bo'lmasin.\n"
        f"Score: {health.get('score')}\n"
        f"Savings rate: {health.get('savings_rate_pct')}%\n"
        f"Expense ratio: {health.get('expense_ratio_pct')}%\n"
        f"Debt ratio: {health.get('debt_ratio_pct')}%\n"
        f"Expense stability: {health.get('expense_stability_pct')}%\n"
        f"Income stability: {health.get('income_stability_pct')}%\n"
    )


def _fallback_health_summary(health, lang="uz"):
    from core.i18n import translate as _tr
    lang = (lang or "uz").lower()
    score = health.get("score", 0)
    label = health.get("label", "O'rtacha")
    savings = health.get("savings_rate_pct", 0)
    expense_ratio = health.get("expense_ratio_pct", 0)
    debt_ratio = health.get("debt_ratio_pct", 0)
    exp_stab = health.get("expense_stability_pct", 0)
    inc_stab = health.get("income_stability_pct", 0)

    translated_label = _tr(label, lang)
    tpl = "Moliyaviy salomatlik: {score}/100 ({label})."
    parts = [_tr(tpl, lang).format(score=score, label=translated_label)]
    if savings < 10:
        parts.append(_tr("Tejash stavkasi past — oy boshida 10% jamg'arma ajrating.", lang))
    elif savings >= 20:
        parts.append(_tr("Tejash darajasi yaxshi — shu tempni saqlang.", lang))
    if expense_ratio > 80:
        parts.append(_tr("Xarajatlar daromadga yaqin — byudjetni siqish kerak.", lang))
    if debt_ratio > 50:
        parts.append(_tr("Qarz yuklama yuqori — to'lov rejasini kuchaytiring.", lang))
    if exp_stab < 50 or inc_stab < 50:
        parts.append(_tr("Xarajat/daromad barqaror emas — barqarorlashtirish kerak.", lang))

    return " ".join(parts[:3])


def generate_health_ai_summary(health, lang="uz"):
    """Use AI to generate a short health summary; fallback if AI unavailable."""
    prompt = _health_ai_prompt(health)
    providers = _provider_candidates()
    if not providers:
        return _fallback_health_summary(health, lang=lang)

    text = None
    for provider in providers:
        if provider == "gemini":
            text = _gemini_generate(prompt, temperature=0.2, max_tokens=120)
        elif provider == "groq":
            text = _groq_generate(prompt, temperature=0.2, max_tokens=120)
        elif provider == "openai":
            text = _openai_generate(prompt, temperature=0.2, max_tokens=120)
        elif provider == "anthropic":
            text = _anthropic_generate(prompt, temperature=0.2, max_tokens=120)
        if text:
            break

    if not text:
        return _fallback_health_summary(health, lang=lang)

    for raw in text.splitlines():
        line = raw.strip()
        if line:
            return line
    return _fallback_health_summary(health, lang=lang)


def _build_notification_prompt(event_type, data):
    """Return a short Uzbek notification message prompt."""
    data = data or {}
    return (
        "Siz moliyaviy assistentsiz. "
        "Quyidagi hodisa bo'yicha 1 ta qisqa xabar yozing (maks 120 belgi). "
        "Faqat bitta satr, keraksiz izohsiz. "
        "Uzbek tilida, foydalanuvchiga tushunarli bo'lsin.\n"
        f"Hodisa turi: {event_type}\n"
        f"Ma'lumot: {json.dumps(data, ensure_ascii=False)}"
    )


def generate_notification_message(event_type, data, fallback_message):
    """Try AI providers; fallback to static message if AI not available."""
    prompt = _build_notification_prompt(event_type, data)
    providers = _provider_candidates()
    if not providers:
        return fallback_message

    text = None
    for provider in providers:
        if provider == "gemini":
            text = _gemini_generate(prompt, temperature=0.2, max_tokens=80)
        elif provider == "groq":
            text = _groq_generate(prompt, temperature=0.2, max_tokens=80)
        elif provider == "openai":
            text = _openai_generate(prompt, temperature=0.2, max_tokens=80)
        elif provider == "anthropic":
            text = _anthropic_generate(prompt, temperature=0.2, max_tokens=80)
        if text:
            break

    if not text:
        return fallback_message

    # First non-empty line
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            return line[:120]
    return fallback_message
