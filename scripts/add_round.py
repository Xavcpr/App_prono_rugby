# backend/add_round.py
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Competition, Round, Match, Team

# Exemple : ajouter Journée 2 Top 14
competition = Competition.objects.get(name="Top 14", season="2025-2026")

next_round_number = 2
next_round_date = "2026-02-01"  # à adapter

round_obj, created = Round.objects.get_or_create(
    competition=competition,
    number=next_round_number,
    defaults={"date": next_round_date}
)

if created:
    print(f"Journée {next_round_number} créée.")
else:
    print(f"Journée {next_round_number} déjà existante.")

# Créer les matchs vides pour la journée
teams = list(Team.objects.all())
for i in range(0, len(teams), 2):
    Match.objects.get_or_create(
        round=round_obj,
        home_team=teams[i],
        away_team=teams[i+1],
        defaults={"weight": competition.match_weight, "phase": "POOL"}
    )

print(f"Tous les matchs de la journée {next_round_number} ont été créés.")
