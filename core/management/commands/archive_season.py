from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.models import Prediction, Season, SeasonHistory, SeasonScore


class Command(BaseCommand):
    help = (
        "Archive le classement final d'une saison terminee dans SeasonHistory "
        "(affichage Hall of Fame). Source : SeasonScore de l'app (totaux "
        "matchs + flair + podium des competitions de la saison). "
        "season_year = annee de FIN de saison (ex. 2026 pour la 2025-2026)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "season_year", type=int,
            help="Annee de fin de la saison a archiver (ex. 2026 pour la 2025-2026).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche le classement sans ecrire en base.",
        )

    def handle(self, *args, **options):
        season_year = options["season_year"]
        dry_run = options["dry_run"]

        prefix = str(season_year - 1)
        seasons = list(Season.objects.filter(year__startswith=prefix).select_related("competition"))
        if not seasons:
            raise CommandError(
                f"Aucune saison trouvée commençant par '{prefix}' "
                "(ex. '2025', '2025/2026'). Vérifie l'année de fin demandée."
            )

        self.stdout.write(
            "Saisons prises en compte : "
            + ", ".join(f"{s.competition.name} {s.year}" for s in seasons)
        )

        group_season_ids = [s.id for s in seasons]

        # Participation réelle : au moins un pronostic déposé dans la saison.
        # (Les DailyScore existent pour tous les comptes à chaque journée jouée,
        # on ne peut pas s'y fier ; et les SeasonScore à 0 pt peuvent avoir été
        # créés par sync/match_points pour des comptes jamais actifs.)
        participants = set(
            Prediction.objects.filter(match__round__season_id__in=group_season_ids)
            .values_list("player__user__username", flat=True)
            .distinct()
        )
        if not participants:
            raise CommandError(
                "Aucun participant (aucun pronostic) pour cette saison — rien à archiver."
            )

        totals = {uname: 0 for uname in participants}
        for ss in SeasonScore.objects.filter(
            season_id__in=group_season_ids
        ).select_related("user"):
            if ss.user.username in totals:
                totals[ss.user.username] += (
                    (ss.match_points or 0) + (ss.ranking_points or 0) + (ss.podium_points or 0)
                )

        ranked = sorted(totals.items(), key=lambda x: (-x[1], x[0].lower()))
        total_players = len(ranked)

        if not dry_run:
            deleted, _ = SeasonHistory.objects.filter(season_year=season_year).delete()
            if deleted:
                self.stdout.write(f"{deleted} ligne(s) existante(s) écrasée(s) pour {season_year}.")

        self.stdout.write(f"Classement {season_year - 1}-{season_year} ({total_players} joueurs) :")
        for i, (uname, pts) in enumerate(ranked, 1):
            self.stdout.write(f"  {i:>2} | {uname} | {pts} pts")
            if not dry_run:
                user = User.objects.get(username=uname)
                SeasonHistory.objects.create(
                    season_year=season_year,
                    user=user,
                    rank=i,
                    total_players=total_players,
                )

        if dry_run:
            self.stdout.write("(--dry-run : rien n'a été écrit en base)")
        else:
            self.stdout.write(
                f"Archive écrit : {total_players} lignes SeasonHistory pour la saison "
                f"{season_year - 1}-{season_year} (season_year={season_year})."
            )