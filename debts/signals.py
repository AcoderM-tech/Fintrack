from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Debt
from core.notifications import check_debt_due


@receiver(post_save, sender=Debt)
def debt_notify(sender, instance, **kwargs):
    check_debt_due(instance)
