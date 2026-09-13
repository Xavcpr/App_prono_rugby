from django.db.models import Q
from django.core.management.base import BaseCommand

from core.models import Match, Prediction


class Command(BaseCommand):
    help = (
        "Affiche tous les pronos (joueur + score + bonus) d'un match. "
        "Usage : show_match_prono <id> | show_match_prono <texte> | --list"
    )

    def add_arguments(self, parser):
        parser.add_argument("query", nargs="?", help="ID du match ou texte de recherche (nom d'équipe).")
        parser.add_argument("--list", action="store_true", help="Liste les matchs avec leurs IDs.")
        parser.add_argument("--competition", help="Filtre la liste par nom de compétition.")
        parser.add_argument("--season", help="Filtre la liste par année de saison (ex. 2026/2027).")
        parser.add_argument("--round", type=int, help="Filtre la liste par numéro de journée.")
        parser.add_argument(
            "--sort",
            choices=["name", "diff"],
            default="name",
            help="Tri des pronos : name (nom du joueur) ou diff (écart Domicile-Extérieur décroissant, "
                 "du plus optimiste pour le domicile au plus pessimiste ; en cas d'égalité, "
                 "le plus de points marqués à domicile d'abord).",
        )

    def handle(self, *args, **options):
        qs = Match.objects.select_related(
            "round__season__competition", "home_team", "away_team"
        )

        if options["competition"]:
            keyword = options["competition"]
            qs = qs.filter(round__season__competition__name__icontains=keyword)
        if options["season"]:
            qs = qs.filter(round__season__year=options["season"])
        if options["round"] is not None:
            qs = qs.filter(round__number=options["round"])

        if options["list"]:
            self._list_matches(qs, options)
            return

        query = (options["query"] or "").strip()
        if not query:
            self.stderr.write("Précise un ID de match (show_match_prono 701) ou --list pour voir les IDs.")
            self._list_matches(qs, options)
            return

        if query.isdigit():
            match = qs.filter(id=int(query)).first()
            if match is None:
                self.stderr.write(f"Match #{query} introuvable.")
                return
        else:
            matches = list(
                qs.filter(
                    Q(home_team__name__icontains=query)
                    | Q(away_team__name__icontains=query)
                ).distinct().order_by("-kickoff_at")
            )
            if not matches:
                self.stderr.write(f"Aucun match ne correspond à « {query} ».")
                return
            if len(matches) > 1:
                self.stderr.write(f"{len(matches)} matchs trouvés, précise ta recherche ou utimise un ID :")
                self._list_matches(Match.objects.filter(id__in=[m.id for m in matches]))
                return
            match = matches[0]

        self._show_match(match, sort_by=options["sort"])

    def _list_matches(self, qs, options=None):
        matches = list(qs.order_by("round__season__year", "-round__number", "kickoff_at"))
        if not matches:
            self.stdout.write("Aucun match.")
            return
        if options is not None:
            self.stdout.write("Matchs correspondants (utilise l'ID dans la 1re colonne) :")
        for m in matches:
            score = f"{m.home_score}-{m.away_score}" if m.home_score is not None else "à jouer"
            kick = f"{m.kickoff_at:%d/%m/%Y %H:%M}" if m.kickoff_at else "horaire inconnu"
            home = m.home_team.name if m.home_team else "?"
            away = m.away_team.name if m.away_team else "?"
            self.stdout.write(
                f"#{m.id:<6} | {m.round.season.competition.name} {m.round.season.year} "
                f"| J{m.round.number:<3} | {kick} "
                f"| {home} vs {away} | {score}"
            )

    def _show_match(self, match, sort_by="name"):
        season = match.round.season
        kick = f"{match.kickoff_at:%d/%m/%Y %H:%M}" if match.kickoff_at else "horaire inconnu"
        score_real = (
            f"{match.home_score}-{match.away_score}" if match.home_score is not None else "pas de score"
        )
        home = match.home_team.name if match.home_team else "?"
        away = match.away_team.name if match.away_team else "?"
        self.stdout.write(
            f"\nMatch #{match.id} — {season.competition.name} {season.year} J{match.round.number} "
            f"({kick})"
        )
        self.stdout.write(f"{home} vs {away} — réel : {score_real}")
        self.stdout.write("Pronos :")

        preds = list(
            Prediction.objects.filter(match=match)
            .select_related("player")
        )
        if sort_by == "diff":
            preds.sort(
                key=lambda p: (
                    p.home_score_pred - p.away_score_pred,
                    p.home_score_pred,
                ),
                reverse=True,
            )
        else:
            preds.sort(key=lambda p: p.player.name)
        if not preds:
            self.stdout.write("  (aucun prono pour ce match)")
            return
        for p in preds:
            parts = [f"{p.player.name}: {p.home_score_pred}-{p.away_score_pred}"]
            if sort_by == "diff":
                diff = p.home_score_pred - p.away_score_pred
                sign = "+" if diff >= 0 else ""
                parts.append(f"[{sign}{diff}]")
            extras = []
            if p.bonus_home_pred:
                extras.append("BO D")
            if p.bonus_away_pred:
                extras.append("BO E")
            if extras:
                parts.append("[" + ", ".join(extras) + "]")
            if getattr(p, "points", None) is not None:
                parts.append(f"{p.points} pts")
            self.stdout.write(f"  {'  '.join(parts)}")