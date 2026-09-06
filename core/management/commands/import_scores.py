from django.core.management.base import BaseCommand
from core.models import Season
from core.services.scores_importer import import_scores
from core.management.commands.backfill_player_seasons import get_season_key

PRONO_START_YEAR = 2025  # ère pronos : 2025/2026, 2026, 2026/2027, 2027...


class Command(BaseCommand):
    help = "Import match scores and fixtures from TheSportsDB API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--season",
            type=str,
            default=None,
            help="Season year (e.g. '2025/2026' or '2026'). Defaults to latest.",
        )
        parser.add_argument(
            "--competition",
            type=str,
            default=None,
            help="Competition name (e.g. 'Top 14', '6 Nations', 'Champions Cup'). Defaults to all.",
        )
        parser.add_argument(
            "--all-seasons",
            action="store_true",
            help="Traiter aussi les saisons archivées (avant l'ère pronos). Par défaut seules les saisons de pronos sont traitées.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without writing to DB",
        )
        parser.add_argument(
            "--quick",
            action="store_true",
            help="Use only the season endpoint (faster, for cron)",
        )
        parser.add_argument(
            "--no-create",
            action="store_true",
            help="Don't create missing matches, only update scores",
        )
        parser.add_argument(
            "--auto-create-teams",
            action="store_true",
            help="Create unknown teams automatically in DB and mapping",
        )

    def handle(self, *args, **options):
        season_year = options.get("season")
        comp_name = options.get("competition")
        all_seasons = options.get("all_seasons", False)
        dry_run = options.get("dry_run", False)
        quick = options.get("quick", False)
        no_create = options.get("no_create", False)
        auto_create_teams = options.get("auto_create_teams", False)

        def is_prono_era(season):
            key = get_season_key(season.year)
            return key.isdigit() and int(key) >= PRONO_START_YEAR

        seasons = list(Season.objects.all())
        if season_year:
            seasons = [s for s in seasons if s.year == season_year]
        elif not all_seasons:
            seasons = [s for s in seasons if is_prono_era(s)]
        if comp_name:
            seasons = [s for s in seasons if s.competition.name == comp_name]

        if not seasons:
            fallback = Season.objects.filter(competition__name="Top 14").order_by("-id").first()
            if fallback:
                seasons = [fallback]
        if not seasons:
            self.stderr.write(self.style.ERROR("Aucune saison trouvée."))
            return

        for season in seasons:
            self.stdout.write(f"--- {season.competition.name} {season.year} ---")
            result = import_scores(season, dry_run=dry_run, quick=quick, create_matches=not no_create, auto_create_teams=auto_create_teams, aborted_rounds=1)

            if result["status"] == "error":
                self.stderr.write(self.style.ERROR(result["message"]))
                continue

            for line in result["results"]:
                self.stdout.write(line)

            created = result.get('created', 0)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done: {created} créés, {result['updated']} mis à jour, {result['skipped']} ignorés"
                )
            )
