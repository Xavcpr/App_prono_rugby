from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Round
from .services.email_service import notify_new_round


@receiver(post_save, sender=Round)
def round_created_notification(sender, instance, created, **kwargs):
    if created:
        notify_new_round(instance)
