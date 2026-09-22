from django.core.management.base import BaseCommand

from core.models import Season
from core.services.scoring import sync_season_match_points


class Command(BaseCommand):
    help = (
        "Resynchronise SeasonScore.match_points depuis les DailyScore pour "
        "réparer le classement global si certaines journées ont été calculées "
        "sans que la somme de saison soit mise à jour."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--season",
            help="Année de saison cible (ex. 2025/2026). Par défaut : toutes les saisons 2025+.",
        )

    def handle(self, *args, **options):
        seasons = Season.objects.filter(year__gte="2025").order_by("year")
        if options["season"]:
            seasons = Season.objects.filter(year=options["season"])

        total = 0
        for s in seasons:
            sync_season_match_points(s)
            total += 1
            self.stdout.write(f"OK : {s.competition.name} {s.year} — SeasonScore.match_points resynchronisé.")

        if not total:
            self.stdout.write("Aucune saison traitée.")
        else:
            self.stdout.write(f"{total} saison(s) resynchronisée(s). Reload la page de classement global.")