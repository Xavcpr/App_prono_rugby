from django.db import transaction
from core.models import CompetitionResult, CompetitionTeamPrediction, CompetitionBonusPrediction, SeasonScore, Prediction, DailyScore, Player 
from django.db.models import Sum, F
import core.services.scoring as scoring


# --- CONFIGURATION DU BARÈME (DEFAUT) ---
_DEFAULT_SCORING_CONFIG = {
    "SCORING_CONFIG": {
        "MATCH_POOL_BASE": 800,
        "PERFECT_SCORE_BONUS": 800,
        "HALF_PERFECT_BONUS": 40,
        "AWAY_WIN_BONUS": 15,
        "DRAW_BONUS": 100,
        "OFFENSIVE_BONUS_VALUE": 15,
        "DEFENSIVE_BONUS_VALUE": 20,
        "BONUS_MALUS": -3,
        "DIFF_TABLE": {0: 15, 1: 12, 2: 10, 3: 8, 4: 6, 5: 4, 6: 2, 7: 1},
        "SUM_TABLE": {0: 8, 1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1},
    },
    "PHASE_MULTIPLIERS": {
        "POOL": 1.0, "R16": 1.25, "QF": 1.5, "SF": 2.0, "FINAL": 3.0,
    },
    "BONUS_SCALES": {
        "Top 14": {7: 150, 6: 60, 5: 20},
        "Champions Cup": {12: 300, 11: 150, 10: 100, 9: 40},
    },
    "RUGBY_SCORING": {
        "Top 14": {"bonus": 200, "winner": 200, "exact_rank": 80, "gap_1": 40, "gap_2": 20, "all_class": 3000, "1st": 300, "2nd": 150, "3rd": 50},
        "Champions Cup": {"bonus": 0, "winner": 200, "exact_rank": 50, "gap_1": 20, "gap_2": 0, "all_class": 100, "1st": 150, "2nd": 75, "3rd": 25},
        "6 Nations": {"bonus": 0, "winner": 100, "exact_rank": 50, "gap_1": 0, "gap_2": 0, "all_class": 100, "1st": 50, "2nd": 25, "3rd": 10},
    },
    "SCORER_RANKS": {
        "Top 14": {"1": 300, "2": 150, "3": 50},
        "Champions Cup": {"1": 200, "2": 75, "3": 25},
        "6 Nations": {"1": 50, "2": 25, "3": 0},
    },
    "MASTER_PALIERS": {12: 50, 13: 150, 14: 200, 15: 250},
}

# Aliasing pour compatibilité avec les imports existants dans views.py
SCORING_CONFIG = _DEFAULT_SCORING_CONFIG["SCORING_CONFIG"]
PHASE_MULTIPLIERS = _DEFAULT_SCORING_CONFIG["PHASE_MULTIPLIERS"]
BONUS_SCALES = _DEFAULT_SCORING_CONFIG["BONUS_SCALES"]
RUGBY_SCORING = _DEFAULT_SCORING_CONFIG["RUGBY_SCORING"]
MASTER_PALIERS = _DEFAULT_SCORING_CONFIG["MASTER_PALIERS"]
# Echelle dégressive par défaut (saisons 2026/2027+) et ancienne échelle
SCORER_RANKS = _DEFAULT_SCORING_CONFIG["SCORER_RANKS"]
_OLD_SCORER_RANKS = {
    "Top 14": {"1": 200, "2": 0, "3": 0},
    "Champions Cup": {"1": 0, "2": 0, "3": 0},
    "6 Nations": {"1": 0, "2": 0, "3": 0},
}

# Ancien barème (saisons 2025-2026 et antérieures) : seule l'affichage de la page barème
# est concerné, les anciennes saisons gardent leur config gelée en base.
_OLD_BAREME_CONFIG = {
    "SCORING_CONFIG": {
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
    },
    "PHASE_MULTIPLIERS": PHASE_MULTIPLIERS,
    "BONUS_SCALES": BONUS_SCALES,
    "RUGBY_SCORING": RUGBY_SCORING,
    "MASTER_PALIERS": MASTER_PALIERS,
}


