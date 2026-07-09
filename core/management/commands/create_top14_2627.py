import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Competition, Season, Round, Match, Team, MatchPhase

logger = logging.getLogger(__name__)

SEASON_YEAR = "2026/2027"
NUM_ROUNDS = 26
NUM_TEAMS = 14

FIXED_TEAMS = [
    "Bayonne", "Castres", "Clermont", "La Rochelle", "Lyon",
    "Montauban", "Montpellier", "Pau", "Perpignan", "Racing 92",
    "Stade français", "Toulon", "Toulouse", "UBB",
]

# Which team(s) to remove (relegated) and add (promoted)
RELEGATED_DEFAULT = "Montauban"
PROMOTED = "Vannes"


class Command(BaseCommand):
    help = f"Crée la saison Top 14 {SEASON_YEAR} avec rounds et équipes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--relegated",
            type=str,
            default=RELEGATED_DEFAULT,
            help=f"Équipe reléguée (défaut: {RELEGATED_DEFAULT})",
        )

    def handle(self, *args, **options):
        relegated_name = options["relegated"]

        competition = Competition.objects.filter(name="Top 14").first()
        if not competition:
            self.stdout.write(self.style.ERROR("Compétition Top 14 introuvable"))
            return

        season, created = Season.objects.get_or_create(
            competition=competition,
            year=SEASON_YEAR,
        )
        if created:
            self.stdout.write(f"Saison créée (ID={season.id})")
        else:
            self.stdout.write(f"Saison existante (ID={season.id})")

        # Determine the 14 teams
        team_names = list(FIXED_TEAMS)
        relegated = Team.objects.filter(name=relegated_name).first()
        if relegated:
            if relegated_name not in team_names:
                self.stdout.write(self.style.WARNING(
                    f"'{relegated_name}' n'est pas dans la liste des équipes fixes"
                ))
            else:
                team_names.remove(relegated_name)
                self.stdout.write(f"Équipe retirée : {relegated_name}")
        else:
            self.stdout.write(self.style.WARNING(
                f"Équipe reléguée '{relegated_name}' introuvable, aucune retirée"
            ))

        promoted = Team.objects.filter(name=PROMOTED).first()
        if promoted:
            if PROMOTED not in team_names:
                team_names.append(PROMOTED)
                self.stdout.write(f"Équipe ajoutée : {PROMOTED}")
        else:
            self.stdout.write(self.style.ERROR(
                f"Équipe promue '{PROMOTED}' introuvable ! Créez-la d'abord."
            ))
            return

        if len(team_names) != NUM_TEAMS:
            self.stdout.write(self.style.ERROR(
                f"Nombre d'équipes incorrect : {len(team_names)} (attendu {NUM_TEAMS})"
            ))
            return

        teams = list(Team.objects.filter(name__in=team_names))
        if len(teams) != NUM_TEAMS:
            missing = set(team_names) - {t.name for t in teams}
            self.stdout.write(self.style.ERROR(
                f"Équipes introuvables en DB : {missing}"
            ))
            return

        season.teams.set(teams)
        self.stdout.write(f"Équipes liées ({len(teams)}) : {[t.name for t in teams]}")

        with transaction.atomic():
            for round_num in range(1, NUM_ROUNDS + 1):
                round_obj, created = Round.objects.get_or_create(
                    season=season,
                    number=round_num,
                    defaults={"phase": MatchPhase.POOL},
                )
                if created:
                    self.stdout.write(f"  Round {round_num} créé")

        self.stdout.write(self.style.SUCCESS(
            f"Saison {SEASON_YEAR} prête : {NUM_ROUNDS} rounds, {len(teams)} équipes. "
            "Les matchs seront importés dès que TheSportsDB aura les données."
        ))
