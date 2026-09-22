from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from core.models import DailyScore, Prediction, Season, SeasonHistory, SeasonScore


class Command(BaseCommand):
    help = (
        "Archive le classement final d'une saison terminee dans SeasonHistory "
        "(affichage Hall of Fame). Source : SeasonScore de l'app (totaux "
        "matchs + flair + podium), regroupes comme sur la page d'accueil "
        "(Top14/CC + 6 Nations debut-annee + 6 Nations fin-annee). "
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

        # Même regroupement que la page d'accueil (get_season_key) :
        # la saison 2025-2026 = 6N 2025 + Top14/CC 2025-2026 + 6N 2026,
        # la saison 2026-2027 = Top14/CC 2026-2027 + 6N 2027.
        seasons = Season.by_season_year(season_year)
        if not seasons:
            raise CommandError(
                f"Aucune saison trouvée pour la saison {season_year - 1}-{season_year}. "
                "Vérifie l'année de fin demandée."
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

        # Fallback match (DailyScore) : identique à home_view, qui prend
        # SeasonScore.match_points s'il est > 0 sinon la somme des DailyScore.
        ds_totals = {
            row["user__username"]: row["total"] or 0
            for row in DailyScore.objects.filter(
                round__season_id__in=group_season_ids
            ).values("user__username").annotate(total=Sum("points"))
        }

        ss_totals = {}
        for ss in SeasonScore.objects.filter(
            season_id__in=group_season_ids
        ).select_related("user"):
            uname = ss.user.username
            if uname not in participants:
                continue
            agg = ss_totals.setdefault(uname, {"match": 0, "ranking": 0, "podium": 0})
            agg["match"] += ss.match_points or 0
            agg["ranking"] += ss.ranking_points or 0
            agg["podium"] += ss.podium_points or 0

        totals = {}
        for uname in participants:
            agg = ss_totals.get(uname, {"match": 0, "ranking": 0, "podium": 0})
            match = agg["match"] if agg["match"] > 0 else ds_totals.get(uname, 0)
            totals[uname] = match + agg["ranking"] + agg["podium"]

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