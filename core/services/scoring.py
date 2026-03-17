from django.db import transaction
from core.models import CompetitionResult, CompetitionTeamPrediction, CompetitionBonusPrediction, SeasonScore, Prediction, DailyScore, Player
from django.db.models import Sum, F
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

RUGBY_SCORING = {
    "Top 14": {
        "bonus": 200,      # Marqueur / Scoreur
        "winner": 200,
        "exact_rank": 80,
        "gap_1": 40,
        "gap_2": 20,
        "all_class" : 3000,
        "1st" : 300,
        "2nd" : 150,
        "3rd" : 50,
    },
    "Champions Cup": {
        "bonus": 0,        # Pas de bonus marqueur sur cette compète
        "winner": 200,
        "exact_rank": 50,
        "gap_1": 20,
        "gap_2": 0,
        "all_class" : 100,        
        "1st" : 150,
        "2nd" : 75,
        "3rd" : 25,
    },
    "6 Nations": {
        "bonus": 0,
        "winner": 100,
        "exact_rank": 50,
        "gap_1": 0,
        "gap_2": 0,
        "all_class" : 100,
        "1st" : 50,
        "2nd" : 25,
        "3rd" : 10,
    }
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
                
def compute_season_ranking_points(season_obj):
    """
    Calcule les points de Flair et de Vainqueur Final,
    puis attribue les bonus de podium aux 3 meilleurs joueurs basés sur le TOTAL.
    """
    res = CompetitionResult.objects.filter(season=season_obj).first()
    if not res:
        return "Erreur : Aucun résultat réel saisi."

    comp_name = season_obj.competition.name
    clean_key = "6 Nations" if "6 Nations" in comp_name else ("Top 14" if "Top 14" in comp_name else "Champions Cup")
    cfg = RUGBY_SCORING.get(clean_key, {})

    real_rankings = res.rankings_json.get('all', {})
    players = Player.objects.all()

    # --- ÉTAPE 1 : CALCUL INDIVIDUEL (RANGS + VAINQUEUR) ---
    for p in players:
        pts_flair = 0
        all_correct = True
        
        preds = CompetitionTeamPrediction.objects.filter(player=p, season=season_obj)
        if not preds.exists():
            all_correct = False
        else:
            for pr in preds:
                real_pos = real_rankings.get(pr.team.name)
                if real_pos == pr.position:
                    pts_flair += cfg.get("exact_rank", 0)
                else:
                    all_correct = False
        
        if all_correct and preds.count() >= 6: # Sécurité : il faut avoir pronostiqué les 6
            pts_flair += cfg.get("all_class", 0)

        bonus_pred = CompetitionBonusPrediction.objects.filter(player=p, season=season_obj).first()
        if bonus_pred and bonus_pred.winner == res.real_winner:
            # On utilise 100 ici comme tu l'as précisé
            pts_flair += 100 

        if p.user:
            ss, _ = SeasonScore.objects.get_or_create(
                user=p.user, season=season_obj, competition=season_obj.competition
            )
            # IMPORTANT : On remplace (on n'ajoute pas) pour pouvoir relancer le script
            ss.ranking_points = pts_flair
            ss.save()

# --- ÉTAPE 2 : PODIUM DES JOUEURS ---

    # 1. On récupère tous les scores de la saison
    all_scores = list(SeasonScore.objects.filter(season=season_obj))
    
    # 2. On trie la liste Python. 
    # Pour chaque score 'x', on calcule (Matchs + Flair actuel) pour le tri.
    # On ajoute x.match_points en deuxième critère pour départager les égalités.
    all_scores.sort(
        key=lambda x: (x.match_points + x.ranking_points, x.match_points), 
        reverse=True
    )

    # 3. Attribution des bonus aux 3 premiers de cette liste triée
    podium_bonuses = [cfg.get("1st", 0), cfg.get("2nd", 0), cfg.get("3rd", 0)]
    labels = ["1er", "2ème", "3ème"]

    print(f"--- Classement Final {season_obj} ---")
    for i in range(min(3, len(all_scores))):
        score_obj = all_scores[i]
        bonus = podium_bonuses[i]
        
        # On affiche le score AVANT bonus pour vérifier
        total_avant = score_obj.match_points + score_obj.ranking_points
        
        # On applique le bonus de podium
        score_obj.ranking_points += bonus
        score_obj.save()
        
        print(f"{labels[i]} : {score_obj.user.username} | "
              f"Score (Matchs+Flair): {total_avant} pts | "
              f"Bonus Podium: +{bonus} | "
              f"Nouveau Total: {score_obj.total_points}")

    return f"Calcul du podium terminé pour {season_obj}."