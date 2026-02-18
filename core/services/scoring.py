from django.db import transaction
from core.models import Prediction, DailyScore, Player

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

# --- OUTILS DE CALCUL ---

def get_winner_side(score_home, score_away):
    if score_home > score_away: return "HOME"
    if score_away > score_home: return "AWAY"
    # if score_home + score_away ==0: return "NO SHOW"
    return "DRAW"

def calculate_match_points(prediction, match, winners_count):
    pts = 0
    cfg = SCORING_CONFIG
    multiplier = PHASE_MULTIPLIERS.get(match.phase, 1.0)
    
    if match.home_score is None or match.away_score is None:
        return 0

    # 1. PARTAGE DU POOL
    real_winner_side = get_winner_side(match.home_score, match.away_score)
    pred_winner_side = get_winner_side(prediction.home_score_pred, prediction.away_score_pred)
    
    # cas du no-show 
    if prediction.home_score_pred + prediction.away_score_pred ==0:
        pred_winner_side = "NO SHOW"
    
    if real_winner_side == pred_winner_side:
        if winners_count > 0:
            pts += (match.weight // winners_count)
        
        if real_winner_side == "AWAY": pts += cfg["AWAY_WIN_BONUS"]
        if real_winner_side == "DRAW": pts += cfg["DRAW_BONUS"]

    # 2. TOUT-PILE OU DEMI-TOUT-PILE
    if (prediction.home_score_pred == match.home_score and prediction.away_score_pred == match.away_score) and pred_winner_side != "NO SHOW":
        pts += cfg["PERFECT_SCORE_BONUS"]
    elif (prediction.home_score_pred == match.home_score or prediction.away_score_pred == match.away_score) and pred_winner_side != "NO SHOW":
        pts += cfg["HALF_PERFECT_BONUS"]

    # 3. BONUS OFFENSIF
    if prediction.bonus_home_pred:
        pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_home else cfg["BONUS_MALUS"]
    if prediction.bonus_away_pred:
        pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_away else cfg["BONUS_MALUS"]

    # 4. BONUS DÉFENSIF
    threshold = match.round.season.competition.bonus_defense_threshold
    real_diff = abs(match.home_score - match.away_score)
    pred_diff_val = abs(prediction.home_score_pred - prediction.away_score_pred)
    
    real_bd_side = None
    if 0 < real_diff <= threshold:
        real_bd_side = "HOME" if match.home_score < match.away_score else "AWAY"
        # real_bd_side peut être "HOME", "AWAY" ou None
        
    pred_bd_side = None
    if 0 < pred_diff_val <= threshold and pred_winner_side != "NO SHOW": # Je ne prends pas de bonus défensif si le joueur ne prédit pas de vainqueur
        if prediction.home_score_pred < prediction.away_score_pred:
            pred_bd_side = "HOME"
        elif prediction.away_score_pred < prediction.home_score_pred:
            pred_bd_side = "AWAY"
        else:
            pred_bd_side = "DRAW"
            # pred_bd_side peut donc être "DRAW", "HOME", "AWAY" ou None

    # si BD pronostiqué mais pas de match nul, alors bonus/malus selon que le côté pronostiqué est bien celui qui perd ou pas   
    if pred_bd_side == "HOME" or pred_bd_side == "AWAY":
        if pred_bd_side == real_bd_side or real_winner_side == "DRAW": # Si le bonus défensif est bien trouvé ou s'il y a match nul réel (dans ce cas, on considère que les deux équipes ont un bonus défensif)
            pts += cfg["DEFENSIVE_BONUS_VALUE"]
        elif real_bd_side is None:
            pts += cfg["BONUS_MALUS"]
    
    # si match nul pronostiqué, alors bonus/malus selon qu'il y a un BD ou pas
    if pred_bd_side == "DRAW":
        if real_bd_side is None:
            pts += cfg["BONUS_MALUS"]
        else:
            pts += cfg["DEFENSIVE_BONUS_VALUE"] 

    # 5. ÉCARTS
    gap_diff = abs(real_diff - pred_diff_val)
    if pred_winner_side != "NO SHOW":
        pts += cfg["DIFF_TABLE"].get(gap_diff, 0)
    gap_sum = abs((match.home_score + match.away_score) - (prediction.home_score_pred + prediction.away_score_pred))
    if pred_winner_side != "NO SHOW":
        pts += cfg["SUM_TABLE"].get(gap_sum, 0)

    return int(pts * multiplier)

# --- TRAITEMENT PAR LOT (BATCH) ---

# def process_round_scores(round_obj):
#     matches = round_obj.matches.all()
#     players = Player.objects.all()
    
#     with transaction.atomic():
#         match_winners_data = {}
#         for match in matches:
#             if match.home_score is not None and match.away_score is not None:
#                 real_side = get_winner_side(match.home_score, match.away_score)
#                 winners_count = 0
#                 all_preds = Prediction.objects.filter(match=match)
#                 for p in all_preds:
#                     if get_winner_side(p.home_score_pred, p.away_score_pred) == real_side:
#                         winners_count += 1
#                 match_winners_data[match.id] = winners_count

#         for match in matches:
#             if match.id in match_winners_data:
#                 predictions = Prediction.objects.filter(match=match)
#                 winners_cnt = match_winners_data[match.id]
#                 for pred in predictions:
#                     pred.points = calculate_match_points(pred, match, winners_cnt)
#                     pred.save()

#         for player in players:
#             total_day = 0
#             player_preds = Prediction.objects.filter(player=player, match__round=round_obj)
#             for p in player_preds:
#                 total_day += p.points
            
#             if player.user:
#                 ds, created = DailyScore.objects.get_or_create(user=player.user, round=round_obj)
#                 ds.points = total_day
#                 ds.save()


def process_round_scores(round_obj):
    matches = round_obj.matches.all()
    players = Player.objects.all()
    
    # Configuration des paliers (copiée de ta vue)
    BONUS_SCALES = {
        "Top 14": {7: 150, 6: 60, 5: 20},
        "Champions Cup": {12: 300, 11: 150, 10: 100, 9: 40}
    }
    comp_name = round_obj.season.competition.name
    current_scale = BONUS_SCALES.get(comp_name, {})

    with transaction.atomic():
        # 1. Calcul des gagnants par match (pour le pool)
        match_winners_data = {}
        for match in matches:
            if match.home_score is not None and match.away_score is not None:
                real_side = get_winner_side(match.home_score, match.away_score)
                winners_count = Prediction.objects.filter(match=match).extra(
                    where=["(home_score_pred > away_score_pred AND %s = 'HOME') OR "
                           "(away_score_pred > home_score_pred AND %s = 'AWAY') OR "
                           "(home_score_pred = away_score_pred AND %s = 'DRAW')"],
                    params=[real_side, real_side, real_side]
                ).count()
                match_winners_data[match.id] = winners_count

        # 2. Mise à jour des points par prédiction
        for match in matches:
            if match.id in match_winners_data:
                predictions = Prediction.objects.filter(match=match)
                winners_cnt = match_winners_data[match.id]
                for pred in predictions:
                    pred.points = calculate_match_points(pred, match, winners_cnt)
                    pred.save()

        # 3. Calcul du DailyScore (Total Matchs + Bonus de Palier)
        for player in players:
            total_match_points = 0
            correct_winners = 0
            
            player_preds = Prediction.objects.filter(player=player, match__round=round_obj)
            
            for p in player_preds:
                total_match_points += (p.points or 0)
                
                # On compte les victoires pour le palier
                m = p.match
                if m.home_score is not None and m.away_score is not None:
                    real_side = get_winner_side(m.home_score, m.away_score)
                    pred_side = get_winner_side(p.home_score_pred, p.away_score_pred)
                    if p.home_score_pred + p.away_score_pred == 0:
                        pred_side = "NO SHOW"
                    
                    if real_side == pred_side:
                        correct_winners += 1

            # Calcul du bonus de palier
            daily_bonus = 0
            for threshold in sorted(current_scale.keys(), reverse=True):
                if correct_winners >= threshold:
                    daily_bonus = current_scale[threshold]
                    break
            
            # Enregistrement du total réel
            if player.user:
                ds, created = DailyScore.objects.get_or_create(user=player.user, round=round_obj)
                ds.points = total_match_points + daily_bonus
                ds.save()