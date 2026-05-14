from django.db import models
from django.contrib.auth.models import User
from accounts_app.models import Account
from core.models import FamilyGroup
from decimal import Decimal


class Debt(models.Model):
    """Qarz va haqdorliklar"""

    DEBT_TYPES = [
        ('given', 'Men bergan qarz (haqdorlik)'),
        ('taken', 'Men olgan qarz'),
    ]

    STATUS_CHOICES = [
        ('open', 'Ochiq'),
        ('closed', 'Yopiq'),
        ('partial', 'Qisman qaytarildi'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='debts')
    family = models.ForeignKey(FamilyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='debts')
    debt_type = models.CharField(max_length=10, choices=DEBT_TYPES, verbose_name="Turi")
    person_name = models.CharField(max_length=150, verbose_name="Shaxs ismi")
    person_phone = models.CharField(max_length=20, blank=True, verbose_name="Telefon raqami")
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Summa")
    currency = models.CharField(max_length=3, default='UZS', verbose_name="Valyuta")
    paid_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="To'langan summa")
    account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Hisob raqam")
    description = models.TextField(blank=True, verbose_name="Izoh")
    date = models.DateField(verbose_name="Qarz sanasi")
    due_date = models.DateField(null=True, blank=True, verbose_name="Qaytarish sanasi")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open', verbose_name="Holat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def remaining_amount(self):
        return self.amount - self.paid_amount

    @property
    def is_overdue(self):
        if self.due_date and self.status == 'open':
            from django.utils import timezone
            return self.due_date < timezone.now().date()
        return False

    def __str__(self):
        type_label = "Bergan" if self.debt_type == 'given' else "Olgan"
        return f"{type_label} qarz: {self.person_name} - {self.amount} {self.currency}"

    class Meta:
        verbose_name = "Qarz"
        verbose_name_plural = "Qarzlar"
        ordering = ['-date']
        indexes = [
            models.Index(fields=['user', 'family', 'status']),
            models.Index(fields=['family', 'due_date']),
            models.Index(fields=['user', 'due_date']),
        ]


class DebtPayment(models.Model):
    """Qarz to'lovlari tarixi"""
    
    debt = models.ForeignKey(Debt, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="To'langan summa")
    date = models.DateField(verbose_name="To'lov sanasi")
    notes = models.TextField(blank=True, verbose_name="Izoh")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Umumiy to'langan summani yangilash
        self.debt.paid_amount = sum(p.amount for p in self.debt.payments.all())
        if self.debt.paid_amount >= self.debt.amount:
            self.debt.status = 'closed'
        elif self.debt.paid_amount > 0:
            self.debt.status = 'partial'
        self.debt.save(update_fields=['paid_amount', 'status'])

    class Meta:
        verbose_name = "Qarz to'lovi"
        verbose_name_plural = "Qarz to'lovlari"
        ordering = ['-date']