def _get_scoring_config(season):
    """Renvoie la config gelée d'une saison, ou la config par défaut si absente."""
    if season and season.scoring_config:
        return season.scoring_config
    return _DEFAULT_SCORING_CONFIG


def _store_scoring_config(season):
    """Stocke la config par défaut sur la saison si pas encore fait (gel)."""
    if season and season.scoring_config is None:
        season.scoring_config = _DEFAULT_SCORING_CONFIG
        season.save(update_fields=["scoring_config"])
# --- OUTILS DE CALCUL ---

def _parse_ranked_names(post_data, base_name):
    """Parse les inputs base_name_1..3 en {'1': [noms], '2': [noms], '3': [noms]}.
    Ex-aequo = plusieurs noms séparés par des virgules dans le même champ."""
    data = {}
    for rank in ("1", "2", "3"):
        raw = post_data.get(f"{base_name}_{rank}", "").strip()
        names = [n.strip() for n in raw.split(",") if n.strip()]
        data[rank] = names
    return data


def _competition_key(competition_name):
    """Clé canonique d'une compétition pour les tables de barème (insensible à la casse)."""
    n = competition_name.lower()
    if "6 nations" in n or "six nations" in n: return "6 Nations"
    if "top 14" in n or "top14" in n: return "Top 14"
    return "Champions Cup"


def _real_top3(result, json_field, old_field):
    """Retourne {'1': [noms], '2': [noms], '3': [noms]} pour une catégorie.
    Ex-aequo = plusieurs noms dans la même liste. Fallback sur l'ancien champ simple."""
    data = getattr(result, json_field, None) or {}
    if isinstance(data, dict) and any(data.values()):
        normalized = {}
        for rank in ("1", "2", "3"):
            v = data.get(rank)
            normalized[rank] = [v] if isinstance(v, str) and v.strip() else (list(v) if v else [])
        return normalized
    old_val = (getattr(result, old_field, "") or "").strip()
    return {"1": [old_val] if old_val else [], "2": [], "3": []}


def _is_new_bareme_season(season):
    """Vrai si la saison appartient au cycle 2026/2027 (nouveau barème)."""
    if season is None:
        return False
    from core.management.commands.backfill_player_seasons import get_season_key
    from core.models import Season as _Season
    try:
        year_key = int(get_season_key(season.year))
    except (TypeError, ValueError):
        return False
    years = [int(get_season_key(s.year))
             for s in _Season.objects.all()
             if get_season_key(s.year).isdigit()]
    return bool(years) and year_key == max(years)


def scorer_rank_points(season, rank):
    """Points du barème 'top marqueur/réalisateur' pour un rang donné (1, 2 ou 3).
    Les saisons du nouveau cycle utilisent l'échelle dégressive ; les saisons passées
    (gelées sous l'ancien barème) conservent le bonus plat Top 14=200, sinon 0."""
    if season is not None and season.scoring_config:
        table = season.scoring_config.get("SCORER_RANKS")
    else:
        table = None
    if not table:
        table = SCORER_RANKS if _is_new_bareme_season(season) else _OLD_SCORER_RANKS
    key = _competition_key(season.competition.name)
    return int(table.get(key, {}).get(str(rank), 0) or 0)


def bonus_marqueur_realisateur_points(season, bonus_pred, result):
    """Points bonus meilleur marqueur + meilleur réalisateur (dégressif, ex-aequo gérés).
    Le joueur ne gagne que le meilleur rang atteint pour chaque catégorie."""
    if bonus_pred is None or result is None:
        return 0
    total = 0
    categories = (
        ("real_best_try_scorer", "real_best_try_scorers", "best_try_scorer"),
        ("real_best_point_scorer", "real_best_point_scorers", "best_point_scorer"),
    )
    for old_field, json_field, pred_field in categories:
        pred_name = (getattr(bonus_pred, pred_field, "") or "").strip()
        if not pred_name:
            continue
        pred = pred_name.lower()
        top3 = _real_top3(result, json_field, old_field)
        for rank in ("1", "2", "3"):
            names = top3.get(rank, [])
            if any(pred == (n or "").strip().lower() for n in names):
                total += scorer_rank_points(season, rank)
                break
    return total

