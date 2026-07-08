from django.core.management.base import BaseCommand
from core.models import Season
from core.services.scores_importer import import_scores


class Command(BaseCommand):
    help = "Import match scores from TheSportsDB API"

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
            "--dry-run",
            action="store_true",
            help="Show what would be updated without writing to DB",
        )

    def handle(self, *args, **options):
        season_year = options.get("season")
        comp_name = options.get("competition")
        dry_run = options.get("dry_run", False)

        seasons_qs = Season.objects.all()
        if season_year:
            seasons_qs = seasons_qs.filter(year=season_year)
        if comp_name:
            seasons_qs = seasons_qs.filter(competition__name=comp_name)

        if not seasons_qs.exists():
            seasons_qs = Season.objects.filter(competition__name="Top 14").order_by("-id")[:1]

        for season in seasons_qs:
            self.stdout.write(f"--- {season.competition.name} {season.year} ---")
            result = import_scores(season, dry_run=dry_run)

            if result["status"] == "error":
                self.stderr.write(self.style.ERROR(result["message"]))
                continue

            for line in result["results"]:
                self.stdout.write(line)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Done: {result['updated']} updated, {result['skipped']} skipped"
                )
            )
