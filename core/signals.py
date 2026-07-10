import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Round
from .services.email_service import notify_new_round


logger = logging.getLogger(__name__)


@receiver(post_save, sender=Round)
def round_created_notification(sender, instance, created, **kwargs):
    if created:
        try:
            notify_new_round(instance)
        except Exception:
            logger.warning("Failed to send round notification email", exc_info=True)
