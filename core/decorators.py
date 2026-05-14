from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from core.i18n import translate as _i18n_translate, get_request_lang


def role_required(roles, redirect_to='family', message=None, use_scope_param=True):
    """Require a family role before accessing a view."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if use_scope_param:
                from core.family_utils import handle_scope_param
                handle_scope_param(request)

            from core.family_utils import get_active_family, get_family_role

            family = get_active_family(request)
            if not family:
                messages.info(request, _i18n_translate("Avval oila guruhini tanlang yoki yarating.", get_request_lang(request)))
                return redirect('family')

            role = get_family_role(request.user, family)
            if roles and role not in roles:
                lang = get_request_lang(request)
                msg = message or "Ushbu bo'lim uchun ruxsat yo'q."
                messages.error(request, _i18n_translate(msg, lang))
                return redirect(redirect_to)

            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
