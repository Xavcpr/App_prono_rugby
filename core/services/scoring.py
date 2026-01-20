# backend/core/services/scoring.py

from math import floor

PHASE_MULTIPLIERS = {
    "POOL": 1.0,
    "R16": 1.25,
    "QF": 1.5,
    "SF": 2,
    "FINAL": 3
}

BONUS_OFF_SUCCESS = 15
BONUS_OFF_FAIL = -3

BONUS_DEF_SUCCESS = 15
BONUS_DEF_FAIL = -3


def calculate_points(prediction, match):
    points = 0

    # =========================
    # BONUS OFFENSIFS
    # =========================

    # Domicile
    if prediction.bonus_home_pred:
        if match.bonus_offense_home:
            points += BONUS_OFF_SUCCESS
        else:
            points += BONUS_OFF_FAIL

    # Extérieur
    if prediction.bonus_away_pred:
        if match.bonus_offense_away:
            points += BONUS_OFF_SUCCESS
        else:
            points += BONUS_OFF_FAIL
    
    # =========================
    # # BONUS DÉFENSIF (AUTO)
    # =========================

    real_home_def, real_away_def = get_defensive_bonus_teams(match)
    pred_home_def, pred_away_def = predicted_defensive_bonus(prediction, match)

    # Home
    if pred_home_def:
        if real_home_def:
            points += BONUS_DEF_SUCCESS
        else:
            points += BONUS_DEF_FAIL

    # Away
    if pred_away_def:
        if real_away_def:
            points += BONUS_DEF_SUCCESS
        else:
            points += BONUS_DEF_FAIL


    # =========================
    # DIFFÉRENCE DE POINTS
    # =========================

    if match.home_score is not None and match.away_score is not None:
        real_diff = match.home_score - match.away_score
        pred_diff = prediction.home_score_pred - prediction.away_score_pred
        delta = abs(real_diff - pred_diff)

        diff_points = [15, 12, 10, 8, 6, 4, 2, 1]
        points += diff_points[min(delta, 7)]

        # =========================
        # SOMME DES SCORES
        # =========================

        real_sum = match.home_score + match.away_score
        pred_sum = prediction.home_score_pred + prediction.away_score_pred
        sum_delta = abs(real_sum - pred_sum)

        sum_points = [8, 6, 5, 4, 3, 2, 1]
        points += sum_points[min(sum_delta, 6)]

    # =========================
    # SCORE EXACT / TOUT-PIL
    # =========================

    if prediction.home_score_pred == match.home_score:
        points += 40
    if prediction.away_score_pred == match.away_score:
        points += 40

    if (
        prediction.home_score_pred == match.home_score
        and prediction.away_score_pred == match.away_score
    ):
        points += 680

    # =========================
    # VICTOIRE À L’EXTÉRIEUR
    # =========================

    if (
        match.home_score is not None
        and match.away_score is not None
        and match.away_score > match.home_score
        and prediction.away_score_pred > prediction.home_score_pred
    ):
        points += 15

    # =========================
    # MATCH NUL
    # =========================

    if (
        match.home_score == match.away_score
        and prediction.home_score_pred == prediction.away_score_pred
    ):
        points += 100

    # =========================
    # POIDS DU MATCH
    # =========================

    winner_real = match.winner()
    if winner_real is not None:
        correct_preds = match.prediction_set.filter(
            home_score_pred__gt=match.away_score
            if winner_real == match.home_team
            else match.home_score
        ).count()

        correct_preds = max(correct_preds, 1)
        points += floor(match.weight / correct_preds)

    # =========================
    # PONDÉRATION PHASE
    # =========================

    points = floor(points * PHASE_MULTIPLIERS.get(match.phase, 1))

    prediction.points = points
    prediction.save()

    return points
