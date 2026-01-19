# backend/init_top14_mvp.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Team, Player, Competition, Round, Match

# --- 1. Créer les équipes Top 14 ---
top14_teams = ["RCT", "SR", "ST", "ASM", "UBB", "LOU", "R92", "USM", "CO", "SF", "MHR", "Pau", "AB", "USAP"]

for team_name in top14_teams:
    Team.objects.get_or_create(name=team_name)

print(f"{len(top14_teams)} équipes créées ou existantes.")

# --- 2. Créer les joueurs ---
player_names = [
    "Alex Collet", "Alex Laval", "Antoine", "Augustin", "Axel", "Cédric", "Hervé",
    "Luc", "Michael", "Mike", "Robin", "Seb Tourne", "Séby", "Stéphane", "Thierry",
    "Vianney", "Xavier"
]

for player_name in player_names:
    Player.objects.get_or_create(name=player_name)

print(f"{len(player_names)} joueurs créés ou existants.")

# --- 3. Créer la compétition Top 14 ---
competition, created = Competition.objects.get_or_create(
    name="Top 14",
    season="2025-2026",
    defaults={"bonus_defense_threshold": 5, "match_weight": 680}
)

if created:
    print("Compétition Top 14 créée.")
else:
    print("Compétition Top 14 déjà existante.")

# --- 4. Créer la prochaine journée ---
next_round, created = Round.objects.get_or_create(
    competition=competition,
    number=15,  # numéro de la journée à adapter
    defaults={"date": "2026-01-25"}  # à adapter à la date réelle
)

if created:
    print(f"Journée {next_round.number} créée.")
else:
    print(f"Journée {next_round.number} déjà existante.")

# --- 5. Créer des matchs vides pour la journée ---
# Exemple d’affectation des matchs : ici 7 matchs pour 14 équipes
team_objs = list(Team.objects.all())
for i in range(0, len(team_objs), 2):
    home = team_objs[i]
    away = team_objs[i+1]
    match, created = Match.objects.get_or_create(
        round=next_round,
        home_team=home,
        away_team=away,
        defaults={"weight": competition.match_weight, "phase": "POOL"}
    )
    if created:
        print(f"Match créé : {home.name} vs {away.name}")
    else:
        print(f"Match existant : {home.name} vs {away.name}")

print("Initialisation MVP Top 14 terminée !")
