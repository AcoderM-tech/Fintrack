from django.db import models
from django.contrib.auth.models import User
from core.models import FamilyGroup
from decimal import Decimal
from django.conf import settings


class Account(models.Model):
    ACCOUNT_TYPES = [
        ('cash', 'Naqd pul'),
        ('card', 'Bank kartasi'),
        ('bank', 'Bank hisob raqami'),
        ('savings', "Jamg'arma"),
        ('investment', 'Investitsiya'),
        ('crypto', 'Kripto'),
    ]
    CURRENCY_CHOICES = [
        ('UZS', "O'zbek so'mi"),
        ('USD', 'Dollar'),
        ('EUR', 'Yevro'),
        ('RUB', 'Rubl'),
    ]
    COLOR_CHOICES = [
        ('#6366f1', 'Indigo'),
        ('#8b5cf6', 'Violet'),
        ('#ec4899', 'Pink'),
        ('#f59e0b', 'Amber'),
        ('#10b981', 'Emerald'),
        ('#3b82f6', 'Blue'),
        ('#ef4444', 'Red'),
        ('#14b8a6', 'Teal'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='accounts')
    family = models.ForeignKey(FamilyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='accounts')
    name = models.CharField(max_length=100, verbose_name="Nomi")
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES, default='card', verbose_name="Turi")
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='UZS', verbose_name="Valyuta")
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="Joriy balans")
    initial_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="Boshlang'ich balans")
    low_balance_threshold = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="Past balans limiti")
    card_number = models.CharField(max_length=19, blank=True, verbose_name="Karta raqami")
    color = models.CharField(max_length=7, default='#6366f1', choices=COLOR_CHOICES, verbose_name="Rang")
    icon = models.CharField(max_length=32, default='credit-card', verbose_name="Belgi")
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    include_in_total = models.BooleanField(default=True, verbose_name="Umumiy hisobga qo'shish")
    description = models.TextField(blank=True, verbose_name="Izoh")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_currency_display()})"

    def get_balance_in_uzs(self):
        """Balansni UZS ga o'girish — settings dan kurs oladi"""
        rates = getattr(settings, 'CURRENCY_RATES', {'UZS': 1, 'USD': 12700, 'EUR': 13800, 'RUB': 140})
        return float(self.balance) * rates.get(self.currency, 1)

    class Meta:
        verbose_name = "Hisob raqam"
        verbose_name_plural = "Hisob raqamlar"
        ordering = ['-created_at']
