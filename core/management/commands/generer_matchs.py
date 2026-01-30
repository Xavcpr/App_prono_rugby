from django.core.management.base import BaseCommand, CommandError
from core.models import Competition, Season, Round, Match, Team

class Command(BaseCommand):
    help = "Génère des matchs pour une compétition, une saison et une journée précise."

    def add_arguments(self, parser):
        # Arguments obligatoires
        parser.add_argument('comp_name', type=str, help="Nom de la compétition (ex: 'Top 14')")
        parser.add_argument('season_year', type=str, help="Année de la saison (ex: '2025/2026')")
        parser.add_argument('round_num', type=int, help="Numéro de la journée")
        parser.add_argument('date', type=str, help="Date (YYYY-MM-DD)")
        # Liste des équipes (nargs='+' récupère tout ce qui reste)
        parser.add_argument('teams', nargs='+', type=str, help="Les 14 équipes")

    def handle(self, *args, **options):
        comp_name = options['comp_name']
        season_year = options['season_year']
        round_num = options['round_num']
        date_str = options['date']
        team_names = options['teams']

        # 1. Trouver la Saison (qui contient déjà la compétition)
        try:
            season = Season.objects.get(competition__name=comp_name, year=season_year)
        except Season.DoesNotExist:
            raise CommandError(f"La saison {season_year} pour {comp_name} n'existe pas.")

        # 2. Créer ou récupérer la journée (Round) liée à cette saison
        # Note : Si ton modèle Round n'a pas encore de lien vers Season, 
        # il utilise celui de Competition.
        round_obj, _ = Round.objects.get_or_create(
            competition=season.competition,
            number=round_num,
            defaults={'date': date_str}
        )

        # 3. Récupération des équipes (avec gestion des guillemets pour les espaces)
        teams = []
        for name in team_names:
            team = Team.objects.filter(name__iexact=name).first()
            if not team:
                raise CommandError(f"L'équipe '{name}' est introuvable.")
            teams.append(team)

        # 4. Création des matchs
        home_teams = teams[:7]
        away_teams = teams[7:]
        
        for home, away in zip(home_teams, away_teams):
            Match.objects.get_or_create(
                round=round_obj,
                home_team=home,
                away_team=away,
                defaults={'phase': "POOL"}
            )
            self.stdout.write(self.style.SUCCESS(f"Match créé : {home} vs {away} ({comp_name} {season_year})"))