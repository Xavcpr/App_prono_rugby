from django.core.management.base import BaseCommand
from core.models import Player, Season


class Command(BaseCommand):
    help = "Associe les joueurs existants à toutes les saisons (backfill après ajout du M2M)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--player",
            type=str,
            help="Nom du joueur à associer (optionnel : si omis, tous les joueurs)",
        )

    def handle(self, *args, **options):
        all_seasons = list(Season.objects.all())
        players = Player.objects.all()
        if options["player"]:
            players = players.filter(name__iexact=options["player"])

        for p in players:
            p.seasons.set(all_seasons)
            self.stdout.write(f"  {p.name} -> {len(all_seasons)} saisons")

        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {players.count()} joueurs, {len(all_seasons)} saisons"
        ))
