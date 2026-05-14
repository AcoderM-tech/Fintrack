import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fintrack.settings')

import django
from django.test import Client
from django.conf import settings

django.setup()

# Allow Django test client host
if isinstance(settings.ALLOWED_HOSTS, list):
    if 'testserver' not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS.append('testserver')
else:
    settings.ALLOWED_HOSTS = ['testserver']

from django.contrib.auth import get_user_model
from core.models import FamilyGroup, FamilyMember


def ensure_father_family(user, name):
    father_membership = FamilyMember.objects.filter(user=user, role='father').select_related('family').first()
    if father_membership:
        return father_membership.family, False
    family, created = FamilyGroup.objects.get_or_create(name=name, created_by=user)
    FamilyMember.objects.update_or_create(
        family=family,
        user=user,
        defaults={'role': 'father'},
    )
    return family, True


def ensure_role(family, user, role):
    FamilyMember.objects.update_or_create(
        family=family,
        user=user,
        defaults={'role': role},
    )


def user_summary(user):
    memberships = FamilyMember.objects.filter(user=user).select_related('family')
    return [(m.family.id, m.family.name, m.role) for m in memberships]


def test_user(user, family):
    client = Client()
    client.force_login(user)
    role = FamilyMember.objects.filter(user=user, family=family).values_list('role', flat=True).first()
    targets = [
        ('dashboard', '/dashboard/'),
        ('family', '/family/'),
        ('family_stats', f'/family/stats/?scope=family&family_id={family.id}'),
        ('family_analytics', f'/analytics/?scope=family&family_id={family.id}'),
    ]
    results = []
    for name, url in targets:
        resp = client.get(url)
        results.append((name, url, resp.status_code))

    # Detailed checks
    detail = {}

    # Family stats behavior
    stats_url = f'/family/stats/?scope=family&family_id={family.id}'
    if role in ('father', 'mother'):
        # pick first eligible member id
        members_qs = FamilyMember.objects.filter(family=family)
        if role == 'father':
            members_qs = members_qs.exclude(role='father')
        elif role == 'mother':
            members_qs = members_qs.filter(role__in=['son', 'daughter'])
        member = members_qs.first()
        if member:
            resp = client.get(stats_url + f'&member={member.id}')
            detail['family_stats'] = {
                'status': resp.status_code,
                'has_trend': 'Oylik xarajat trendi' in resp.content.decode('utf-8', errors='ignore'),
            }
        else:
            resp = client.get(stats_url)
            detail['family_stats'] = {
                'status': resp.status_code,
                'empty_state': "A'zo tanlang" in resp.content.decode('utf-8', errors='ignore'),
            }
    else:
        resp = client.get(stats_url)
        detail['family_stats'] = {
            'status': resp.status_code,
            'blocked': "A'zo tanlang" in resp.content.decode('utf-8', errors='ignore'),
        }

    # Family analytics behavior
    analytics_url = f'/analytics/?scope=family&family_id={family.id}'
    resp = client.get(analytics_url)
    body = resp.content.decode('utf-8', errors='ignore')
    if role in ('father', 'mother'):
        detail['family_analytics'] = {
            'status': resp.status_code,
            'blocked': "Oilaviy tahlil faqat Ota yoki Ona rollari uchun mavjud." in body,
            'has_trend': "Trend (" in body,
        }
    else:
        detail['family_analytics'] = {
            'status': resp.status_code,
            'blocked': "Oilaviy tahlil faqat Ota yoki Ona rollari uchun mavjud." in body,
        }

    client.logout()
    return results, detail, role


if __name__ == '__main__':
    User = get_user_model()
    users = list(User.objects.order_by('id')[:3])
    if len(users) < 3:
        print('Kamida 3 ta user kerak. Hozir:', len(users))
        raise SystemExit(1)

    u1, u2, u3 = users

    family_a, created_a = ensure_father_family(u1, 'Demo Family A')
    ensure_role(family_a, u2, 'son')

    family_b, created_b = ensure_father_family(u2, 'Demo Family B')
    ensure_role(family_b, u3, 'son')

    print('== FAMILY SETUP ==')
    print('Family A:', family_a.id, family_a.name, 'created_by', u1.username, 'created', created_a)
    print('Family B:', family_b.id, family_b.name, 'created_by', u2.username, 'created', created_b)

    print('\n== USER MEMBERSHIPS ==')
    for u in (u1, u2, u3):
        print(u.username, user_summary(u))

    print('\n== MENU TESTS ==')
    for u, fam in ((u1, family_a), (u2, family_b), (u3, family_b)):
        print(f'User: {u.username}')
        results, detail, role = test_user(u, fam)
        print('  role:', role)
        for name, url, code in results:
            print(' ', name, url, code)
        print('  family_stats_check:', detail.get('family_stats'))
        print('  family_analytics_check:', detail.get('family_analytics'))
        print('---')

    print('Done.')
