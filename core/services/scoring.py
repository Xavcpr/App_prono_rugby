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
    if prediction.bonus_home_pred:
        points += BONUS_OFF_SUCCESS if match.bonus_offense_home else BONUS_OFF_FAIL
    if prediction.bonus_away_pred:
        points += BONUS_OFF_SUCCESS if match.bonus_offense_away else BONUS_OFF_FAIL

    # =========================
    # BONUS DÉFENSIF (AUTO)
    # =========================
    # uniquement en phase POOL
    if match.phase == "POOL":
        threshold = match.round.competition.bonus_defense_threshold

        # équipes perdantes avec score ≤ seuil
        real_home_def = match.home_score < match.away_score and (match.away_score - match.home_score) <= threshold
        real_away_def = match.away_score < match.home_score and (match.home_score - match.away_score) <= threshold

        # prédiction “bonus défensif” si diff pronostiquée ≤ seuil
        pred_home_def = prediction.home_score_pred < prediction.away_score_pred and \
                        (prediction.away_score_pred - prediction.home_score_pred) <= threshold
        pred_away_def = prediction.away_score_pred < prediction.home_score_pred and \
                        (prediction.home_score_pred - prediction.away_score_pred) <= threshold

        # points
        points += BONUS_DEF_SUCCESS if pred_home_def and real_home_def else 0
        points += BONUS_DEF_FAIL if pred_home_def and not real_home_def else 0

        points += BONUS_DEF_SUCCESS if pred_away_def and real_away_def else 0
        points += BONUS_DEF_FAIL if pred_away_def and not real_away_def else 0

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
    if prediction.home_score_pred == match.home_score and prediction.away_score_pred == match.away_score:
        points += 680

    # =========================
    # VICTOIRE À L’EXTÉRIEUR
    # =========================
    if match.home_score is not None and match.away_score is not None:
        if match.away_score > match.home_score and prediction.away_score_pred > prediction.home_score_pred:
            points += 15

    # =========================
    # MATCH NUL
    # =========================
    if match.home_score == match.away_score and prediction.home_score_pred == prediction.away_score_pred:
        points += 100

    # =========================
    # POIDS DU MATCH
    # =========================
    winner_real = match.winner()
    if winner_real is not None:
        correct_preds = match.prediction_set.filter(
            home_score_pred__gt=match.away_score if winner_real == match.home_team else match.home_score
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
