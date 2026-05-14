from urllib.parse import urlencode
from django.conf import settings
from django.utils import translation

# Django session key for language preference
LANGUAGE_SESSION_KEY = "django_language"
from django.shortcuts import redirect
from django.contrib.auth import logout
from django.utils import timezone
from django.core.cache import cache
from django.http import HttpResponse
from django.urls import Resolver404, resolve
import hashlib
import time


class LoginRequiredMiddleware:
    """Login bo'lmagan foydalanuvchini himoyalangan URLlardan qaytarish."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if request.user.is_authenticated:
            if not request.user.is_active:
                logout(request)
                return redirect(settings.LOGIN_URL)
            return self.get_response(request)

        if self._is_public_path(path):
            return self.get_response(request)

        # Noto'g'ri URL bo'lsa (resolve bo'lmasa) login sahifaga yubormaymiz,
        # Django 404 handler ishlasin.
        try:
            resolve(request.path_info)
        except Resolver404:
            return self.get_response(request)

        login_url = settings.LOGIN_URL
        query = urlencode({'next': path})
        return redirect(f"{login_url}?{query}")

    def _is_public_path(self, path: str) -> bool:
        if path == '/':
            return True
        if path.startswith('/set-language/'):
            return True
        if path.startswith('/auth/') or path.startswith('/admin/'):
            return True
        if settings.STATIC_URL and path.startswith(settings.STATIC_URL):
            return True
        if settings.MEDIA_URL and path.startswith(settings.MEDIA_URL):
            return True
        return False


class RateLimitMiddleware:
    """IP-based rate limiting."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, 'RATE_LIMIT_ENABLED', False):
            return self.get_response(request)

        path = request.path or '/'
        if self._is_exempt_path(path):
            return self.get_response(request)

        ip = self._get_ip(request)
        now = int(time.time())

        if path.startswith('/auth/login') and request.method == 'POST':
            username = (request.POST.get('username') or '').strip().lower()
            if not self._allow_login(ip, username, now):
                return self._blocked_response()
            return self.get_response(request)

        if getattr(settings, 'RATE_LIMIT_ALL_REQUESTS', False):
            if not self._allow_general(ip, now):
                return self._blocked_response()

        return self.get_response(request)

    def _blocked_response(self):
        return HttpResponse(
            "So'rovlar juda ko'p. Iltimos, biroz kuting va qayta urinib ko'ring.",
            status=429,
        )

    def _allow_login(self, ip, username, now):
        ip_limit = int(getattr(settings, 'RATE_LIMIT_LOGIN_MAX', 5))
        ip_window = int(getattr(settings, 'RATE_LIMIT_LOGIN_WINDOW', 300))
        user_limit = int(getattr(settings, 'RATE_LIMIT_LOGIN_USERNAME_MAX', 10))
        user_window = int(getattr(settings, 'RATE_LIMIT_LOGIN_USERNAME_WINDOW', 300))

        ip_key = f"rl:login:ip:{ip}"
        if not self._hit(ip_key, ip_limit, ip_window, now):
            return False

        if username:
            uname_hash = hashlib.sha256(username.encode('utf-8')).hexdigest()[:16]
            user_key = f"rl:login:user:{uname_hash}"
            if not self._hit(user_key, user_limit, user_window, now):
                return False
        return True

    def _allow_general(self, ip, now):
        limit = int(getattr(settings, 'RATE_LIMIT_REQUESTS', 120))
        window = int(getattr(settings, 'RATE_LIMIT_WINDOW', 60))
        key = f"rl:req:ip:{ip}"
        return self._hit(key, limit, window, now)

    def _hit(self, key, limit, window, now):
        entry = cache.get(key)
        if not entry:
            cache.set(key, {'count': 1, 'start': now}, timeout=window)
            return True
        count = entry.get('count', 0) + 1
        entry['count'] = count
        cache.set(key, entry, timeout=window)
        return count <= limit

    def _get_ip(self, request):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            # Faqat birinchi IP (eng yaqin client)
            ip = xff.split(',')[0].strip()
            # IPv4/IPv6 validatsiyasi
            if ip and len(ip) <= 45:
                return ip
        return request.META.get('REMOTE_ADDR', 'unknown')

    def _is_exempt_path(self, path):
        if settings.STATIC_URL and path.startswith(settings.STATIC_URL):
            return True
        if settings.MEDIA_URL and path.startswith(settings.MEDIA_URL):
            return True
        extra = getattr(settings, 'RATE_LIMIT_EXEMPT_PATHS', [])
        for p in extra:
            p = (p or '').strip()
            if p and path.startswith(p):
                return True
        return False


