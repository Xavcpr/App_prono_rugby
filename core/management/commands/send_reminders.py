from django.core.management.base import BaseCommand
from core.services.email_service import send_round_reminders


class Command(BaseCommand):
    help = "Envoie les rappels H-24 et H-6 aux joueurs qui n'ont pas pronostiqué"

    def handle(self, *args, **options):
        send_round_reminders()
        self.stdout.write(self.style.SUCCESS("Rappels envoyés avec succès"))