def get_winner_side(score_home, score_away):
    if score_home > score_away: return "HOME"
    if score_away > score_home: return "AWAY"
    return "DRAW"

def calculate_match_points(prediction, match, winners_count, scoring_config=None):
    cfg = (scoring_config or {}).get("SCORING_CONFIG", _DEFAULT_SCORING_CONFIG["SCORING_CONFIG"])
    pts = 0
    
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
    season = round_obj.season
    _store_scoring_config(season)
    cfg = _get_scoring_config(season)
    matches = round_obj.matches.all()
    players = Player.objects.all()
    comp_name = season.competition.name
    current_scale = cfg["BONUS_SCALES"].get(comp_name, {})

    # SÉCURITÉ : On s'assure que les matchs ont la même phase que la journée
    matches.filter(phase='POOL').update(phase=round_obj.phase)

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
                m_pts = calculate_match_points(pr, m, winners_cnt, cfg)
                
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
            multiplier = cfg["PHASE_MULTIPLIERS"].get(round_obj.phase, 1.0)
            
            if _competition_key(comp_name) == "6 Nations":
                multiplier *= 2.0

            final_daily_score = (total_points_matchs + day_bonus) * multiplier
            
            if p.user:
                ds, _ = DailyScore.objects.get_or_create(user=p.user, round=round_obj)
                ds.points = int(final_daily_score)
                ds.save()   

from django.db.models import Sum
from core.models import SeasonScore, CompetitionResult, CompetitionBonusPrediction, DailyScore, Player, CompetitionTeamPrediction

@transaction.atomic
def compute_season_ranking_points(season_obj, compute_podium=False):
    _store_scoring_config(season_obj)

    # Détection auto : si la saison n'a PAS de phase finale, le podium est calculé automatiquement
    playoff_phases = ['SF', 'FINAL', 'QF', 'R16']
    has_playoffs = season_obj.rounds.filter(phase__in=playoff_phases).exists()
    if not has_playoffs:
        compute_podium = True

    # --- ÉTAPE 0 : VÉRIFICATION ET DESTRUCTURATION DU JSON (POULES OU GLOBAL) ---
    res = CompetitionResult.objects.filter(season=season_obj).first()
    if not res:
        return "Erreur : Aucun résultat créé pour cette saison."
    
    has_winner = bool(res.real_winner)
    if not has_winner:
        print("⚠️ Pas de vainqueur renseigné — le bonus vainqueur ne sera pas attribué, mais les points Matchs + Flair + Podium seront calculés.")

    # Gestion intelligente du JSON : on s'adapte si c'est découpé en "pool1", "pool2" ou "all"
    json_data = res.rankings_json or {}
    real_rankings = {}
    
    if 'all' in json_data:
        # Format classique (ex: Top 14 / 6 Nations)
        for key, pos in json_data.get('all', {}).items():
            real_rankings[str(key)] = pos
    else:
        # Format par poules (ex: Champions Cup avec {"pool1": {"21": 1, "2": 2...}})
        for pool_key, pool_teams in json_data.items():
            if isinstance(pool_teams, dict):
                for team_id_str, position in pool_teams.items():
                    real_rankings[str(team_id_str)] = position

    # Vérification souple basée sur les IDs ou les noms pour ne pas bloquer l'exécution
    expected_teams = season_obj.teams.all() 
    missing_teams = [t.name for t in expected_teams if str(t.id) not in real_rankings and t.name not in real_rankings]
    if missing_teams:
        print(f"⚠️ Note : {len(missing_teams)} équipes absentes du JSON de classement (ignorées pour le Flair).")


    # --- ÉTAPE 1 : SYNCHRONISATION DES POINTS DE MATCHS & RESET TOTAL ---
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
        ss.ranking_points = 0  # Reset propre du Flair
        ss.podium_points = 0   # Reset propre du Podium (Nouveau champ)
        ss.save()


    # --- ÉTAPE 2 : CALCUL DU FLAIR (Rangs + Gaps + Vainqueur + Master) ---
    comp_name = season_obj.competition.name
    clean_key = _competition_key(comp_name)
    s_cfg = _get_scoring_config(season_obj)
    cfg = s_cfg["RUGBY_SCORING"].get(clean_key, {})
    paliers = s_cfg.get("MASTER_PALIERS", {12: 50, 13: 150, 14: 200, 15: 250})

    for p in players:
        pts_flair = 0
        all_correct = True
        
        # A. Rangs et Gaps
        preds = CompetitionTeamPrediction.objects.filter(player=p, season=season_obj)
        for pr in preds:
            # On cherche d'abord par ID (format Champions Cup) puis par Nom (format historique)
            real_pos = real_rankings.get(str(pr.team.id)) or real_rankings.get(pr.team.name)
            
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

        # C. Bonus Vainqueur Final (uniquement si le vainqueur est connu)
        bonus_pred = CompetitionBonusPrediction.objects.filter(player=p, season=season_obj).first()
        if has_winner and bonus_pred and bonus_pred.winner == res.real_winner:
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
            for seuil, valeur in sorted(paliers.items(), reverse=True):
                if good_matches_count >= seuil:
                    bonus_master = valeur
                    break
            
            if bonus_master > 0:
                pts_flair += bonus_master

        # Sauvegarde du Flair calculé en base
        ss = SeasonScore.objects.get(user=p.user, season=season_obj)
        ss.ranking_points = pts_flair
        ss.save()


    # --- ÉTAPE 3 : LE PODIUM (optionnel, réservé à la fin de la compétition) ---
    if compute_podium:
        final_ranking = list(SeasonScore.objects.filter(season=season_obj))
        final_ranking.sort(key=lambda x: (x.match_points + x.ranking_points, x.match_points), reverse=True)

        bonus_keys = ["1st", "2nd", "3rd"]
        for i, b_key in enumerate(bonus_keys):
            if len(final_ranking) > i:
                pre_score = final_ranking[i]
                val_b = cfg.get(b_key, 0)
                if val_b > 0:
                    score_obj = SeasonScore.objects.get(id=pre_score.id)
                    score_obj.podium_points = val_b
                    score_obj.save()

    return "Calcul terminé (Matchs + Flair)" if not compute_podium else "Calcul terminé (Matchs + Flair + Podium)"
