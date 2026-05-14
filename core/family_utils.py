from django.contrib import messages
from django.db.models import Q

from core.models import FamilyGroup, FamilyMember
from core.i18n import translate as _i18n_translate, get_request_lang


ROLE_LABELS = {
    "father": "Ota",
    "mother": "Ona",
    "son": "O'g'il",
    "daughter": "Qiz",
}

ROLE_GENDER_MAP = {
    "father": "male",
    "son": "male",
    "mother": "female",
    "daughter": "female",
}

GENDER_PARENT_ROLE = {
    "male": "father",
    "female": "mother",
}

GENDER_CHILD_ROLE = {
    "male": "son",
    "female": "daughter",
}


def get_user_gender(user):
    if not user:
        return None
    profile = getattr(user, "profile", None)
    return getattr(profile, "gender", None)


def get_parent_role_for_gender(gender):
    return GENDER_PARENT_ROLE.get(gender)


def get_child_role_for_gender(gender):
    return GENDER_CHILD_ROLE.get(gender)


def is_role_allowed_for_user(user, role):
    gender = get_user_gender(user)
    if not gender or role not in ROLE_GENDER_MAP:
        return False
    return ROLE_GENDER_MAP[role] == gender


def is_family_parent(role):
    return role in ("father", "mother")


def is_family_head(user, family):
    return bool(user and family and family.created_by_id == user.id)


def get_active_family(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None
    if hasattr(request, "_active_family_cache"):
        return request._active_family_cache
    scope = request.session.get("finance_scope", "personal")
    if scope != "family":
        request._active_family_cache = None
        return None
    family_id = request.session.get("finance_family_id")
    if not family_id:
        request._active_family_cache = None
        return None
    family = FamilyGroup.objects.filter(id=family_id, members=request.user).first()
    request._active_family_cache = family
    return family


def get_family_role(user, family):
    if not user or not family:
        return None
    cache = getattr(family, "_role_cache", None)
    if cache is None:
        cache = {}
        setattr(family, "_role_cache", cache)
    if user.id in cache:
        return cache[user.id]
    role = FamilyMember.objects.filter(user=user, family=family).values_list("role", flat=True).first()
    cache[user.id] = role
    return role


def is_family_admin(role, user=None, family=None):
    return role == "father"


def can_manage_family_finance(role, user=None, family=None):
    return role in ("father", "mother")


def scope_queryset(qs, user, family=None, role=None, user_field="user", family_field="family"):
    if not family:
        return qs.filter(**{user_field: user, f"{family_field}__isnull": True})
    if role in ("son", "daughter"):
        return qs.filter(**{family_field: family, user_field: user})
    return qs.filter(**{family_field: family})


def categories_queryset(user, family=None, role=None):
    from transactions.models import Category
    if not family:
        return Category.objects.filter(Q(user=user) | Q(is_default=True), family__isnull=True)
    return Category.objects.filter(Q(family=family) | Q(is_default=True))


def accounts_queryset(user, family=None, role=None):
    from accounts_app.models import Account
    if not family:
        return Account.objects.filter(user=user, family__isnull=True, is_active=True)
    if role in ("son", "daughter"):
        return Account.objects.filter(family=family, user=user, is_active=True)
    return Account.objects.filter(family=family, is_active=True)


def ensure_scope(request, scope=None, family_id=None):
    if not scope:
        return
    if scope == "personal":
        request.session["finance_scope"] = "personal"
        request.session.pop("finance_family_id", None)
        request.session.modified = True
        return
    if scope == "family":
        if not family_id:
            return
        family = FamilyGroup.objects.filter(id=family_id, members=request.user).first()
        if not family:
            return
        request.session["finance_scope"] = "family"
        request.session["finance_family_id"] = family.id
        request.session.modified = True
        return


def handle_scope_param(request):
    scope = request.GET.get("scope")
    family_id = request.GET.get("family_id")
    if scope in ("personal", "family"):
        ensure_scope(request, scope=scope, family_id=family_id)
    if scope == "family":
        if not family_id:
            return
        family = FamilyGroup.objects.filter(id=family_id, members=request.user).first()
        if not family:
            messages.error(request, _i18n_translate("Oilaviy guruh topilmadi yoki siz a'zo emassiz.", get_request_lang(request)))
            return
        request.session["finance_scope"] = "family"
        request.session["finance_family_id"] = family.id
        request.session.modified = True
        return
