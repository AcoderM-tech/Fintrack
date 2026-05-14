from django.db import models
from django.contrib.auth.models import User
from transactions.models import Category
from core.models import FamilyGroup
from decimal import Decimal
import datetime


class Budget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budgets')
    family = models.ForeignKey(FamilyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='budgets')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Kategoriya")
    name = models.CharField(max_length=100, verbose_name="Nomi")
    budget_type = models.CharField(max_length=10, choices=[
        ('expense', 'Xarajat limiti'),
        ('income', 'Daromad maqsadi'),
    ], default='expense')
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Rejalashtirilgan summa")
    currency = models.CharField(max_length=3, default='UZS')
    month = models.IntegerField(verbose_name="Oy")
    year = models.IntegerField(verbose_name="Yil")
    created_at = models.DateTimeField(auto_now_add=True)

    # ─── FIX: N+1 bug — get_spent endi precomputed_actual dan foydalanadi ───
    # View'lar precomputed_actual ni set qiladi, methodlar faqat fallback
    def _query_actual(self, tx_type):
        """Fallback — faqat birma-bir chaqirilsa (template outside list)"""
        from transactions.models import Transaction
        qs = Transaction.objects.filter(
            transaction_type=tx_type,
            date__month=self.month,
            date__year=self.year,
        )
        if self.family_id:
            qs = qs.filter(family=self.family)
        else:
            qs = qs.filter(user=self.user, family__isnull=True)
        if self.category_id:
            qs = qs.filter(category_id=self.category_id)
        from django.db.models import Sum
        return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    def get_spent(self):
        # View tomonidan precomputed_actual set qilingan bo'lsa — ishlatamiz (N+1 yo'q)
        if hasattr(self, '_precomputed_actual'):
            return Decimal(str(self._precomputed_actual))
        return self._query_actual('expense')

    def get_income(self):
        if hasattr(self, '_precomputed_actual'):
            return Decimal(str(self._precomputed_actual))
        return self._query_actual('income')

    def get_percentage(self):
        spent = self.get_spent() if self.budget_type == 'expense' else self.get_income()
        if not self.amount:
            return 0
        return min(int((spent / self.amount) * 100), 100)

    def get_remaining(self):
        spent = self.get_spent() if self.budget_type == 'expense' else self.get_income()
        return self.amount - spent

    def __str__(self):
        return f"{self.name} - {self.month}/{self.year}"

    class Meta:
        verbose_name = "Byudjet"
        verbose_name_plural = "Byudjetlar"
        ordering = ['-year', '-month']
        indexes = [
            models.Index(fields=['user', 'family', 'year', 'month']),
            models.Index(fields=['family', 'year', 'month']),
            models.Index(fields=['user', 'year', 'month']),
        ]
