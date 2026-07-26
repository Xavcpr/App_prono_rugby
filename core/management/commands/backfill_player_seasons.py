from django.core.management.base import BaseCommand
from core.models import Player, Season


def get_season_key(year_str):
    if '/' in year_str: return year_str.split('/')[0]
    if '-' in year_str: return year_str.split('-')[0]
    if year_str.isdigit(): return str(int(year_str) - 1)
    return year_str


class Command(BaseCommand):
    help = "Associe les joueurs aux saisons (backfill après ajout du M2M)"

    def add_arguments(self, parser):
        parser.add_argument("--player", type=str, help="Nom du joueur (optionnel)")
        parser.add_argument("--latest-only", action="store_true",
                            help="N\'assigner que les saisons les plus récentes (clé année max, ex: 2026-2027)")

    def handle(self, *args, **options):
        all_seasons = list(Season.objects.all())
        # Ne garder que les saisons 2025+
        recent_seasons = [s for s in all_seasons if get_season_key(s.year).isdigit() and int(get_season_key(s.year)) >= 2025]

        if options["latest_only"]:
            # Ne garder que la clé d'année la plus élevée (ex: 2026)
            max_key = max(int(get_season_key(s.year)) for s in recent_seasons)
            targeted = [s for s in recent_seasons if int(get_season_key(s.year)) == max_key]
        else:
            targeted = recent_seasons

        players = Player.objects.all()
        if options["player"]:
            players = players.filter(name__iexact=options["player"])

        for p in players:
            p.seasons.set(targeted)
            self.stdout.write(f"  {p.name} -> {len(targeted)} saisons")

        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {players.count()} joueurs, {len(targeted)} saisons"
        ))
