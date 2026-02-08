import os
import django
import pandas as pd

# Configuration de l'environnement Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings') # Vérifie le nom de ton dossier settings
django.setup()

from core.models import Player, Competition, Team, CompetitionTeamPrediction, CompetitionBonusPrediction

def import_excel_to_db(file_path, competition_name):
    # 1. Récupérer la compétition
    try:
        comp = Competition.objects.get(name__icontains=competition_name)
    except Competition.DoesNotExist:
        print(f"Erreur : La compétition '{competition_name}' n'existe pas en base.")
        return

    # 2. Charger le fichier Excel
    df = pd.read_excel(file_path)

    for index, row in df.iterrows():
        # Trouver le joueur
        player = Player.objects.filter(name__icontains=row['player_name']).first()
        if not player:
            print(f"Joueur non trouvé : {row['player_name']}")
            continue

        # Trouver l'équipe
        team = Team.objects.filter(name__icontains=row['team_name']).first()
        if not team:
            print(f"Équipe non trouvée : {row['team_name']}")
            continue

        # --- PARTIE 1 : CLASSEMENT ---
        # On utilise update_or_create pour éviter les doublons si on relance le script
        CompetitionTeamPrediction.objects.update_or_create(
            competition=comp,
            player=player,
            block_key=str(row['block_key']),
            position=int(row['position']),
            defaults={'team': team}
        )

        # --- PARTIE 2 : BONUS (Vainqueur, Buteurs) ---
        winner_team = None
        if pd.notna(row.get('winner_final')):
            winner_team = Team.objects.filter(name__icontains=row['winner_final']).first()

        bonus_defaults = {}
        if winner_team:
            bonus_defaults['winner'] = winner_team
        if 'best_try_scorer' in row and pd.notna(row['best_try_scorer']):
            bonus_defaults['best_try_scorer'] = row['best_try_scorer']
        if 'best_point_scorer' in row and pd.notna(row['best_point_scorer']):
            bonus_defaults['best_point_scorer'] = row['best_point_scorer']

        if bonus_defaults:
            CompetitionBonusPrediction.objects.update_or_create(
                competition=comp,
                player=player,
                defaults=bonus_defaults
            )

    print(f"Importation terminée pour {competition_name} !")

if __name__ == "__main__":
    # Remplace par les vrais noms de tes fichiers
    import_excel_to_db("import_class_cc.xlsx", "Champions Cup")
    import_excel_to_db("import_class_top14.xlsx", "Top 14")
    pass