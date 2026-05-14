from core.i18n import translate as _i18n_translate, get_request_lang
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from core.models import UserProfile
from transactions.models import Category


def register_view(request):
    """Ro'yxatdan o'tish"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        gender = (request.POST.get('gender') or '').strip().lower()
        gender_valid = gender in ('male', 'female')
        if form.is_valid() and gender_valid:
            user = form.save()

            # Profil yaratish
            UserProfile.objects.create(user=user, gender=gender)

            # Default kategoriyalar
            default_categories = [
                {'name': 'Oziq-ovqat', 'icon': 'shopping-cart', 'color': '#f59e0b', 'type': 'expense'},
                {'name': 'Transport', 'icon': 'car', 'color': '#3b82f6', 'type': 'expense'},
                {'name': 'Uy-joy', 'icon': 'home', 'color': '#8b5cf6', 'type': 'expense'},
                {'name': 'Kiyim', 'icon': 'shirt', 'color': '#ec4899', 'type': 'expense'},
                {'name': 'Salomatlik', 'icon': 'heart', 'color': '#ef4444', 'type': 'expense'},
                {'name': "Ta'lim", 'icon': 'book', 'color': '#6366f1', 'type': 'expense'},
                {'name': "Ko'ngilochar", 'icon': 'device-gamepad-2', 'color': '#14b8a6', 'type': 'expense'},
                {'name': 'Kommunal', 'icon': 'bulb', 'color': '#f97316', 'type': 'expense'},
                {'name': 'Internet/Telefon', 'icon': 'phone', 'color': '#0ea5e9', 'type': 'expense'},
                {'name': 'Boshqa xarajat', 'icon': 'tag', 'color': '#64748b', 'type': 'expense'},
                {'name': 'Maosh', 'icon': 'cash', 'color': '#10b981', 'type': 'income'},
                {'name': 'Freelance', 'icon': 'briefcase', 'color': '#6366f1', 'type': 'income'},
                {'name': 'Bonus', 'icon': 'gift', 'color': '#f59e0b', 'type': 'income'},
                {'name': 'Ijara', 'icon': 'building', 'color': '#8b5cf6', 'type': 'income'},
                {'name': 'Investitsiya', 'icon': 'chart-line', 'color': '#14b8a6', 'type': 'income'},
                {'name': 'Boshqa daromad', 'icon': 'coins', 'color': '#64748b', 'type': 'income'},
            ]
            Category.objects.bulk_create([
                Category(
                    user=user,
                    name=cat['name'],
                    icon=cat['icon'],
                    color=cat['color'],
                    category_type=cat['type'],
                    is_default=True,
                )
                for cat in default_categories
            ])

            login(request, user)
            messages.success(request, f"Xush kelibsiz, {user.username}! " + _i18n_translate("Hisob muvaffaqiyatli yaratildi.", get_request_lang(request)))
            return redirect('dashboard')
        if not gender_valid:
            form.add_error(None, "Jinsni tanlang (Erkak yoki Ayol).")
    else:
        form = UserCreationForm()

    return render(request, 'registration/register.html', {
        'form': form,
        'gender_value': (request.POST.get('gender') if request.method == 'POST' else ''),
    })
