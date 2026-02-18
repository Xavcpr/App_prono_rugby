from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional

from django.db.models import Sum
from django.contrib.auth import get_user_model

from core.models import Competition, Round, Match, Player, Prediction, DailyScore

# =========================
# Mapping champs à adapter
# =========================
MATCH_HOME_SCORE_FIELD = "home_score"
MATCH_AWAY_SCORE_FIELD = "away_score"

PRED_HOME_SCORE_FIELD  = "home_score_pred"
PRED_AWAY_SCORE_FIELD  = "away_score_pred"

# bonus (si vous en avez)
MATCH_BONUS_OFF_FIELD = None   # ex: "bonus_off"
MATCH_BONUS_DEF_FIELD = None   # ex: "bonus_def"
PRED_BONUS_OFF_FIELD  = None   # ex: "bonus_off_pred"
PRED_BONUS_DEF_FIELD  = None   # ex: "bonus_def_pred"

PRED_POINTS_FIELD = "points"


def _get(obj, field, default=None):
    if not field:
        return default
    return getattr(obj, field, default)


def _outcome(h: int, a: int) -> str:
    if h > a:
        return "H"
    if a > h:
        return "A"
    return "D"


def _denominator_for_pie(competition: Optional[Competition], matches_count: int) -> int:
    if competition is None:
        return matches_count
    code = (getattr(competition, "code", "") or getattr(competition, "name", "") or "").lower()
    if "top14" in code or "top 14" in code:
        return 7
    if "champ" in code or "ercc" in code or "europe" in code:
        return 12
    if "nation" in code or "6" in code:
        return 15
    return matches_count


@dataclass
class StatsResult:
    labels: List[str]
    score_series: Dict[str, List[int]]
    rank_series: Dict[str, List[int]]
    gap_series: Dict[str, List[int]]

    pie_labels: List[str]
    pie_values: List[int]
    pie_denominator: int

    victory_table: List[Dict]
    kpi: Dict[str, int]

    # ✅ nouveau : tableau “classement détaillé”
    detailed_ranking: List[Dict]

    # ✅ nouveau : choppes
    choppes_or: List[Dict]
    choppes_bois: List[Dict]


