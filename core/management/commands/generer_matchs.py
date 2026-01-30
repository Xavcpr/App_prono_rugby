from django.core.management.base import BaseCommand, CommandError
from core.models import Competition, Season, Round, Match, Team

class Command(BaseCommand):
    help = "Génère des matchs pour une compétition, une saison et une journée précise."

    def add_arguments(self, parser):
        parser.add_argument('comp_name', type=str, help="Nom de la compétition (ex: 'Top 14')")
        parser.add_argument('season_year', type=str, help="Année de la saison (ex: '2025/2026')")
        parser.add_argument('round_num', type=int, help="Numéro de la journée")
        parser.add_argument('date', type=str, help="Date (YYYY-MM-DD)")
        parser.add_argument('teams', nargs='+', type=str, help="Les 14 équipes")

    def handle(self, *args, **options):
        comp_name = options['comp_name']
        season_year = options['season_year']
        round_num = options['round_num']
        date_str = options['date']
        team_names = options['teams']

        # 1. Trouver la Saison
        try:
            season = Season.objects.get(competition__name=comp_name, year=season_year)
        except Season.DoesNotExist:
            raise CommandError(f"La saison {season_year} pour {comp_name} n'existe pas.")

        # 2. Créer ou récupérer la journée (Round)
        # CORRECTION ICI : On retire 'competition' qui n'est pas un champ du modèle Round
        round_obj, _ = Round.objects.get_or_create(
            number=round_num,
            season=season,
            defaults={'date': date_str}
        )

        # 3. Récupération des équipes
        teams = []
        for name in team_names:
            team = Team.objects.filter(name__iexact=name).first()
            if not team:
                raise CommandError(f"L'équipe '{name}' est introuvable.")
            teams.append(team)

        # Vérification du nombre d'équipes
        if len(teams) % 2 != 0:
            raise CommandError("Le nombre d'équipes doit être pair pour créer des matchs.")

        # 4. Création des matchs
        mid = len(teams) // 2
        home_teams = teams[:mid]
        away_teams = teams[mid:]
        
        for home, away in zip(home_teams, away_teams):
            Match.objects.get_or_create(
                round=round_obj,
                home_team=home,
                away_team=away,
                defaults={'phase': "POOL"}
            )
            self.stdout.write(self.style.SUCCESS(f"Match créé : {home} vs {away}"))