from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from django.db.models import Sum

from core.models import Competition, Round, Match, Player, Prediction, DailyScore, Season


def _outcome(h: int, a: int) -> str:
    if h > a: return "H"
    if a > h: return "A"
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


def _comp_abbr(name: str) -> str:
    name_lower = name.lower()
    if "top" in name_lower:
        return "T14"
    if "champions" in name_lower or "europe" in name_lower:
        return "CC"
    if "challenge" in name_lower:
        return "CC"
    if "nation" in name_lower or "6" in name_lower:
        return "6N"
    if "pro d2" in name_lower:
        return "D2"
    return name[:4].upper()


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
    detailed_ranking: List[Dict]

    choppes_or: List[Dict]
    choppes_bois: List[Dict]

    chopes_cumulees: List[Dict]
    cuilleres_bois: List[Dict]

    demi_tout_pile_table: List[Dict] = field(default_factory=list)
    bonus_off_table: List[Dict] = field(default_factory=list)
    bonus_def_table: List[Dict] = field(default_factory=list)


def compute_statistics(competition: Optional[Competition], season: Optional[Season] = None, season_ids: Optional[list] = None) -> StatsResult:
    rounds_qs = Round.objects.select_related("season__competition").all()

    if season_ids:
        rounds_qs = rounds_qs.filter(season_id__in=season_ids)
    elif season is not None:
        rounds_qs = rounds_qs.filter(season=season)
    elif competition is not None:
        rounds_qs = rounds_qs.filter(season__competition=competition)

    rounds_qs = rounds_qs.order_by("date", "id")
    rounds = list(rounds_qs)

    round_ids = [r.id for r in rounds]

    has_multi_comp = len({r.season.competition_id for r in rounds}) > 1

    labels = []
    for r in rounds:
        if has_multi_comp:
            abbr = _comp_abbr(r.season.competition.name)
            if r.phase != Round.MatchPhase.POOL:
                labels.append(f"{abbr} {r.get_phase_display()}")
            else:
                labels.append(f"{abbr} J{r.number}")
        else:
            if r.phase != Round.MatchPhase.POOL:
                labels.append(r.get_phase_display())
            else:
                labels.append(f"J{r.number}")

    players = list(Player.objects.select_related("user").all().order_by("user__username"))
    player_keys = [p.user.username for p in players if p.user]

    all_daily_scores = DailyScore.objects.filter(round_id__in=round_ids).select_related("user")

    scores_map = {}
    for ds in all_daily_scores:
        rid = ds.round_id
        uname = ds.user.username
        if rid not in scores_map:
            scores_map[rid] = {}
        scores_map[rid][uname] = int(ds.points or 0)

    # Fallback : calculer les scores par round depuis les pronostics
    pred_points = (
        Prediction.objects.filter(match__round_id__in=round_ids)
        .values("match__round_id", "player__user__username")
        .annotate(total=Sum("points"))
    )
    pred_scores = {}
    for item in pred_points:
        rid = item["match__round_id"]
        uname = item["player__user__username"]
        pts = item["total"] or 0
        if rid not in pred_scores:
            pred_scores[rid] = {}
        pred_scores[rid][uname] = pred_scores[rid].get(uname, 0) + pts

    # Ne garder que les joueurs qui ont des données dans la période
    active_players = set()
    for rid_data in scores_map.values():
        active_players.update(rid_data.keys())
    for rid_data in pred_scores.values():
        active_players.update(rid_data.keys())
    player_keys = [k for k in player_keys if k in active_players]

    score_series = {k: [] for k in player_keys}
    rank_series  = {k: [] for k in player_keys}
    gap_series   = {k: [] for k in player_keys}
    cumulative   = {k: 0 for k in player_keys}

    chopes_points_by_player = {k: 0 for k in player_keys}
    cuilleres_by_player = {k: 0 for k in player_keys}

    for rid in round_ids:
        day_data = scores_map.get(rid, {})
        if not day_data:
            day_data = pred_scores.get(rid, {})

        for k in player_keys:
            pts_jour = day_data.get(k, 0)
            cumulative[k] += pts_jour
            score_series[k].append(cumulative[k])

        sorted_items = sorted(day_data.items(), key=lambda x: -x[1])
        rank = 0
        prev_pts = None
        player_rank = {}
        for idx, (k, pts) in enumerate(sorted_items):
            if pts != prev_pts:
                rank = idx + 1
                prev_pts = pts
            player_rank[k] = rank

        min_pts = min(day_data.values()) if day_data else 0
        max_pts = max(day_data.values()) if day_data else 0

        for k, pts in day_data.items():
            r = player_rank[k]
            if pts > 0:
                if r == 1:
                    chopes_points_by_player[k] += 3
                elif r == 2:
                    chopes_points_by_player[k] += 2
                elif r == 3:
                    chopes_points_by_player[k] += 1

            if pts > 0 and pts == min_pts and len(day_data) >= 3 and min_pts < max_pts:
                cuilleres_by_player[k] += 1

        ordered = sorted(cumulative.items(), key=lambda x: x[1], reverse=True)
        leader_points = ordered[0][1] if ordered else 0
        ranks = {name: idx + 1 for idx, (name, _) in enumerate(ordered)}

        for k in player_keys:
            rank_series[k].append(int(ranks.get(k, 1)))
            gap_series[k].append(int(leader_points - cumulative[k]))

    preds = Prediction.objects.select_related(
        "player__user", "match__round__season__competition"
    ).filter(match__round_id__in=round_ids)

    correct_outcomes = {k: 0 for k in player_keys}
    tout_pile_by_player = {k: 0 for k in player_keys}
    bois_by_player = {k: 0 for k in player_keys}

    demi_tout_pile_by_player = {k: 0 for k in player_keys}
    bon_bonus_off_by_player = {k: 0 for k in player_keys}
    mauvais_bonus_off_by_player = {k: 0 for k in player_keys}
    bon_bonus_def_by_player = {k: 0 for k in player_keys}
    mauvais_bonus_def_by_player = {k: 0 for k in player_keys}

    kpi = {
        "tout_pile": 0, "demi_tout_pile": 0, "demi_dom": 0, "demi_ext": 0,
        "bon_bonus_off": 0, "mauvais_bonus_off": 0,
        "bon_bonus_def": 0, "mauvais_bonus_def": 0,
    }

    for pr in preds:
        if not pr.player.user: continue
        key = pr.player.user.username
        m = pr.match

        threshold = m.round.season.competition.bonus_defense_threshold

        mh, ma = m.home_score, m.away_score
        ph, pa = pr.home_score_pred, pr.away_score_pred

        if mh is None or ma is None or ph is None or pa is None: continue

        if pr.bonus_home_pred:
            if m.bonus_offense_home:
                kpi["bon_bonus_off"] += 1
                bon_bonus_off_by_player[key] += 1
            else:
                kpi["mauvais_bonus_off"] += 1
                mauvais_bonus_off_by_player[key] += 1
        if pr.bonus_away_pred:
            if m.bonus_offense_away:
                kpi["bon_bonus_off"] += 1
                bon_bonus_off_by_player[key] += 1
            else:
                kpi["mauvais_bonus_off"] += 1
                mauvais_bonus_off_by_player[key] += 1

        real_bd = m.get_defense_bonus()
        pred_bd = None
        p_diff = abs(ph - pa)

        if p_diff <= threshold:
            if ph < pa: pred_bd = 'HOME'
            elif pa < ph: pred_bd = 'AWAY'
            else: pred_bd = 'DRAW'

        if pred_bd:
            if pred_bd == real_bd or (pred_bd == 'DRAW' and real_bd is not None):
                kpi["bon_bonus_def"] += 1
                bon_bonus_def_by_player[key] += 1
            else:
                kpi["mauvais_bonus_def"] += 1
                mauvais_bonus_def_by_player[key] += 1

        if _outcome(ph, pa) == _outcome(mh, ma):
            correct_outcomes[key] += 1
        else:
            bois_by_player[key] += 1

        if ph == mh and pa == ma:
            kpi["tout_pile"] += 1
            tout_pile_by_player[key] += 1
        elif ph == mh or pa == ma:
            kpi["demi_tout_pile"] += 1
            demi_tout_pile_by_player[key] += 1
            if ph == mh: kpi["demi_dom"] += 1
            if pa == ma: kpi["demi_ext"] += 1

    matches_count = Match.objects.filter(round_id__in=round_ids).count()
    pie_den = _denominator_for_pie(competition, matches_count)

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
        })

    def format_trophy(data_dict):
        sorted_data = sorted(data_dict.items(), key=lambda x: x[1], reverse=True)
        return [{"username": k, "value": v} for k, v in sorted_data]

    def format_bonus(data_dict_bon, data_dict_mauvais):
        combined = []
        for k in player_keys:
            reussi = data_dict_bon.get(k, 0)
            rate = data_dict_mauvais.get(k, 0)
            total = reussi + rate
            if total > 0:
                combined.append({
                    "username": k, "reussi": reussi, "rate": rate, "total": total,
                    "points": 15 * reussi - 3 * rate
                })
        combined.sort(key=lambda x: x["points"], reverse=True)
        return combined

    return StatsResult(
        labels=labels,
        score_series=score_series,
        rank_series=rank_series,
        gap_series=gap_series,
        pie_labels=[f"{i}/{pie_den}" for i in range(pie_den, -1, -1)],
        pie_values=[list(correct_outcomes.values()).count(i) for i in range(pie_den, -1, -1)],
        pie_denominator=pie_den,
        victory_table=sorted(
            [{
                "username": k, "bons": v,
                "total": v + bois_by_player.get(k, 0),
                "pourcentage": round(v / (v + bois_by_player.get(k, 0)) * 100, 1)
                    if (v + bois_by_player.get(k, 0)) > 0 else 0
            } for k, v in correct_outcomes.items()],
            key=lambda x: x["bons"], reverse=True
        ),
        kpi=kpi,
        detailed_ranking=detailed_ranking,
        choppes_or=format_trophy(tout_pile_by_player),
        choppes_bois=format_trophy(bois_by_player),
        chopes_cumulees=format_trophy(chopes_points_by_player),
        cuilleres_bois=format_trophy(cuilleres_by_player),
        demi_tout_pile_table=format_trophy(demi_tout_pile_by_player),
        bonus_off_table=format_bonus(bon_bonus_off_by_player, mauvais_bonus_off_by_player),
        bonus_def_table=format_bonus(bon_bonus_def_by_player, mauvais_bonus_def_by_player),
    )
