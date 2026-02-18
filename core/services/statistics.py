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
    # ---- Rounds scope (toutes les journées de la compète, ou toutes)
    rounds_qs = Round.objects.all()
    if competition is not None:
        # adapte si nécessaire
        try:
            rounds_qs = rounds_qs.filter(season__competition=competition)
        except Exception:
            pass

    if hasattr(Round, "date"):
        rounds_qs = rounds_qs.order_by("date")
    elif hasattr(Round, "number"):
        rounds_qs = rounds_qs.order_by("number")
    else:
        rounds_qs = rounds_qs.order_by("id")

    rounds = list(rounds_qs)
    labels = [getattr(r, "name", f"J{r.id}") for r in rounds]
    round_ids = [r.id for r in rounds]

    # ---- Players
    players = list(Player.objects.select_related("user").all().order_by("user__username"))
    player_keys = [getattr(p.user, "username", str(p.id)) for p in players]

    # ---- Matches count for pie denominator
    matches_qs = Match.objects.all()
    if competition is not None:
        try:
            matches_qs = matches_qs.filter(round__season__competition=competition)
        except Exception:
            pass
    matches_count = matches_qs.count()
    pie_den = _denominator_for_pie(competition, matches_count)

    # ---- Points source
    use_daily_score = DailyScore.objects.exists()

    def points_for_round(rid: int) -> Dict[str, int]:
        # 1. On cherche d'abord dans DailyScore pour ce round précis
        ds = DailyScore.objects.filter(round_id=rid).select_related("user")
        
        if ds.exists():
            # Si on a des scores enregistrés pour cette journée, on les prend
            return {getattr(x.user, "username", str(x.user.id)): int(x.points or 0) for x in ds}
        
        # 2. S'il n'y a pas de DailyScore (ex: journée pas encore terminée ou recalculée), 
        # on fait la somme des points des prédictions
        pr = Prediction.objects.filter(match__round_id=rid).select_related("player__user")
        agg = pr.values("player__user__username").annotate(pts=Sum("points"))
        
        return {a["player__user__username"]: int(a["pts"] or 0) for a in agg}

    # ---- Series
    score_series = {k: [] for k in player_keys}
    rank_series  = {k: [] for k in player_keys}
    gap_series   = {k: [] for k in player_keys}
    cumulative   = {k: 0 for k in player_keys}

    for rid in round_ids:
        per = points_for_round(rid)
        for k in player_keys:
            cumulative[k] += per.get(k, 0)
            score_series[k].append(cumulative[k])

        ordered = sorted(cumulative.items(), key=lambda x: x[1], reverse=True)
        leader_points = ordered[0][1] if ordered else 0
        ranks = {name: idx + 1 for idx, (name, _) in enumerate(ordered)}

        for k in player_keys:
            rank_series[k].append(int(ranks.get(k, 0) or 0))
            gap_series[k].append(int(leader_points - cumulative[k]))

    # ---- Predictions scope for victory stats / KPIs / choppes
    preds = Prediction.objects.select_related("player__user", "match").all()
    if competition is not None:
        try:
            preds = preds.filter(match__round__season__competition=competition)
        except Exception:
            pass

    correct_outcomes = {k: 0 for k in player_keys}

    # KPIs “globaux” (sur la période filtrée)
    kpi = {
        "tout_pile": 0,
        "demi_tout_pile": 0,
        "demi_dom": 0,
        "demi_ext": 0,
        "bon_bonus_off": 0,
        "mauvais_bonus_off": 0,
        "bon_bonus_def": 0,
        "mauvais_bonus_def": 0,
    }

    # Choppes : on calcule par joueur
    tout_pile_by_player = {k: 0 for k in player_keys}
    bois_by_player = {k: 0 for k in player_keys}  # définition : “mauvais résultat” (= issue fausse)

    for pr in preds:
        m = pr.match
        key = getattr(pr.player.user, "username", str(pr.player.id))

        mh = _get(m, MATCH_HOME_SCORE_FIELD)
        ma = _get(m, MATCH_AWAY_SCORE_FIELD)
        ph = _get(pr, PRED_HOME_SCORE_FIELD)
        pa = _get(pr, PRED_AWAY_SCORE_FIELD)
        if mh is None or ma is None or ph is None or pa is None:
            continue

        mh, ma, ph, pa = int(mh), int(ma), int(ph), int(pa)

        # bons pronos victoire (issue)
        if _outcome(ph, pa) == _outcome(mh, ma):
            correct_outcomes[key] += 1
        else:
            bois_by_player[key] += 1

        # tout-pile / demi
        if ph == mh and pa == ma:
            kpi["tout_pile"] += 1
            tout_pile_by_player[key] += 1
        elif ph == mh or pa == ma:
            kpi["demi_tout_pile"] += 1
            if ph == mh:
                kpi["demi_dom"] += 1
            if pa == ma:
                kpi["demi_ext"] += 1

        # bonus (si champs présents)
        mbo = _get(m, MATCH_BONUS_OFF_FIELD, None)
        mbd = _get(m, MATCH_BONUS_DEF_FIELD, None)
        pbo = _get(pr, PRED_BONUS_OFF_FIELD, None)
        pbd = _get(pr, PRED_BONUS_DEF_FIELD, None)

        if mbo is not None and pbo is not None:
            if pbo == mbo:
                kpi["bon_bonus_off"] += 1
            else:
                kpi["mauvais_bonus_off"] += 1

        if mbd is not None and pbd is not None:
            if pbd == mbd:
                kpi["bon_bonus_def"] += 1
            else:
                kpi["mauvais_bonus_def"] += 1

    # ---- Pie distribution X/den
    pie_labels = [f"{i}/{pie_den}" for i in range(pie_den, -1, -1)]
    pie_counts = {lab: 0 for lab in pie_labels}
    for k, nb in correct_outcomes.items():
        nb = max(0, min(pie_den, int(nb)))
        pie_counts[f"{nb}/{pie_den}"] += 1
    pie_values = [pie_counts[lab] for lab in pie_labels]

    # ---- Table victory
    victory_table = sorted(
        [{"username": k, "bons": int(correct_outcomes.get(k, 0))} for k in player_keys],
        key=lambda x: x["bons"],
        reverse=True,
    )

    # ---- “Classement détaillé” (proche de résultats)
    # On prend le total points (dernier point de la série)
    totals = []
    for k in player_keys:
        total_pts = score_series[k][-1] if score_series[k] else 0
        totals.append((k, total_pts))
    totals.sort(key=lambda x: x[1], reverse=True)

    leader_pts = totals[0][1] if totals else 0
    detailed_ranking = []
    for idx, (k, pts) in enumerate(totals, start=1):
        detailed_ranking.append({
            "rank": idx,
            "username": k,
            "points": int(pts),
            "gap": int(leader_pts - pts),
            "bons_victoires": int(correct_outcomes.get(k, 0)),
            "tout_pile": int(tout_pile_by_player.get(k, 0)),
            "bois": int(bois_by_player.get(k, 0)),
        })

    # ---- Choppes d’or (desc) = nombre de tout-pile
    choppes_or = sorted(
        [{"rank": None, "username": k, "value": int(v)} for k, v in tout_pile_by_player.items()],
        key=lambda x: x["value"],
        reverse=True,
    )
    for i, row in enumerate(choppes_or, start=1):
        row["rank"] = i

    # ---- Choppes de bois (desc) = nombre d’issues fausses (ou autre “mauvais”)
    choppes_bois = sorted(
        [{"rank": None, "username": k, "value": int(v)} for k, v in bois_by_player.items()],
        key=lambda x: x["value"],
        reverse=True,
    )
    for i, row in enumerate(choppes_bois, start=1):
        row["rank"] = i

    return StatsResult(
        labels=labels,
        score_series=score_series,
        rank_series=rank_series,
        gap_series=gap_series,
        pie_labels=pie_labels,
        pie_values=pie_values,
        pie_denominator=pie_den,
        victory_table=victory_table,
        kpi=kpi,
        detailed_ranking=detailed_ranking,
        choppes_or=choppes_or,
        choppes_bois=choppes_bois,
    )