def compute_statistics(competition: Optional[Competition]) -> StatsResult:
    # 1. ---- Définition du périmètre des Rounds ----
    rounds_qs = Round.objects.all()
    if competition is not None:
        try:
            rounds_qs = rounds_qs.filter(season__competition=competition)
        except Exception:
            pass

    # Tri pour la chronologie des graphiques
    if hasattr(Round, "date"):
        rounds_qs = rounds_qs.order_by("date")
    elif hasattr(Round, "number"):
        rounds_qs = rounds_qs.order_by("number")
    else:
        rounds_qs = rounds_qs.order_by("id")

    rounds = list(rounds_qs)
    labels = [getattr(r, "name", f"J{r.id}") for r in rounds]
    round_ids = [r.id for r in rounds]

    # 2. ---- Chargement des Joueurs ----
    players = list(Player.objects.select_related("user").all().order_by("user__username"))
    # On ne garde que les joueurs ayant un utilisateur lié
    player_keys = [p.user.username for p in players if p.user]

    # 3. ---- Récupération des scores (Source Unique de Vérité) ----
    # On récupère tous les scores enregistrés pour ces rounds en une seule requête
    all_daily_scores = DailyScore.objects.filter(round_id__in=round_ids).select_related("user")
    
    # On crée une map pour un accès rapide : { round_id: { username: points } }
    scores_map = {}
    for ds in all_daily_scores:
        rid = ds.round_id
        uname = ds.user.username
        if rid not in scores_map:
            scores_map[rid] = {}
        scores_map[rid][uname] = int(ds.points or 0)

    # 4. ---- Construction des Séries Temporelles ----
    score_series = {k: [] for k in player_keys}
    rank_series  = {k: [] for k in player_keys}
    gap_series   = {k: [] for k in player_keys}
    cumulative   = {k: 0 for k in player_keys}

    for rid in round_ids:
        day_data = scores_map.get(rid, {})
        for k in player_keys:
            pts_jour = day_data.get(k, 0)
            cumulative[k] += pts_jour
            score_series[k].append(cumulative[k])

        # Calcul du classement et de l'écart au leader à l'instant T
        ordered = sorted(cumulative.items(), key=lambda x: x[1], reverse=True)
        leader_points = ordered[0][1] if ordered else 0
        ranks = {name: idx + 1 for idx, (name, _) in enumerate(ordered)}

        for k in player_keys:
            rank_series[k].append(int(ranks.get(k, 1)))
            gap_series[k].append(int(leader_points - cumulative[k]))

    # 5. ---- Analyse des Prédictions (KPIs & Choppes) ----
    # Ici on utilise les Predictions uniquement pour les stats de "type" de prono
    preds = Prediction.objects.select_related("player__user", "match").filter(match__round_id__in=round_ids)
    
    correct_outcomes = {k: 0 for k in player_keys}
    tout_pile_by_player = {k: 0 for k in player_keys}
    bois_by_player = {k: 0 for k in player_keys}
    
    kpi = {
        "tout_pile": 0, "demi_tout_pile": 0, "demi_dom": 0, "demi_ext": 0,
        "bon_bonus_off": 0, "mauvais_bonus_off": 0, "bon_bonus_def": 0, "mauvais_bonus_def": 0,
    }

    for pr in preds:
        if not pr.player.user: continue
        key = pr.player.user.username
        m = pr.match
        
        mh, ma = m.home_score, m.away_score
        ph, pa = pr.home_score_pred, pr.away_score_pred
        
        if mh is None or ma is None or ph is None or pa is None:
            continue

        # Victoires (Issues)
        if _outcome(ph, pa) == _outcome(mh, ma):
            correct_outcomes[key] += 1
        else:
            bois_by_player[key] += 1

        # Tout-pile
        if ph == mh and pa == ma:
            kpi["tout_pile"] += 1
            tout_pile_by_player[key] += 1
        elif ph == mh or pa == ma:
            kpi["demi_tout_pile"] += 1
            if ph == mh: kpi["demi_dom"] += 1
            if pa == ma: kpi["demi_ext"] += 1

    # 6. ---- Finalisation des Tableaux ----
    # Dénominateur pour le camembert
    matches_count = Match.objects.filter(round_id__in=round_ids).count()
    pie_den = _denominator_for_pie(competition, matches_count)

    # Classement détaillé
    detailed_ranking = []
    totals = sorted(cumulative.items(), key=lambda x: x[1], reverse=True)
    max_pts = totals[0][1] if totals else 0
    
    for idx, (uname, pts) in enumerate(totals, start=1):
        detailed_ranking.append({
            "rank": idx,
            "username": uname,
            "points": pts,
            "gap": max_pts - pts,
            "bons_victoires": correct_outcomes.get(uname, 0),
            "tout_pile": tout_pile_by_player.get(uname, 0),
            "bois": bois_by_player.get(uname, 0),
        })

    # Choppes
    def format_choppe(data_dict, reverse=True):
        sorted_data = sorted(data_dict.items(), key=lambda x: x[1], reverse=reverse)
        return [{"rank": i, "username": k, "value": v} for i, (k, v) in enumerate(sorted_data, 1)]

    return StatsResult(
        labels=labels,
        score_series=score_series,
        rank_series=rank_series,
        gap_series=gap_series,
        pie_labels=[f"{i}/{pie_den}" for i in range(pie_den, -1, -1)],
        pie_values=[list(correct_outcomes.values()).count(i) for i in range(pie_den, -1, -1)],
        pie_denominator=pie_den,
        victory_table=sorted([{"username": k, "bons": v} for k, v in correct_outcomes.items()], key=lambda x: x["bons"], reverse=True),
        kpi=kpi,
        detailed_ranking=detailed_ranking,
        choppes_or=format_choppe(tout_pile_by_player),
        choppes_bois=format_choppe(bois_by_player)
    )