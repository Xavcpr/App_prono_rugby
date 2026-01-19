import sys
import os

# Ajouter le dossier courant au path pour que Python trouve ton projet
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Spécifier le module settings correct
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from core.models import Competition, ScoringConfig

# ----- Paramètres de la Champions Cup 2025-2026 -----
competition_name = "Champions Cup"
season = "2025-2026"

# Récupérer ou créer la compétition
competition, created = Competition.objects.get_or_create(
    name=competition_name,
    season=season,
    defaults={
        "bonus_defense_threshold": 7,  # seuil pour le bonus défensif
        "match_weight": 680            # poids des matchs
    }
)

# Liste des catégories et points pour cette saison
scoring_items = [
    # Bonus offensif
    {"category": "bonus_offense_correct", "delta": 0, "points": 15},
    {"category": "bonus_offense_wrong", "delta": 0, "points": -3},
    # Différence de points
    {"category": "diff_exact", "delta": 0, "points": 15},
    {"category": "diff_1", "delta": 1, "points": 12},
    {"category": "diff_2", "delta": 2, "points": 10},
    {"category": "diff_3", "delta": 3, "points": 8},
    {"category": "diff_4", "delta": 4, "points": 6},
    {"category": "diff_5", "delta": 5, "points": 4},
    {"category": "diff_6", "delta": 6, "points": 2},
    {"category": "diff_7", "delta": 7, "points": 1},
    # Somme des points
    {"category": "sum_exact", "delta": 0, "points": 8},
    {"category": "sum_1", "delta": 1, "points": 6},
    {"category": "sum_2", "delta": 2, "points": 5},
    {"category": "sum_3", "delta": 3, "points": 4},
    {"category": "sum_4", "delta": 4, "points": 3},
    {"category": "sum_5", "delta": 5, "points": 2},
    {"category": "sum_6", "delta": 6, "points": 1},
    # Bon score / demi-tout-pile
    {"category": "correct_score_one_team", "delta": 0, "points": 40},
    {"category": "correct_score_both_teams", "delta": 0, "points": 680},
    # Victoire à l’extérieur
    {"category": "away_win", "delta": 0, "points": 15},
    # Match nul
    {"category": "draw", "delta": 0, "points": 100},
]

# Création ou mise à jour des configs
for item in scoring_items:
    ScoringConfig.objects.update_or_create(
        competition=competition,
        category=item["category"],
        delta=item["delta"],
        defaults={"points": item["points"]}
    )

print(f"Scoring config pour {competition_name} {season} initialisée avec succès !")
