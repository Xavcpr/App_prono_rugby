from core.services.scoring import calculate_points, apply_phase_multiplier


def compute_prediction_points(prediction, match):
    """
    Calcule et sauvegarde le score final d'un pronostic
    (score brut + pondération phase finale)
    """

    raw_points = calculate_points(prediction, match)
    final_points = apply_phase_multiplier(raw_points, match)

    prediction.points = final_points
    prediction.save(update_fields=["points"])

    return final_points