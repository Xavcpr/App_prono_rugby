# backend/init_recalculate_scores.py

import os
import django

# --- Configuration Django ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Competition, Round, Match, Prediction, DailyScore, SeasonScore
from core.services.scoring import calculate_points
from django.db.models import Sum

def recalc_competition(competition_name, season):
    """Recalcule tous les points pour une compétition donnée"""
    
    competition = Competition.objects.get(name=competition_name, season=season)
    print(f"Recalcul des points pour {competition}...")

    # --- Boucle sur toutes les journées et matchs ---
    for round_obj in Round.objects.filter(competition=competition):
        print(f"Journée {round_obj.number}...")
        for match in Match.objects.filter(round=round_obj):
            for pred in match.prediction_set.all():
                calculate_points(pred, match)

        # --- DailyScore ---
        for player_id, total in Prediction.objects.filter(
            match__round=round_obj
        ).values('player').annotate(points_sum=Sum('points')).values_list('player', 'points_sum'):
            DailyScore.objects.update_or_create(
                user_id=player_id,
                journee=round_obj,
                defaults={'points': total}
            )

    # --- SeasonScore ---
    for player_id, total in Prediction.objects.filter(
        match__round__competition=competition
    ).values('player').annotate(points_sum=Sum('points')).values_list('player', 'points_sum'):
        SeasonScore.objects.update_or_create(
            user_id=player_id,
            competition=competition,
            defaults={'points': total}
        )

    print("Recalcul terminé !")

# --- Exemple d'utilisation ---
if __name__ == "__main__":
    recalc_competition("Champions Cup", "2025-2026")
