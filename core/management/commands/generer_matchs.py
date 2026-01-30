import datetime
from django.core.management.base import BaseCommand, CommandError
from core.models import Competition, Round, Match, Team

class Command(BaseCommand):
    help = "Génère 7 matchs pour une journée de Top 14 à partir d'une liste d'équipes"

    def add_arguments(self, parser):
        # On définit les arguments que tu devras taper dans le terminal
        parser.add_argument('round_number', type=int, help="Numéro de la journée")
        parser.add_argument('date', type=str, help="Date indicative (YYYY-MM-DD)")
        parser.add_argument('teams', nargs='+', type=str, help="Liste des 14 noms d'équipes séparés par des espaces")

    def handle(self, *args, **options):
        round_number = options['round_number']
        date_str = options['date']
        team_names = options['teams']

        # 1. Vérifications de base
        if len(team_names) != 14:
            raise CommandError(f"Il faut exactement 14 équipes (tu en as mis {len(team_names)})")

        try:
            comp = Competition.objects.get(name="Top 14")
        except Competition.DoesNotExist:
            raise CommandError("La compétition 'Top 14' n'existe pas en base de données.")

        # 2. Création/Récupération de la journée
        round_obj, created = Round.objects.get_or_create(
            competition=comp,
            number=round_number,
            defaults={'date': date_str}
        )

        # 3. Récupération des objets Teams
        teams = []
        for name in team_names:
            try:
                teams.append(Team.objects.get(name=name))
            except Team.DoesNotExist:
                raise CommandError(f"L'équipe '{name}' n'existe pas.")

        # 4. Appariement (7 premiers vs 7 derniers)
        home_teams = teams[:7]
        away_teams = teams[7:]
        
        count = 0
        for home, away in zip(home_teams, away_teams):
            _, created = Match.objects.get_or_create(
                round=round_obj,
                home_team=home,
                away_team=away,
                defaults={'weight': comp.match_weight, 'phase': "POOL"}
            )
            if created:
                count += 1
                self.stdout.write(self.style.SUCCESS(f"Match créé : {home} vs {away}"))
            else:
                self.stdout.write(self.style.WARNING(f"Match déjà existant : {home} vs {away}"))

        self.stdout.write(self.style.SUCCESS(f"Opération terminée : {count} matchs ajoutés à la J{round_number}."))