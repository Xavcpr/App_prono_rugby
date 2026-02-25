from django.db import transaction
from core.models import Prediction, DailyScore, Player
import core.services.scoring as scoring

# --- CONFIGURATION DU BARÈME ---
SCORING_CONFIG = {
    "MATCH_POOL_BASE": 680,
    "PERFECT_SCORE_BONUS": 680,
    "HALF_PERFECT_BONUS": 40,
    "AWAY_WIN_BONUS": 15,
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

BONUS_SCALES = {
        "Top 14": {7: 150, 6: 60, 5: 20},
        "Champions Cup": {12: 300, 11: 150, 10: 100, 9: 40}
}

# --- OUTILS DE CALCUL ---

def get_winner_side(score_home, score_away):
    if score_home > score_away: return "HOME"
    if score_away > score_home: return "AWAY"
    return "DRAW"

def calculate_match_points(prediction, match, winners_count):
    """
    Calcule les points pour une seule prédiction.
    Utilisé par le traitement par lot.
    """
    pts = 0
    cfg = SCORING_CONFIG
    
    if match.home_score is None or match.away_score is None:
        return 0

    # 1. PARTAGE DU POOL
    real_winner_side = get_winner_side(match.home_score, match.away_score)
    pred_winner_side = get_winner_side(prediction.home_score_pred, prediction.away_score_pred)
    
    if prediction.home_score_pred + prediction.away_score_pred == 0:
        pred_winner_side = "NO SHOW"
    
    if real_winner_side == pred_winner_side:
        if winners_count > 0:
            pts += (match.weight // winners_count)
        
        if real_winner_side == "AWAY": pts += cfg["AWAY_WIN_BONUS"]
        if real_winner_side == "DRAW": pts += cfg["DRAW_BONUS"]

    # 2. TOUT-PILE OU DEMI-TOUT-PILE
    home_err = abs(prediction.home_score_pred - match.home_score)
    away_err = abs(prediction.away_score_pred - match.away_score)
    
    if pred_winner_side != "NO SHOW":
        if home_err == 0: pts += cfg["HALF_PERFECT_BONUS"]
        if away_err == 0: pts += cfg["HALF_PERFECT_BONUS"]
        if home_err == 0 and away_err == 0: pts += cfg["PERFECT_SCORE_BONUS"]

    # 3. BONUS OFFENSIF
    if prediction.bonus_home_pred:
        pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_home else cfg["BONUS_MALUS"]
    if prediction.bonus_away_pred:
        pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_away else cfg["BONUS_MALUS"]

    # 4. BONUS DÉFENSIF
    threshold = match.round.season.competition.bonus_defense_threshold
    real_bd_side = match.get_defense_bonus() # Utilise la méthode du modèle Match
    
    pred_diff_val = abs(prediction.home_score_pred - prediction.away_score_pred)
    pred_bd_side = None
    if pred_diff_val <= threshold and pred_winner_side != "NO SHOW":
        if prediction.home_score_pred < prediction.away_score_pred: pred_bd_side = "HOME"
        elif prediction.away_score_pred < prediction.home_score_pred: pred_bd_side = "AWAY"
        else: pred_bd_side = "DRAW"

    if pred_bd_side in ["HOME", "AWAY"]:
        if pred_bd_side == real_bd_side or match.home_score == match.away_score:
            pts += cfg["DEFENSIVE_BONUS_VALUE"]
        elif real_bd_side is None:
            pts += cfg["BONUS_MALUS"]
    elif pred_bd_side == "DRAW":
        if real_bd_side is not None: pts += cfg["DEFENSIVE_BONUS_VALUE"]
        else: pts += cfg["BONUS_MALUS"]

    # 5. ÉCARTS
    if pred_winner_side != "NO SHOW":
        diff_err = abs((prediction.home_score_pred - prediction.away_score_pred) - (match.home_score - match.away_score))
        sum_err = abs((prediction.home_score_pred + prediction.away_score_pred) - (match.home_score + match.away_score))
        pts += cfg["DIFF_TABLE"].get(diff_err, 0)
        pts += cfg["SUM_TABLE"].get(sum_err, 0)

    return pts

# --- TRAITEMENT PAR LOT (BATCH) ---

def process_round_scores(round_obj):
    """
    Calcule et enregistre tous les points pour un Round donné.
    """
    matches = round_obj.matches.all()
    players = Player.objects.all()
    
    # 1. Barème des Bonus de palier
    
    comp_name = round_obj.season.competition.name
    current_scale = BONUS_SCALES.get(comp_name, {})

    # 2. Pré-calcul du nombre de gagnants par match (pour le partage du pool)
    match_winners_counts = {}
    for m in matches:
        if m.home_score is not None and m.away_score is not None:
            real_side = get_winner_side(m.home_score, m.away_score)
            
            # Compte combien de joueurs ont trouvé le bon vainqueur
            winners_count = Prediction.objects.filter(match=m).extra(
                where=["(home_score_pred > away_score_pred AND %s = 'HOME') OR "
                       "(away_score_pred > home_score_pred AND %s = 'AWAY') OR "
                       "(home_score_pred = away_score_pred AND %s = 'DRAW')"],
                params=[real_side, real_side, real_side]
            ).count()
            match_winners_counts[m.id] = winners_count

    # 3. Calcul pour chaque joueur
    with transaction.atomic():
        for p in players:
            total_points_matchs = 0
            correct_winners_count = 0
            player_preds = Prediction.objects.filter(match__round=round_obj, player=p)

            for pr in player_preds:
                m = pr.match
                if m.home_score is None or m.away_score is None: continue
                
                # Calcul des points de base du match
                winners_cnt = match_winners_counts.get(m.id, 0)
                m_pts = calculate_match_points(pr, m, winners_cnt)
                
                # Vérification si vainqueur trouvé (pour le bonus de palier)
                real_side = get_winner_side(m.home_score, m.away_score)
                pred_side = get_winner_side(pr.home_score_pred, pr.away_score_pred)
                if pr.home_score_pred + pr.away_score_pred == 0: pred_side = "NO SHOW"
                
                if real_side == pred_side:
                    correct_winners_count += 1

                # Sauvegarde des points individuels du match
                pr.points = m_pts
                pr.save()
                total_points_matchs += m_pts

            # 4. Bonus de Palier (si applicable)
            day_bonus = 0
            for thresh in sorted(current_scale.keys(), reverse=True):
                if correct_winners_count >= thresh:
                    day_bonus = current_scale[thresh]
                    break
            
            # 5. Multiplicateurs (Phase et Compétition)
            # Utilisation de .matches au lieu de .match_set
            first_match = round_obj.matches.first()
            multiplier = PHASE_MULTIPLIERS.get(first_match.phase if first_match else "POOL", 1.0)
            
            if "6 Nations" in comp_name:
                multiplier *= 2.0

            # Calcul final pour la journée
            final_daily_score = (total_points_matchs + day_bonus) * multiplier
            
            if p.user:
                ds, _ = DailyScore.objects.get_or_create(user=p.user, round=round_obj)
                ds.points = int(final_daily_score)
                ds.save()