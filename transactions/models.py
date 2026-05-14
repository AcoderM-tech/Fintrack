from django.db import models, transaction as db_transaction
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from accounts_app.models import Account
from core.models import FamilyGroup
from decimal import Decimal


class Category(models.Model):
    CATEGORY_TYPES = [
        ('expense', 'Xarajat'),
        ('income', 'Daromad'),
        ('both', 'Ikkalasi'),
    ]
    name = models.CharField(max_length=100, verbose_name="Nomi")
    icon = models.CharField(max_length=32, default='tag', verbose_name="Belgi")
    color = models.CharField(max_length=7, default='#6366f1', verbose_name="Rang")
    category_type = models.CharField(max_length=10, choices=CATEGORY_TYPES, default='expense')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='categories')
    family = models.ForeignKey(FamilyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='categories')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Kategoriya"
        verbose_name_plural = "Kategoriyalar"
        ordering = ['name']


class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('expense', 'Xarajat'),
        ('income', 'Daromad'),
        ('transfer', 'Transfer'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    family = models.ForeignKey(FamilyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, verbose_name="Turi")
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Summa")
    currency = models.CharField(max_length=3, default='UZS', verbose_name="Valyuta")
    account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, related_name='transactions', verbose_name="Hisob raqam")
    to_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name='incoming_transfers', verbose_name="Qabul qiluvchi hisob")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kategoriya")
    description = models.CharField(max_length=500, blank=True, verbose_name="Tavsif")
    date = models.DateField(verbose_name="Sana")
    exchange_rate = models.DecimalField(max_digits=15, decimal_places=4, default=1, verbose_name="Valyuta kursi")
    converted_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True, verbose_name="Konvertatsiya qilingan summa")
    notes = models.TextField(blank=True, verbose_name="Qo'shimcha izoh")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.amount} {self.currency} ({self.date})"

    def _validate_basic(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError("Summa 0 dan katta bo'lishi kerak.")
        if self.family_id:
            if self.account and self.account.family_id != self.family_id:
                raise ValidationError("Hisob oilaviy tranzaksiya uchun mos emas.")
            if self.to_account and self.to_account.family_id != self.family_id:
                raise ValidationError("Qabul qiluvchi hisob oilaviy tranzaksiya uchun mos emas.")
            if self.category and self.category.family_id and self.category.family_id != self.family_id:
                raise ValidationError("Kategoriya oilaviy tranzaksiya uchun mos emas.")
        else:
            if self.account and self.account.family_id is not None:
                raise ValidationError("Shaxsiy tranzaksiya uchun shaxsiy hisob tanlang.")
            if self.to_account and self.to_account.family_id is not None:
                raise ValidationError("Shaxsiy transfer uchun shaxsiy hisob tanlang.")
        if self.transaction_type == 'transfer':
            if not self.account_id or not self.to_account_id:
                raise ValidationError("Transfer uchun ikkala hisob ham kerak.")
            if self.account_id == self.to_account_id:
                raise ValidationError("Manba va qabul qiluvchi hisob bir xil bo'lmasligi kerak.")
        else:
            if not self.account_id:
                raise ValidationError("Hisob tanlanishi shart.")

    def _balance_deltas(self):
        """Account balanslaridagi o'zgarishlar xaritasi (account_id -> delta)."""
        deltas = {}
        if self.transaction_type == 'expense':
            if self.account_id:
                deltas[self.account_id] = deltas.get(self.account_id, Decimal('0')) - self.amount
        elif self.transaction_type == 'income':
            if self.account_id:
                deltas[self.account_id] = deltas.get(self.account_id, Decimal('0')) + self.amount
        elif self.transaction_type == 'transfer':
            if self.account_id:
                deltas[self.account_id] = deltas.get(self.account_id, Decimal('0')) - self.amount
            if self.to_account_id:
                converted = self.converted_amount or self.amount
                deltas[self.to_account_id] = deltas.get(self.to_account_id, Decimal('0')) + converted
        return deltas

    def save(self, *args, **kwargs):
        old = None
        if self.pk:
            try:
                old = Transaction.objects.get(pk=self.pk)
            except Transaction.DoesNotExist:
                old = None

        self._normalize_fields()

        # AI auto-kategoriya (faqat yangi tranzaksiya va kategoriya yo'q bo'lganda)
        if not self.pk and self.transaction_type == 'expense' and not self.category_id and self.description:
            try:
                from core.ai import auto_assign_category
                auto_cat = auto_assign_category(self.user, self.description, family=self.family)
                if auto_cat:
                    self.category = auto_cat
            except Exception:
                pass

        self._validate_basic()

        with db_transaction.atomic():
            # Lock barcha tegishli accountlarni
            account_ids = set()
            for tx in (old, self):
                if tx and tx.account_id:
                    account_ids.add(tx.account_id)
                if tx and tx.to_account_id:
                    account_ids.add(tx.to_account_id)

            locked_accounts = {}
            if account_ids:
                locked_accounts = {
                    acc.id: acc
                    for acc in Account.objects.select_for_update().filter(pk__in=account_ids)
                }

            new_deltas = self._balance_deltas()
            old_deltas = old._balance_deltas() if old else {}

            # Net delta = yangi - eski (bir atomik update)
            net_deltas = {}
            for acc_id in set(new_deltas) | set(old_deltas):
                net_deltas[acc_id] = (
                    new_deltas.get(acc_id, Decimal('0'))
                    - old_deltas.get(acc_id, Decimal('0'))
                )

            # Balans yetarliligi tekshiruvi
            for acc_id, delta in net_deltas.items():
                if delta < 0:
                    acc = locked_accounts.get(acc_id)
                    if acc and (acc.balance + delta) < 0:
                        raise ValidationError("Hisobda yetarli mablag' yo'q.")

            # DB ga yozish
            super().save(*args, **kwargs)

            # Balanslarni to'g'ridan-to'g'ri net delta bilan yangilash (double-update bug FIX)
            for acc_id, delta in net_deltas.items():
                if delta != 0:
                    acc = locked_accounts.get(acc_id)
                    if acc:
                        acc.balance += delta
                        acc.save(update_fields=['balance'])

    def _normalize_fields(self):
        try:
            self.amount = Decimal(str(self.amount or 0))
        except Exception:
            self.amount = Decimal('0')

        if self.exchange_rate not in (None, ''):
            try:
                self.exchange_rate = Decimal(str(self.exchange_rate))
            except Exception:
                self.exchange_rate = Decimal('1')
        else:
            self.exchange_rate = Decimal('1')

        if self.converted_amount in ('', None):
            self.converted_amount = None
        else:
            try:
                self.converted_amount = Decimal(str(self.converted_amount))
            except Exception:
                self.converted_amount = None

        if self.account:
            self.currency = self.account.currency

        if self.transaction_type != 'transfer':
            self.to_account = None
            self.exchange_rate = Decimal('1')
            self.converted_amount = None
            return

        if not self.account or not self.to_account:
            self.converted_amount = None
            return

        if self.account.currency != self.to_account.currency:
            rate = Decimal(str(self.exchange_rate or 1))
            if rate <= 0:
                rate = Decimal('1')
            if self.converted_amount is None:
                self.converted_amount = Decimal(str(self.amount)) * rate
        else:
            self.exchange_rate = Decimal('1')
            self.converted_amount = None

    def delete(self, *args, **kwargs):
        with db_transaction.atomic():
            account_ids = set()
            if self.account_id:
                account_ids.add(self.account_id)
            if self.to_account_id:
                account_ids.add(self.to_account_id)
            locked_accounts = {}
            if account_ids:
                locked_accounts = {
                    acc.id: acc
                    for acc in Account.objects.select_for_update().filter(pk__in=account_ids)
                }
            deltas = self._balance_deltas()
            super().delete(*args, **kwargs)
            # Reverse deltas
            for acc_id, delta in deltas.items():
                acc = locked_accounts.get(acc_id)
                if acc and delta != 0:
                    acc.balance -= delta
                    acc.save(update_fields=['balance'])

    class Meta:
        verbose_name = "Tranzaksiya"
        verbose_name_plural = "Tranzaksiyalar"
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'family', 'date']),
            models.Index(fields=['family', 'date']),
            models.Index(fields=['user', 'date']),
            models.Index(fields=['transaction_type', 'date']),
            models.Index(fields=['category', 'date']),
            models.Index(fields=['account', 'date']),
        ]
