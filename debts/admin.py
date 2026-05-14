from django.contrib import admin
from .models import Debt, DebtPayment
admin.site.register(Debt)
admin.site.register(DebtPayment)