class IdleLogoutMiddleware:
    """Auto-logout users after inactivity."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, 'IDLE_LOGOUT_ENABLED', False):
            return self.get_response(request)

        path = request.path or '/'
        if self._is_exempt_path(path):
            return self.get_response(request)

        if request.user.is_authenticated:
            idle_seconds = int(getattr(settings, 'IDLE_LOGOUT_SECONDS', 900))
            now_ts = int(timezone.now().timestamp())
            last_ts = request.session.get('last_activity_ts')

            if last_ts and (now_ts - int(last_ts)) > idle_seconds:
                logout(request)
                request.session.flush()
                return redirect(f"{settings.LOGIN_URL}?next={path}")

            request.session['last_activity_ts'] = now_ts

        return self.get_response(request)

    def _is_exempt_path(self, path):
        if path == '/':
            return True
        if path.startswith('/auth/') or path.startswith('/admin/'):
            return True
        if settings.STATIC_URL and path.startswith(settings.STATIC_URL):
            return True
        if settings.MEDIA_URL and path.startswith(settings.MEDIA_URL):
            return True
        extra = getattr(settings, 'IDLE_LOGOUT_EXEMPT_PATHS', [])
        for p in extra:
            p = (p or '').strip()
            if p and path.startswith(p):
                return True
        return False


class SecurityHeadersMiddleware:
    """Qo'shimcha xavfsizlik headerlari."""

    # Content-Security-Policy
    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=(), payment=()'
        response['X-DNS-Prefetch-Control'] = 'off'
        ct = response.get('Content-Type', '')
        if 'text/html' in ct:
            response['Content-Security-Policy'] = self._CSP
        if not response.get('Cache-Control'):
            if request.user.is_authenticated:
                response['Cache-Control'] = 'private, no-store'
            else:
                response['Cache-Control'] = 'public, max-age=60'
        return response


class LanguagePreferenceMiddleware:
    """
    Foydalanuvchi tilini aniqlaydi va request.LANGUAGE_CODE ni o'rnatadi.
    Tartib (ustuvorlik — yuqoridan quyi):
      1. fintrack_lang cookie  (foydalanuvchi explicit tanlagan)
      2. django_language sessiya
      3. UserProfile.language  (foydalanuvchi profilida saqlangan)
      4. default: uz
    AuthenticationMiddleware dan KEYIN turishi shart!
    """

    VALID = {"uz", "ru", "en"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = self._detect_lang(request)

        # request ga yoz — bu {% t %} tegi o'qiydi
        request.LANGUAGE_CODE = lang

        # Sessiyaga ham yoz — keyingi so'rovlarda ishlatilsin
        if request.session.get(LANGUAGE_SESSION_KEY) != lang:
            request.session[LANGUAGE_SESSION_KEY] = lang
            request.session.modified = True

        # Django translation engine ham shu tilga o'tsin
        translation.activate(lang)

        response = self.get_response(request)
        translation.deactivate()
        return response

    def _detect_lang(self, request):
        # 1. Cookie (eng yuqori ustuvorlik — foydalanuvchi o'zi tanlagan)
        lang = request.COOKIES.get("fintrack_lang", "").strip().lower()
        if lang in self.VALID:
            return lang

        # 2. Sessiya
        lang = (request.session.get(LANGUAGE_SESSION_KEY) or "").strip().lower()
        if lang in self.VALID:
            return lang

        # 3. UserProfile (faqat auth bo'lgan foydalanuvchi uchun)
        if getattr(request, "user", None) and request.user.is_authenticated:
            try:
                lang = (request.user.profile.language or "").strip().lower()
                if lang in self.VALID:
                    return lang
            except Exception:
                pass

        return "uz"