def compute_competition_points(season):
    from core.models import CompetitionResult, CompetitionTeamPrediction, CompetitionBonusPrediction, SeasonScore, Player
    result = CompetitionResult.objects.filter(season=season).first()
    if not result:
        return "Aucun r�sultat saisi."

    s_cfg = _get_scoring_config(season)
    rules = s_cfg["RUGBY_SCORING"].get(_competition_key(season.competition.name), s_cfg["RUGBY_SCORING"]["Top 14"])
    players = Player.objects.all()

    for player in players:
        pts_classement = 0
        pts_bonus_finaux = 0

        user_preds = CompetitionTeamPrediction.objects.filter(
            player=player,
            competition=season.competition,
            season=season
        )
        for p in user_preds:
            real_block = result.rankings_json.get(p.block_key, {})
            real_pos = real_block.get(str(p.team.id))
            if real_pos:
                diff = abs(p.position - int(real_pos))
                if diff == 0: pts_classement += rules["exact_rank"]
                elif diff == 1: pts_classement += rules["gap_1"]
                elif diff == 2: pts_classement += rules["gap_2"]

        bonus_pred = CompetitionBonusPrediction.objects.filter(
            player=player,
            competition=season.competition,
season=season
        ).first()

        if bonus_pred and result.real_winner:
            if bonus_pred.winner == result.real_winner:
                pts_bonus_finaux += rules["winner"]

        pts_bonus_finaux += bonus_marqueur_realisateur_points(season, bonus_pred, result)

        if player.user:
            s_score, _ = SeasonScore.objects.get_or_create(
                user=player.user,
                competition=season.competition,
                season=season
            )
            s_score.ranking_points = pts_classement + pts_bonus_finaux
            s_score.save()
