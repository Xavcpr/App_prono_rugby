from django.core.management.base import BaseCommand
from core.models import Season
from core.services.scores_importer import import_scores


class Command(BaseCommand):
    help = "Import match scores from TheSportsDB API for a given season"

    def add_arguments(self, parser):
        parser.add_argument(
            "--season",
            type=str,
            default=None,
            help="Season name (e.g. '2025-2026'). Defaults to latest.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without writing to DB",
        )

    def handle(self, *args, **options):
        season_name = options.get("season")
        dry_run = options.get("dry_run", False)

        if season_name:
            season = Season.objects.filter(year=season_name).first()
            if not season:
                self.stderr.write(self.style.ERROR(f"Season '{season_name}' not found"))
                return
        else:
            season = Season.objects.filter(competition__name="Top 14").order_by("-id").first()
            if not season:
                season = Season.objects.order_by("-id").first()
            if not season:
                self.stderr.write(self.style.ERROR("No seasons found"))
                return

        self.stdout.write(f"Importing scores for season: {season}")

        result = import_scores(season, dry_run=dry_run)

        if result["status"] == "error":
            self.stderr.write(self.style.ERROR(result["message"]))
            return

        for line in result["results"]:
            self.stdout.write(line)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {result['updated']} updated, {result['skipped']} skipped"
            )
        )
