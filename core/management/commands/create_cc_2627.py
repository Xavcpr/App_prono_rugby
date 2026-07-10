import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Competition, Season, Round, Team, MatchPhase

logger = logging.getLogger(__name__)

SEASON_YEAR = "2026/2027"
NUM_ROUNDS = 8
POOL_ROUNDS = 4


class Command(BaseCommand):
    help = f"Crée la saison Champions Cup {SEASON_YEAR} avec rounds"

    def add_arguments(self, parser):
        parser.add_argument(
            "--num-rounds",
            type=int,
            default=NUM_ROUNDS,
            help="Nombre total de rounds (pools + phases finales)",
        )
        parser.add_argument(
            "--pool-rounds",
            type=int,
            default=POOL_ROUNDS,
            help="Nombre de rounds de poules",
        )

    def handle(self, *args, **options):
        num_rounds = options["num_rounds"]
        pool_rounds = options["pool_rounds"]

        competition = Competition.objects.filter(name="Champions Cup").first()
        if not competition:
            self.stdout.write(self.style.ERROR("Compétition Champions Cup introuvable"))
            return

        season, created = Season.objects.get_or_create(
            competition=competition,
            year=SEASON_YEAR,
        )
        if created:
            self.stdout.write(f"Saison créée (ID={season.id})")
        else:
            self.stdout.write(f"Saison existante (ID={season.id})")

        with transaction.atomic():
            for round_num in range(1, num_rounds + 1):
                if round_num <= pool_rounds:
                    phase = MatchPhase.POOL
                elif round_num == pool_rounds + 1:
                    phase = MatchPhase.R16
                elif round_num == pool_rounds + 2:
                    phase = MatchPhase.QF
                elif round_num == pool_rounds + 3:
                    phase = MatchPhase.SF
                else:
                    phase = MatchPhase.FINAL
                round_obj, created = Round.objects.get_or_create(
                    season=season,
                    number=round_num,
                    defaults={"phase": phase},
                )
                if created:
                    self.stdout.write(f"  Round {round_num} créé (phase={phase})")

        self.stdout.write(self.style.SUCCESS(
            f"Saison {SEASON_YEAR} prête : {num_rounds} rounds. "
            "Les équipes et matchs seront importés depuis TheSportsDB "
            "(lancer avec --auto-create-teams pour créer les équipes automatiquement)."
        ))
