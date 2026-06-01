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

# Bonus journée tournoi des 6 nations pour ceux qui ont plus que X bons pronos
MASTER_PALIERS = {12: 50, 13: 150, 14: 200, 15: 250}
# --- OUTILS DE CALCUL ---

def get_winner_side(score_home, score_away):
    if score_home > score_away: return "HOME"
    if score_away > score_home: return "AWAY"
    return "DRAW"

def calculate_match_points(prediction, match, winners_count):
    pts = 0
    cfg = SCORING_CONFIG
    
    if match.home_score is None or match.away_score is None:
        return 0

    # SÉCURITÉ PHASE FINALE : On identifie si on doit compter les bonus
    is_pool_phase = (match.phase == "POOL")

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

    # 3. BONUS OFFENSIF (Uniquement en POOL)
    if is_pool_phase:
        if prediction.bonus_home_pred:
            pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_home else cfg["BONUS_MALUS"]
        if prediction.bonus_away_pred:
            pts += cfg["OFFENSIVE_BONUS_VALUE"] if match.bonus_offense_away else cfg["BONUS_MALUS"]

    # 4. BONUS DÉFENSIF (Uniquement en POOL)
    if is_pool_phase:
        threshold = match.round.season.competition.bonus_defense_threshold
        real_bd_side = match.get_defense_bonus()
        
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

def process_round_scores(round_obj):
    matches = round_obj.matches.all()
    players = Player.objects.all()
    comp_name = round_obj.season.competition.name
    current_scale = BONUS_SCALES.get(comp_name, {})

    # SÉCURITÉ : On s'assure que les matchs ont la même phase que la journée
    matches.update(phase=round_obj.phase)

    match_winners_counts = {}
    for m in matches:
        if m.home_score is not None and m.away_score is not None:
            real_side = get_winner_side(m.home_score, m.away_score)
            winners_count = Prediction.objects.filter(match=m).extra(
                where=["(home_score_pred > away_score_pred AND %s = 'HOME') OR "
                       "(away_score_pred > home_score_pred AND %s = 'AWAY') OR "
                       "(home_score_pred = away_score_pred AND %s = 'DRAW')"],
                params=[real_side, real_side, real_side]
            ).count()
            match_winners_counts[m.id] = winners_count

    with transaction.atomic():
        for p in players:
            total_points_matchs = 0
            correct_winners_count = 0
            player_preds = Prediction.objects.filter(match__round=round_obj, player=p)

            for pr in player_preds:
                m = pr.match
                if m.home_score is None or m.away_score is None: continue
                
                winners_cnt = match_winners_counts.get(m.id, 0)
                m_pts = calculate_match_points(pr, m, winners_cnt)
                
                real_side = get_winner_side(m.home_score, m.away_score)
                pred_side = get_winner_side(pr.home_score_pred, pr.away_score_pred)
                if pr.home_score_pred + pr.away_score_pred == 0: pred_side = "NO SHOW"
                
                if real_side == pred_side:
                    correct_winners_count += 1

                pr.points = m_pts
                pr.save()
                total_points_matchs += m_pts

            # Bonus de Palier
            day_bonus = 0
            for thresh in sorted(current_scale.keys(), reverse=True):
                if correct_winners_count >= thresh:
                    day_bonus = current_scale[thresh]
                    break
            
            # MULTIPLICATEUR (Appliqué sur tout : Matchs + Bonus de palier)
            multiplier = PHASE_MULTIPLIERS.get(round_obj.phase, 1.0)
            
            if "6 Nations" in comp_name:
                multiplier *= 2.0

            final_daily_score = (total_points_matchs + day_bonus) * multiplier
            
            if p.user:
                ds, _ = DailyScore.objects.get_or_create(user=p.user, round=round_obj)
                ds.points = int(final_daily_score)
                ds.save()   

