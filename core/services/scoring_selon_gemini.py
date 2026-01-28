from django.db.models import Count

# --- CONFIGURATION DU BARÈME ---
SCORING_CONFIG = {
    "MATCH_POOL_BASE": 680,
    "PERFECT_SCORE_BONUS": 680,
    "HALF_PERFECT_BONUS": 40,
    "AWAY_WIN_BONUS": 30,
    "DRAW_BONUS": 100,
    "OFFENSIVE_BONUS_VALUE": 15,
    "DEFENSIVE_BONUS_VALUE": 15,
    "BONUS_MALUS": -3,
    "DIFF_TABLE": {0: 15, 1: 12, 2: 10, 3: 8, 4: 6, 5: 4, 6: 2, 7: 1},
    "SUM_TABLE": {0: 8, 1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1},
}

PHASE_MULTIPLIERS = {
    "POOL": 1.0,
    "R16": 1.25,
    "QF": 1.5,
    "SF": 2.0,
    "FINAL": 3.0
}

def get_winner_side(score_home, score_away):
    if score_home > score_away: return "HOME"
    if score_away > score_home: return "AWAY"
    return "DRAW"

def calculate_match_points(prediction, match, winners_count):
    """
    Calcule les points totaux d'une prédiction pour un match donné.
    """
    pts = 0
    cfg = SCORING_CONFIG
    multiplier = PHASE_MULTIPLIERS.get(match.phase, 1.0)
    
    # 1. PARTAGE DU POOL (Le poids du match / nombre de gagnants)
    real_winner_side = get_winner_side(match.home_score, match.away_score)
    pred_winner_side = get_winner_side(prediction.home_score_pred, prediction.away_score_pred)
    
    if real_winner_side == pred_winner_side:
        # Partage des points (ex: 680 / 10 gagnants = 68 pts chacun)
        if winners_count > 0:
            pts += (match.weight / winners_count)
        
        # Bonus Victoire Extérieur (+30)
        if real_winner_side == "AWAY":
            pts += cfg["AWAY_WIN_BONUS"]
        
        # Bonus Match Nul (+100)
        if real_winner_side == "DRAW":
            pts += cfg["DRAW_BONUS"]

    # 2. TOUT-PILE OU DEMI-TOUT-PILE
    if prediction.home_score_pred == match.home_score and prediction.away_score_pred == match.away_score:
        pts += cfg["PERFECT_SCORE_BONUS"]
    elif prediction.home_score_pred == match.home_score or prediction.away_score_pred == match.away_score:
        pts += cfg["HALF_PERFECT_BONUS"]

    # 3. BONUS OFFENSIF (BO) - Basé sur les saisies admin/joueur
    if prediction.bonus_home_pred:
        pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_home else cfg["BONUS_MALUS"]
    if prediction.bonus_away_pred:
        pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_away else cfg["BONUS_MALUS"]

    # 4. BONUS DÉFENSIF (BD) - Automatique
    # On calcule si le joueur a prédit un score qui aurait donné un BD
    threshold = match.round.season.competition.bonus_threshold
    real_diff = abs(match.home_score - match.away_score)
    pred_diff_val = abs(prediction.home_score_pred - prediction.away_score_pred)
    
    # Est-ce qu'il y a un BD réel ?
    real_bd_side = None
    if 0 < real_diff <= threshold:
        real_bd_side = "HOME" if match.home_score < match.away_score else "AWAY"
        
    # Est-ce que le joueur a pronostiqué un score de BD ?
    if 0 < pred_diff_val <= threshold:
        pred_bd_side = "HOME" if prediction.home_score_pred < prediction.away_score_pred else "AWAY"
        # Si le côté du BD correspond au réel : bonus, sinon malus
        pts += cfg["DEFENSIVE_BONUS_VALUE"] if pred_bd_side == real_bd_side else cfg["BONUS_MALUS"]

    # 5. ÉCARTS DE DIFFÉRENCE ET DE SOMME
    gap_diff = abs(real_diff - pred_diff_val)
    pts += cfg["DIFF_TABLE"].get(gap_diff, 0)

    gap_sum = abs((match.home_score + match.away_score) - (prediction.home_score_pred + prediction.away_score_pred))
    pts += cfg["SUM_TABLE"].get(gap_sum, 0)

    # 6. APPLICATION DU MULTIPLICATEUR DE PHASE
    return pts * multiplier