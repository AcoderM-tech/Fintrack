from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Transaction
from core.notifications import handle_transaction_notifications, check_low_balance


@receiver(post_save, sender=Transaction)
def transaction_notify(sender, instance, **kwargs):
    handle_transaction_notifications(instance)


@receiver(post_delete, sender=Transaction)
def transaction_notify_delete(sender, instance, **kwargs):
    # After deletion, balances are already reverted in model.
    if instance.account_id:
        check_low_balance(instance.account)
    if instance.to_account_id:
        check_low_balance(instance.to_account)
