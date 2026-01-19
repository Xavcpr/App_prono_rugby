# backend/core/services/scoring.py

from math import floor

# Pondérations par phase
PHASE_MULTIPLIERS = {
    "POOL": 1.0,
    "R16": 1.25,
    "QF": 1.5,
    "SF": 2,
    "FINAL": 3
}

def calculate_points(prediction, match):
    """
    Calcule les points d'un pronostic pour un match donné
    selon le barème complet (bonus offensif, diff, somme, victoire extérieure, tout-pile)
    et applique le poids du match + pondération phase finale.
    """

    points = 0
    competition = match.round.competition

    # --- Bonus offensif ---
    if prediction.bonus_offense_pred:
        # Exemple simple : bonus offensif correct si équipe pronostiquée a gagné avec bonus
        if hasattr(match, "bonus_offense_team"):
            if prediction.home_score_pred > prediction.away_score_pred and match.bonus_offense_team == match.home_team:
                points += 15
            elif prediction.away_score_pred > prediction.home_score_pred and match.bonus_offense_team == match.away_team:
                points += 15
            else:
                points -= 3

    # --- Différence de points ---
    if match.home_score is not None and match.away_score is not None:
        real_diff = match.home_score - match.away_score
        pred_diff = prediction.home_score_pred - prediction.away_score_pred
        delta = abs(real_diff - pred_diff)
        diff_points = [15, 12, 10, 8, 6, 4, 2, 1]  # delta 0 à 7+
        points += diff_points[min(delta, 7)]

    # --- Somme des scores ---
        real_sum = match.home_score + match.away_score
        pred_sum = prediction.home_score_pred + prediction.away_score_pred
        sum_delta = abs(real_sum - pred_sum)
        sum_points = [8, 6, 5, 4, 3, 2, 1]  # delta 0 à 6+
        points += sum_points[min(sum_delta, 6)]

    # --- Bon score / tout-pile ---
    if prediction.home_score_pred == match.home_score or prediction.away_score_pred == match.away_score:
        points += 40
    if prediction.home_score_pred == match.home_score and prediction.away_score_pred == match.away_score:
        points += 680

    # --- Victoire à l'extérieur ---
    if match.home_score is not None and match.away_score is not None:
        if match.away_score > match.home_score and prediction.away_score_pred > prediction.home_score_pred:
            points += 15

    # --- Match nul ---
    if match.home_score == match.away_score and prediction.home_score_pred == prediction.away_score_pred:
        points += 100

    # --- Poids du match ---
    winner_real = match.winner()
    if winner_real is not None:
        # Comptage des pronostics corrects pour appliquer le poids
        correct_preds = match.prediction_set.filter(
            home_score_pred__gt=match.away_score if winner_real == match.home_team else match.home_score,
        ).count()
        correct_preds = max(correct_preds, 1)  # éviter division par zéro
        weight_points = floor(match.weight / correct_preds)
        points += weight_points

    # --- Pondération phase finale ---
    points = floor(points * PHASE_MULTIPLIERS.get(match.phase, 1))

    # --- Enregistrement ---
    prediction.points = points
    prediction.save()

    return points