def compute_season_ranking_points(season_obj):

    # --- ÉTAPE 0 : VÉRIFICATION DU JSON ET DES DONNÉES (SOUPLE) ---
    res = CompetitionResult.objects.filter(season=season_obj).first()
    if not res:
        return "Erreur : Aucun résultat créé pour cette saison."
    
    real_rankings = res.rankings_json.get('all', {})
    if not res.real_winner:
        return "Erreur : Le vainqueur réel (Winner) n'est pas renseigné."

    expected_teams = season_obj.teams.all() 
    missing_teams = [t.name for t in expected_teams if t.name not in real_rankings]
    if missing_teams:
        print(f"⚠️ Note : {len(missing_teams)} équipes absentes du JSON (ignorées pour le calcul).")

    # --- ÉTAPE 1 : SYNCHRONISATION DES POINTS DE MATCHS & RESET ---
    print(f"Synchronisation pour {season_obj}...")
    players = Player.objects.filter(user__isnull=False)
    for p in players:
        total_matchs = DailyScore.objects.filter(
            user=p.user, 
            round__season=season_obj
        ).aggregate(total=Sum('points'))['total'] or 0
        
        ss, _ = SeasonScore.objects.get_or_create(
            user=p.user, 
            season=season_obj, 
            competition=season_obj.competition
        )
        ss.match_points = total_matchs
        ss.ranking_points = 0  # Reset Flair
        ss.podium_points = 0   # RESET DU NOUVEAU CHAMP !
        ss.save()

    # --- ÉTAPE 2 : CALCUL DU FLAIR (Rangs + Gaps + Vainqueur + Master) ---
    comp_name = season_obj.competition.name
    clean_key = "6 Nations" if "6 Nations" in comp_name else ("Top 14" if "Top 14" in comp_name else "Champions Cup")
    cfg = RUGBY_SCORING.get(clean_key, {})

    for p in players:
        pts_flair = 0
        all_correct = True
        
        # A. Rangs et Gaps
        preds = CompetitionTeamPrediction.objects.filter(player=p, season=season_obj)
        for pr in preds:
            real_pos = real_rankings.get(pr.team.name)
            if real_pos is not None:
                gap = abs(pr.position - real_pos)
                if gap == 0:
                    pts_flair += cfg.get("exact_rank", 0)
                elif gap == 1:
                    pts_flair += cfg.get("gap_1", 0)
                    all_correct = False
                elif gap == 2:
                    pts_flair += cfg.get("gap_2", 0)
                    all_correct = False
                else:
                    all_correct = False
            else:
                all_correct = False
        
        # B. Bonus "All Class"
        if all_correct and preds.count() >= 6:
            pts_flair += cfg.get("all_class", 0)

        # C. Bonus Vainqueur Final
        bonus_pred = CompetitionBonusPrediction.objects.filter(player=p, season=season_obj).first()
        if bonus_pred and bonus_pred.winner == res.real_winner:
            pts_flair += cfg.get("winner", 100)

        # D. BONUS MASTER TOURNOI (6 Nations uniquement)
        if clean_key == "6 Nations":
            from core.models import Prediction
            user_preds = Prediction.objects.filter(
                player=p, 
                match__round__season=season_obj
            ).select_related('match', 'match__home_team', 'match__away_team')

            good_matches_count = 0
            for pr in user_preds:
                real_win = pr.match.winner()
                if pr.home_score_pred > pr.away_score_pred:
                    pred_win = pr.match.home_team
                elif pr.home_score_pred < pr.away_score_pred:
                    pred_win = pr.match.away_team
                else:
                    pred_win = None
                
                if real_win and pred_win and real_win == pred_win:
                    good_matches_count += 1
                elif real_win is None and pred_win is None and pr.match.home_score is not None:
                    good_matches_count += 1

            bonus_master = 0
            for seuil, valeur in sorted(MASTER_PALIERS.items(), reverse=True):
                if good_matches_count >= seuil:
                    bonus_master = valeur
                    break
            
            if bonus_master > 0:
                pts_flair += bonus_master

        # Sauvegarde du Flair (uniquement Gaps + Vainqueur + Master)
        ss = SeasonScore.objects.get(user=p.user, season=season_obj)
        ss.ranking_points = pts_flair
        ss.save()

# --- ÉTAPE 3 : LE PODIUM ---
    final_ranking = list(SeasonScore.objects.filter(season=season_obj))
    final_ranking.sort(key=lambda x: (x.match_points + x.ranking_points, x.match_points), reverse=True)

    print(f"DEBUG PODIUM : Nombre de scores trouvés = {len(final_ranking)}")

    bonus_keys = ["1st", "2nd", "3rd"]
    for i, b_key in enumerate(bonus_keys):
        if len(final_ranking) > i:
            pre_score = final_ranking[i]
            val_b = cfg.get(b_key, 0)
            
            print(f"DEBUG JOUER {i+1} : {pre_score.user.username} | Matchs: {pre_score.match_points} | Flair: {pre_score.ranking_points} | Bonus prévu ({b_key}): {val_b}")
            
            if val_b > 0:
                score_obj = SeasonScore.objects.get(id=pre_score.id)
                score_obj.podium_points = val_b
                score_obj.save()
                # On recharge pour vérifier l'écriture
                score_obj.refresh_from_db()
                print(f"✅ ÉCRITURE OK -> {score_obj.user.username} a maintenant {score_obj.podium_points} pts de podium. Total_points = {score_obj.total_points}")