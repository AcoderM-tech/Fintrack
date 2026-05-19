import os
from pathlib import Path
from django.utils.translation import gettext_lazy as _


def _load_env(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key not in os.environ or os.environ.get(key, "") == "":
            os.environ[key] = val


BASE_DIR = Path(__file__).resolve().parent.parent
_load_env(BASE_DIR / ".env")


def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_int(name, default=0):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_raw_secret = os.getenv("SECRET_KEY", "")
if not _raw_secret:
    if os.getenv("DJANGO_ENV") == "production":
        raise ValueError("SECRET_KEY must be set in production environment")
    _raw_secret = "django-insecure-dev-only-change-me"
SECRET_KEY = _raw_secret

DEBUG = _env_bool("DEBUG", True)

ALLOWED_HOSTS = ['fintrack-wmc6.onrender.com', 'localhost', '127.0.0.1']
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts_app",
    "transactions.apps.TransactionsConfig",
    "budgets",
    "debts.apps.DebtsConfig",
    "analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware olib tashlandi — u cookie/sessiyani noto'g'ri override qiladi
    # "django.middleware.locale.LocaleMiddleware",
    "core.middleware.RateLimitMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # AuthenticationMiddleware dan KEYIN — shunda request.user tayyor bo'ladi
    "core.middleware.LanguagePreferenceMiddleware",
    "core.middleware.IdleLogoutMiddleware",
    "core.middleware.LoginRequiredMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fintrack.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "builtins": ["core.templatetags.core_tags"],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.i18n",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.menu_notifications",
                "core.context_processors.finance_scope",
            ],
        },
    },
]

WSGI_APPLICATION = "fintrack.wsgi.application"

# ─── Database ────────────────────────────────────────────────────────────────
_db_url = os.getenv("DATABASE_URL", "")
if _db_url.startswith("postgres"):
    import re
    m = re.match(r"postgres(?:ql)?://([^:]+):([^@]+)@([^:/]+):?(\d*)/(.+)", _db_url)
    if m:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "USER": m.group(1),
                "PASSWORD": m.group(2),
                "HOST": m.group(3),
                "PORT": m.group(4) or "5432",
                "NAME": m.group(5),
                "CONN_MAX_AGE": _env_int("DB_CONN_MAX_AGE", 60),
                "OPTIONS": {"connect_timeout": 10},
            }
        }
    else:
        raise ValueError("DATABASE_URL noto'g'ri format")
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ─── Auth ────────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

# ─── I18n ────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "uz")
LANGUAGES = [
    ("uz", _("O'zbek")),
    ("ru", _("Russian")),
    ("en", _("English")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Tashkent")
USE_I18N = True
USE_TZ = True

# ─── Static & Media ──────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Sessions ────────────────────────────────────────────────────────────────
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = _env_int("SESSION_COOKIE_AGE", 86400 * 14)
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = _env_bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", False)

# ─── Security ────────────────────────────────────────────────────────────────
SECURE_SSL_REDIRECT = False if DEBUG else _env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = False if DEBUG else _env_bool("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = False if DEBUG else _env_bool("CSRF_COOKIE_SECURE", True)
SECURE_HSTS_SECONDS = 0 if DEBUG else _env_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False if DEBUG else _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = False if DEBUG else _env_bool("SECURE_HSTS_PRELOAD", True)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# ─── File Upload Security ─────────────────────────────────────────────────────
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # 5 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
MAX_UPLOAD_SIZE = 2 * 1024 * 1024                # avatar max 2 MB
ALLOWED_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]

# ─── Rate Limit ───────────────────────────────────────────────────────────────
RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_LOGIN_MAX = _env_int("RATE_LIMIT_LOGIN_MAX", 5)
RATE_LIMIT_LOGIN_WINDOW = _env_int("RATE_LIMIT_LOGIN_WINDOW", 300)
RATE_LIMIT_LOGIN_USERNAME_MAX = _env_int("RATE_LIMIT_LOGIN_USERNAME_MAX", 10)
RATE_LIMIT_LOGIN_USERNAME_WINDOW = _env_int("RATE_LIMIT_LOGIN_USERNAME_WINDOW", 300)
RATE_LIMIT_ALL_REQUESTS = _env_bool("RATE_LIMIT_ALL_REQUESTS", False)
RATE_LIMIT_REQUESTS = _env_int("RATE_LIMIT_REQUESTS", 120)
RATE_LIMIT_WINDOW = _env_int("RATE_LIMIT_WINDOW", 60)

# ─── Idle Logout ──────────────────────────────────────────────────────────────
IDLE_LOGOUT_ENABLED = _env_bool("IDLE_LOGOUT_ENABLED", False)
IDLE_LOGOUT_SECONDS = _env_int("IDLE_LOGOUT_SECONDS", 900)

# ─── AI Providers ─────────────────────────────────────────────────────────────
AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")
AI_PROVIDER_ORDER = os.getenv("AI_PROVIDER_ORDER", "groq,openai,anthropic,gemini")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_LABEL = os.getenv("OPENAI_LABEL", "ChatGPT")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-001")
GEMINI_MODEL_FALLBACK = os.getenv("GEMINI_MODEL_FALLBACK", "")

# ─── Currency ─────────────────────────────────────────────────────────────────
CURRENCY_RATES = {
    "UZS": 1,
    "USD": int(os.getenv("RATE_USD", "12700")),
    "EUR": int(os.getenv("RATE_EUR", "13800")),
    "RUB": int(os.getenv("RATE_RUB", "140")),
}

# ─── Notification throttle ────────────────────────────────────────────────────
NOTIFICATION_REFRESH_CACHE_SECONDS = _env_int("NOTIFICATION_REFRESH_CACHE_SECONDS", 300)

# ─── Caching ──────────────────────────────────────────────────────────────────
# Use Redis in production: set REDIS_URL=redis://127.0.0.1:6379/1 in .env
_redis_url = os.getenv("REDIS_URL", "")
if _redis_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _redis_url,
            "OPTIONS": {
                "socket_connect_timeout": 5,
                "socket_timeout": 5,
            },
            "KEY_PREFIX": "fintrack",
        }
    }
    # Store sessions in cache for speed
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"
else:
    # Development: in-memory cache per process (default)
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fintrack-default",
        }
    }

# ─── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {module} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "WARNING")},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
