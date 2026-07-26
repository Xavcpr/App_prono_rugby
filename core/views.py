import os, logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout, update_session_auth_hash
from django.contrib import messages
from django.utils import timezone
from django.db.models import Prefetch, Sum, Count, Q, Min, Max
from .forms import SettingsForm
from django.contrib.admin.views.decorators import staff_member_required
from datetime import datetime, timedelta
from django.contrib.auth.models import User

# ModÃ¨les conservÃ©s
from .models import (
    Competition, Season, Round, Match, Player, 
    Prediction, DailyScore, SeasonScore, CompetitionResult,
    CompetitionTeam, CompetitionTeamPrediction, CompetitionBonusPrediction, SeasonHistory
)

# Services
from .services import scoring
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse, HttpResponseRedirect
from .services.scoring import PHASE_MULTIPLIERS, SCORING_CONFIG, RUGBY_SCORING, process_round_scores, get_winner_side, BONUS_SCALES, compute_competition_points
from .services.statistics import compute_statistics

# CONFIGURATION DU BAREME DES POINTS


def health_view(request):
    return HttpResponse("ok", content_type="text/plain")


def _get_adjacent_rounds(rounds_qs, current_round_id):
    if not current_round_id:
        return (None, None)
    try:
        current_id = int(current_round_id)
    except (ValueError, TypeError):
        return (None, None)
    rounds_list = list(rounds_qs)
    for i, r in enumerate(rounds_list):
        if r.id == current_id:
            prev_id = rounds_list[i-1].id if i > 0 else None
            next_id = rounds_list[i+1].id if i < len(rounds_list) - 1 else None
            return (prev_id, next_id)
    return (None, None)


def _find_next_round(rounds_qs, now):
    """Return the first round with upcoming (kickoff_at >= now) or undated matches.
       Falls back to the last round if all matches are in the past."""
    for r in rounds_qs:
        if r.matches.filter(kickoff_at__gte=now).exists() or r.matches.filter(kickoff_at__isnull=True).exists():
            return r
    return rounds_qs.last()


def _players_for_season(season):
    """Retourne les joueurs associés à une saison, ou les joueurs sans aucunes saison (nouveaux)."""
    q = Q(sc=0)
    if season is not None:
        q |= Q(seasons=season)
    return Player.objects.annotate(sc=Count('seasons')).filter(q).distinct().order_by('name')


def _latest_season(seasons_qs):
    """Retourne la saison la plus récente d'un queryset, basé sur la clé année (ex: 2026 pour 2026/2027)."""
    from .management.commands.backfill_player_seasons import get_season_key
    seasons = list(seasons_qs)
    valid = [(s, get_season_key(s.year)) for s in seasons if get_season_key(s.year).isdigit()]
    if not valid:
        return seasons_qs.first()
    max_key = max(int(k) for _, k in valid)
    return next((s for s, k in valid if int(k) == max_key), seasons_qs.first())


# ------------------
# PRONOS VIEW
# ------------------
@login_required
def pronos_view(request):
    user = request.user
    try:
        player = user.player
    except Player.DoesNotExist:
        messages.error(request, "Votre compte nâ€™est pas encore liÃ© Ã  un joueur.")
        return redirect("logout")

    # 1. RÃ‰CUPÃ‰RATION DES PARAMÃˆTRES
    competition_id = request.GET.get("competition")
    season_id = request.GET.get("season")
    round_id = request.GET.get("round")
    now = timezone.now()

    # 2. LOGIQUE DES MENUS DÃ‰ROULANTS
    competitions = Competition.objects.all().order_by('name')
    
    # Choix de la compÃ©tition
    if competition_id:
        selected_comp = competitions.filter(id=competition_id).first()
    else:
        # CompÃ©tition du prochain match Ã  venir (toute compÃ©tition confondue)
        next_match = Match.objects.filter(kickoff_at__gte=now).order_by('kickoff_at').first()
        if next_match:
            selected_comp = next_match.round.season.competition
        else:
            selected_comp = competitions.first()

    # Choix de la saison
    seasons = Season.objects.filter(competition=selected_comp,year__gte=2025).order_by('-year')
    if season_id:
        selected_season = seasons.filter(id=season_id).first()
    else:
        selected_season = _latest_season(seasons)

    # Choix du round
    rounds = Round.objects.filter(season=selected_season).order_by('number')
    if not round_id:
        current_r_obj = _find_next_round(rounds, now)
        round_id = str(current_r_obj.id) if current_r_obj else None
    else:
        current_r_obj = rounds.filter(id=round_id).first()

    # 3. GESTION DU POST (SAUVEGARDE)
    # On garde ta logique de sauvegarde trÃ¨s robuste, elle est parfaite.
    if request.method == "POST":
        matches_to_save = Match.objects.filter(round_id=round_id)
        for match in matches_to_save:
            if match.is_locked: continue
            
            h_score_raw = request.POST.get(f"home_score_{match.id}", "").strip()
            a_score_raw = request.POST.get(f"away_score_{match.id}", "").strip()

            if h_score_raw and a_score_raw:
                try:
                    Prediction.objects.update_or_create(
                        match=match, player=player,
                        defaults={
                            'home_score_pred': int(h_score_raw),
                            'away_score_pred': int(a_score_raw),
                            'bonus_home_pred': f"bonus_home_{match.id}" in request.POST,
                            'bonus_away_pred': f"bonus_away_{match.id}" in request.POST,
                        }
                    )
                except ValueError: continue

        messages.success(request, "Pronostics enregistrÃ©s !")
        return redirect(f"{request.path}?competition={selected_comp.id}&season={selected_season.id}&round={round_id}")

    # 4. PRÃ‰PARATION AFFICHAGE
    matches = Match.objects.filter(round_id=round_id).select_related("home_team", "away_team", "round").order_by("kickoff_at")
    predictions_by_match = {p.match_id: p for p in Prediction.objects.filter(player=player, match__round_id=round_id)}

    submit_disabled = True
    for match in matches:
        match.user_prediction = predictions_by_match.get(match.id)
        if not match.is_locked: submit_disabled = False

    prev_round_id, next_round_id = _get_adjacent_rounds(rounds, round_id)

    return render(request, "pronos/pronos.html", {
        "player": player,
        "matches": matches,
        "competitions": competitions,
        "seasons": seasons,
        "rounds": rounds,
        "selected_competition": selected_comp,
        "selected_season": selected_season,
        "selected_round": round_id,
        "submit_disabled": submit_disabled,
        "prev_round_id": prev_round_id,
        "next_round_id": next_round_id,
    })

# ------------------
# LOGOUT VIEW
# ------------------
@login_required
def logout_view(request):
    auth_logout(request)
    return redirect("login")

# ------------------
# SETTINGS VIEW
# ------------------
@login_required
def settings_view(request):
    user = request.user
    if request.method == 'POST':
        form = SettingsForm(user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'ParamÃ¨tres mis Ã  jour !')
            return redirect('settings')
        else:
            messages.error(request, 'Corrigez les erreurs ci-dessous.')
    else:
        form = SettingsForm(user)

    return render(request, 'settings.html', {'form': form})

# ------------------
# COMPETITION RANKING VIEW
# ------------------
@login_required
def competition_ranking_view(request):
    competitions = Competition.objects.all()
    selected_competition_id = request.GET.get("competition")
    
    selected_competition = None
    selected_season = None
    rankings = []

    if selected_competition_id:
        selected_competition = get_object_or_404(Competition, id=selected_competition_id)
        
        # On rÃ©cupÃ¨re la saison la plus rÃ©cente pour cette compÃ©tition
        selected_season = Season.objects.filter(competition=selected_competition, year__gte=2025).order_by('-year').first()
        
        if selected_season:
            # On rÃ©cupÃ¨re les pronos de classement liÃ©s au joueur ET Ã  la saison
            rankings = CompetitionTeamPrediction.objects.filter(
                player__user=request.user, # On filtre par l'utilisateur connectÃ©
                competition=selected_competition,
                season=selected_season
            ).order_by("position")

    return render(request, "pronos/classement.html", {
        "competitions": competitions,
        "selected_competition": selected_competition,
        "selected_season": selected_season,
        "rankings": rankings,
    })



# ------------------
# CLASSEMENT_PREDICTION VIEW
# ------------------
@login_required
def classement_prediction(request):
    try:
        return _classement_prediction(request)
    except Exception:
        logging.getLogger(__name__).exception("Fatal error in classement_prediction")
        competitions = Competition.objects.all()
        messages.error(request, "Une erreur est survenue lors du chargement de la page.")
        return render(request, "pronos/classement.html", {
            "competitions": competitions,
            "selected_competition": None,
            "season": None,
            "seasons": [],
            "blocks": [],
            "bonus": None,
            "winner_teams": [],
            "last_saved_ranking": [],
        })


def _classement_prediction(request):
    competitions = Competition.objects.all()
    # On unifie la rÃ©cupÃ©ration de l'ID de compÃ©tition (POST ou GET)
    competition_id = request.POST.get("competition_id") or request.GET.get("competition")
    season_id = request.POST.get("season_id") or request.GET.get("season")

    selected_competition = None
    blocks = []
    bonus = None
    winner_teams = []
    season = None
    seasons = []

    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
        seasons = Season.objects.filter(competition=selected_competition, year__gte=2025).order_by("-year")
        season = seasons.filter(id=season_id).first() if season_id else seasons.first()
        
        # RÃ©cupÃ©ration des bonus
        bonus, _ = CompetitionBonusPrediction.objects.get_or_create(
            player=request.user.player,
            competition=selected_competition,
            season=season
        )
        
        try:
            winner_teams = (season.teams.all() if season else selected_competition.teams.all()).order_by("name")
        except Exception:
            winner_teams = Team.objects.none()

        # --- On prÃ©pare les BLOCKS ici pour qu'ils existent en GET ET en POST ---
        if selected_competition.name.lower() == "champions cup":
            try:
                has_pool_data = CompetitionTeam.objects.filter(
                    competition=selected_competition, season=season
                ).exists()
                if has_pool_data:
                    for pool in range(1, 5):
                        comp_teams = CompetitionTeam.objects.filter(
                            competition=selected_competition, season=season, pool=pool
                        ).select_related("team")
                        pool_teams = [ct.team for ct in comp_teams]
                        blocks.append({
                            "key": f"pool{pool}",
                            "teams": pool_teams,
                            "positions": list(range(1, 7)),
                            "pool": pool
                        })
                else:
                    CC_POOLS_2627 = [
                        {"pool": 1, "teams": ["Leinster","Glasgow","Pau","Sale Sharks","Leicester Tigers","Clermont"]},
                        {"pool": 2, "teams": ["Toulouse","Lions","Saracens","La Rochelle","Exeter Chiefs","Connacht"]},
                        {"pool": 3, "teams": ["UBB","Stormers","Racing 92","Munster","Bristol Bears","Gloucester"]},
                        {"pool": 4, "teams": ["Northampton Saints","Bath Rugby","Cardiff","Montpellier","Stade franÃ§ais","Bulls"]},
                    ]
                    teams_map = {t.name: t for t in Team.objects.all()}
                    for pool_data in CC_POOLS_2627:
                        pool_teams = []
                        for name in pool_data["teams"]:
                            t = teams_map.get(name)
                            if not t:
                                for db_name, db_t in teams_map.items():
                                    if name.lower() in db_name.lower() or db_name.lower() in name.lower():
                                        t = db_t
                                        break
                            if not t:
                                # Auto-create missing teams (ex: Lions, Exeter Chiefs, etc.)
                                t = Team.objects.create(name=name)
                                teams_map[name] = t
                                if season:
                                    t.seasons.add(season)
                            pool_teams.append(t)
                        pool_teams.sort(key=lambda x: x.name)
                        blocks.append({
                            "key": f"pool{pool_data['pool']}",
                            "teams": pool_teams,
                            "positions": list(range(1, 7)),
                            "pool": pool_data["pool"],
                        })
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("CC pools error")
                # Fallback ultime : un seul bloc avec toutes les Ã©quipes
                all_teams_list = list(Team.objects.all())
                blocks.append({
                    "key": "all",
                    "teams": all_teams_list,
                    "positions": list(range(1, len(all_teams_list) + 1)),
                    "pool": None,
                })
        else:
            teams = (season.teams.all() if season else selected_competition.teams.all()).order_by("name")
            blocks.append({
                "key": "all",
                "teams": teams,
                "positions": list(range(1, teams.count() + 1)),
                "pool": None
            })

    # --- SAUVEGARDE (POST) ---
    if request.method == "POST" and selected_competition:
        
        # VERROU : On vÃ©rifie si la compÃ©tition a commencÃ©
        if season and season.has_started:
            messages.error(request, "La compÃ©tition a dÃ©jÃ  commencÃ© ! Modification impossible.")
            return redirect(f"{request.path}?competition={selected_competition.id}&season={season.id}")
        
        # 1. Sauvegarde des Bonus
        bonus.best_try_scorer = request.POST.get("best_try_scorer", "").strip()
        bonus.best_point_scorer = request.POST.get("best_point_scorer", "").strip()
        winner_id = request.POST.get("winner")
        bonus.winner_id = int(winner_id) if winner_id and winner_id.isdigit() else None
        bonus.save()

        # 2. Nettoyage et 3. Enregistrement
        CompetitionTeamPrediction.objects.filter(
            competition=selected_competition, player=request.user.player, season=season
        ).delete()

        recorded_teams = set()
        for block in blocks: # Maintenant 'blocks' n'est plus vide !
            for pos in block["positions"]:
                field_name = f"team_{block['key']}_{pos}"
                team_id_raw = request.POST.get(field_name)
                if team_id_raw and team_id_raw.isdigit():
                    t_id = int(team_id_raw)
                    if t_id not in recorded_teams:
                        CompetitionTeamPrediction.objects.create(
                            competition=selected_competition,
                            player=request.user.player,
                            team_id=t_id,
                            position=pos,
                            block_key=block["key"]
                        )
                        recorded_teams.add(t_id)
        
        messages.success(request, "Vos pronostics ont Ã©tÃ© enregistrÃ©s !")
        season_param = f"&season={season.id}" if season else ""
        return redirect(f"{request.path}?competition={selected_competition.id}{season_param}")

    # --- RÃ‰CUPÃ‰RATION POUR AFFICHAGE (GET) ---
    if selected_competition and season:
        for block in blocks:
            saved_preds = CompetitionTeamPrediction.objects.filter(
                competition=selected_competition,
                player=request.user.player,
                block_key=block["key"],
                season=season
            )
            # CRUCIAL : On s'assure que la clÃ© est un entier (pos) 
            # et la valeur est un entier (ID de l'Ã©quipe)
            block["saved"] = {int(p.position): int(p.team.id) for p in saved_preds}
            
    # RÃ©cupÃ©ration propre pour l'affichage du rÃ©capitulatif
    last_saved_ranking = []
    if selected_competition and season:
        last_saved_ranking = CompetitionTeamPrediction.objects.filter(
            competition=selected_competition,
            player=request.user.player,
            season=season
        ).select_related('team').order_by('block_key', 'position')

    return render(request, "pronos/classement.html", {
        "season": season,
        "competitions": competitions,
        "seasons": seasons,
        "selected_competition": selected_competition,
        "blocks": blocks,
        "bonus": bonus,
        "winner_teams": winner_teams,
        "last_saved_ranking": last_saved_ranking,
    })

@login_required
def all_pronos_view(request):
    now = timezone.now()
    is_admin = request.user.is_staff or request.user.is_superuser
    
    # 1. RÃ©cupÃ©ration des IDs
    comp_id = request.GET.get("comp")
    season_id = request.GET.get("season")
    round_id = request.GET.get("round")

    all_competitions = Competition.objects.all().order_by('name')
    
    # 2. DÃ©termination de la compÃ©tition
    if comp_id:
        selected_comp = all_competitions.filter(id=comp_id).first()
    else:
        next_match = Match.objects.filter(kickoff_at__gte=now).order_by('kickoff_at').first()
        if next_match:
            selected_comp = next_match.round.season.competition
        else:
            selected_comp = all_competitions.first()

    # 3. DÃ©termination de la saison (FILTRÃ‰E par la compÃ©tition choisie)
    seasons = Season.objects.filter(competition=selected_comp, year__gte=2025).order_by('-year')
    
    if season_id and seasons.filter(id=season_id).exists():
        selected_season = seasons.filter(id=season_id).first()
    else:
        # Si on change de comp, season_id devient invalide, on prend la plus rÃ©cente de la nouvelle comp
        selected_season = seasons.first()

    # 4. DÃ©termination des journÃ©es (FILTRÃ‰ES par la saison choisie)
    rounds = Round.objects.filter(season=selected_season).order_by('number')

    # 5. DÃ©termination du Round final Ã  afficher
    # On initialise Ã  None
    current_round_obj = None

    # PRIORITÃ‰ 1 : L'utilisateur a choisi un round manuellement
    if round_id and round_id.isdigit():
        current_round_obj = rounds.filter(id=round_id).first()

    # PRIORITÃ‰ 2 : Si aucun round choisi (ou ID invalide), on lance l'automatisme
    if not current_round_obj:
        current_round_obj = _find_next_round(rounds, now)

    rows = []
    players = _players_for_season(selected_season).select_related('user').order_by('user__username')

    if current_round_obj:
        matches = Match.objects.filter(round=current_round_obj).select_related('home_team', 'away_team').order_by("kickoff_at")
        predictions = Prediction.objects.filter(match__round=current_round_obj)
        threshold = current_round_obj.season.competition.bonus_defense_threshold

        for m in matches:
            is_locked = now > m.kickoff_at if m.kickoff_at else False
            has_result = m.home_score is not None and m.away_score is not None
            real_bd = m.get_defense_bonus() # Attendu: 'HOME', 'AWAY' ou None
            
            player_pronos = []
            for p in players:
                prono = next((pred for pred in predictions if pred.match_id == m.id and pred.player_id == p.id), None)
                
                # Init du dictionnaire de donnÃ©es pour le template
                p_dict = {
                    'has_prono': prono is not None,
                    'score_home': None, 'score_away': None,
                    'class': "", 'display_locked': False,
                    'is_perfect_home': False, 'is_perfect_away': False,
                    'bo_home_ok': False, 'bo_home_ko': False,
                    'bd_home_ok': False, 'bd_home_ko': False,
                    'bo_away_ok': False, 'bo_away_ko': False,
                    'bd_away_ok': False, 'bd_away_ko': False,
                    'pending_home': False, 'pending_away': False,
                }

                if not is_locked and not is_admin:
                    p_dict['display_locked'] = True
                
                if (is_locked or is_admin) and prono:
                    p_dict.update({'score_home': prono.home_score_pred, 'score_away': prono.away_score_pred})
                    
                    if has_result:
                        # 1. Scores Exacts
                        p_dict['is_perfect_home'] = (prono.home_score_pred == m.home_score)
                        p_dict['is_perfect_away'] = (prono.away_score_pred == m.away_score)

                        # 2. Bonus Offensifs (BO)
                        if prono.bonus_home_pred:
                            if m.bonus_offense_home: p_dict['bo_home_ok'] = True
                            else: p_dict['bo_home_ko'] = True
                        if prono.bonus_away_pred:
                            if m.bonus_offense_away: p_dict['bo_away_ok'] = True
                            else: p_dict['bo_away_ko'] = True
                        
                        # 3. Bonus DÃ©fensifs (BD) - Logique Auto
                        # Home prÃ©dit BD
                        if prono.home_score_pred < prono.away_score_pred and (prono.away_score_pred - prono.home_score_pred) <= threshold:
                            if real_bd == 'HOME' or m.home_score == m.away_score: p_dict['bd_home_ok'] = True
                            else: p_dict['bd_home_ko'] = True
                        # Away prÃ©dit BD
                        if prono.away_score_pred < prono.home_score_pred and (prono.home_score_pred - prono.away_score_pred) <= threshold:
                            if real_bd == 'AWAY' or m.home_score == m.away_score: p_dict['bd_away_ok'] = True
                            else: p_dict['bd_away_ko'] = True
                    else:
                        # Match non jouÃ© : Orange si un bonus est "dans les tuyaux"
                        if prono.bonus_home_pred or (prono.home_score_pred < prono.away_score_pred and (prono.away_score_pred - prono.home_score_pred) <= threshold):
                            p_dict['pending_home'] = True
                        if prono.bonus_away_pred or (prono.away_score_pred < prono.home_score_pred and (prono.home_score_pred - prono.away_score_pred) <= threshold):
                            p_dict['pending_away'] = True

                    # Background couleur selon vainqueur prÃ©dit
                    if prono.home_score_pred > prono.away_score_pred: p_dict['class'] = "bg-home-win"
                    elif prono.away_score_pred > prono.home_score_pred: p_dict['class'] = "bg-away-win"
                    else: p_dict['class'] = "bg-draw"

                player_pronos.append(p_dict)

            rows.append({
                'info': f"{m.home_team.name if m.home_team else 'TBD'} - {m.away_team.name if m.away_team else 'TBD'}",
                'reel_home': m.home_score,
                'reel_away': m.away_score,
                'bo_reel_home': m.bonus_offense_home,
                'bd_reel_home': (real_bd == 'HOME'),
                'bo_reel_away': m.bonus_offense_away,
                'bd_reel_away': (real_bd == 'AWAY'),
                'player_pronos': player_pronos,
                'is_locked': is_locked
            })

    prev_round_id, next_round_id = _get_adjacent_rounds(
        rounds, current_round_obj.id if current_round_obj else None
    )

    # Stats prÃ©dictions pour l'admin
    player_status = []
    if current_round_obj:
        match_ids = {m.id for m in matches}
        for p in players:
            p_preds = [pr for pr in predictions if pr.player_id == p.id and pr.match_id in match_ids and pr.home_score_pred is not None]
            done = len(p_preds)
            total = len(matches)
            if done == 0:
                status = 'missing'
            elif done < total:
                status = 'partial'
            else:
                status = 'complete'
            player_status.append({'player': p, 'status': status, 'done': done, 'total': total})

    return render(request, "pronos/all_pronos.html", {
        "rows": rows, "players": players, "competitions": all_competitions,
        "seasons": seasons, "rounds": rounds, "selected_comp": selected_comp,
        "selected_season": selected_season, "current_round_obj": current_round_obj,
        "prev_round_id": prev_round_id, "next_round_id": next_round_id,
        "player_status": player_status, "is_admin": is_admin,
    })  

@login_required
def round_results_board(request, round_id):
    # 1. RÃ©cupÃ©ration de l'objet et gestion des changements via GET
    round_obj = get_object_or_404(Round.objects.select_related('season__competition'), id=round_id)
    
    new_comp_id = request.GET.get('comp')
    new_season_id = request.GET.get('season')

    if new_comp_id and int(new_comp_id) != round_obj.season.competition.id:
        selected_comp = get_object_or_404(Competition, id=new_comp_id)
        selected_season = Season.objects.filter(competition=selected_comp, year__gte=2025).order_by('-year').first()
        if selected_season:
            first_round = Round.objects.filter(season=selected_season).order_by('number').first()
            if first_round:
                return redirect('round_board', round_id=first_round.id)

    if new_season_id and int(new_season_id) != round_obj.season.id:
        selected_season = get_object_or_404(Season, id=new_season_id)
        first_round = Round.objects.filter(season=selected_season).order_by('number').first()
        if first_round:
            return redirect('round_board', round_id=first_round.id)

    # 2. PrÃ©paration des donnÃ©es de base
    selected_comp = round_obj.season.competition
    selected_season = round_obj.season
    
    seasons = Season.objects.filter(competition=selected_comp, year__gte=2025).order_by('-year')
    rounds = Round.objects.filter(season=selected_season).order_by('number')
    players = _players_for_season(selected_season).order_by('name')
    matches = Match.objects.filter(round=round_obj).select_related('home_team', 'away_team').order_by('kickoff_at')
    all_competitions = Competition.objects.prefetch_related(
        Prefetch('seasons', queryset=Season.objects.all().order_by('-year'))
    ).distinct()

    # 3. Configuration du BarÃ¨me et des Multiplicateurs
    comp_name = round_obj.season.competition.name
    current_scale = scoring.BONUS_SCALES.get(comp_name, {})
    
    # Multiplicateur de compÃ©tition (ex: 6 Nations)
    comp_multiplier = 2 if ("6 Nations" in comp_name or "Six Nations" in comp_name) else 1
    
    # Multiplicateur de phase (ex: POOL=1, R16=1.25, QF=1.5...)
    phase_multiplier = scoring.PHASE_MULTIPLIERS.get(round_obj.phase, 1.0)
    
    # SÃ©curitÃ© pour les bonus BO/BD (Uniquement en POOL)
    is_pool_phase = (round_obj.phase == "POOL")

    # 4. Toutes les prÃ©dictions du round en UNE requÃªte
    all_preds = list(Prediction.objects.filter(
        match__round=round_obj
    ).select_related(
        'player', 'match'
    ))

    # Index par match pour la matrice des points
    preds_by_match_player = {}
    for pr in all_preds:
        key = (pr.match_id, pr.player_id)
        preds_by_match_player[key] = pr

    # Index par joueur pour les stats
    preds_by_player = {p.id: [] for p in players}
    for pr in all_preds:
        if pr.player_id in preds_by_player:
            preds_by_player[pr.player_id].append(pr)

    # 5. PrÃ©-calcul des gagnants par match (Partage du pool)
    match_winners_counts = {}
    for m in matches:
        if m.home_score is not None and m.away_score is not None:
            real_side = get_winner_side(m.home_score, m.away_score)
            winners_count = 0
            for pr in all_preds:
                if pr.match_id != m.id: continue
                pred_side = get_winner_side(pr.home_score_pred, pr.away_score_pred)
                if pred_side == real_side:
                    winners_count += 1
            match_winners_counts[m.id] = winners_count
        else:
            match_winners_counts[m.id] = 0

    # 6. Construction de la matrice des points
    matrix = {}
    for m in matches:
        matrix[m.id] = {}
        for p in players:
            pr = preds_by_match_player.get((m.id, p.id))
            matrix[m.id][p.id] = pr.points if (pr and pr.points is not None) else 0

    # 7. Calcul des totaux et stats par joueur
    totals_display = []
    for p in players:
        player_preds = preds_by_player.get(p.id, [])
        stats = {
            'pm': 0, 'winners': 0, 'bo': 0, 'bd': 0, 'diff': 0, 
            'somme': 0, 'ext': 0, 'dtp': 0, 'draw': 0, 'tp': 0
        }

        for pr in player_preds:
            m = pr.match
            if m.home_score is None or m.away_score is None: continue
            
            match_threshold = round_obj.season.competition.bonus_defense_threshold
            
            real_winner_side = get_winner_side(m.home_score, m.away_score)
            pred_winner_side = get_winner_side(pr.home_score_pred, pr.away_score_pred)
            if pr.home_score_pred + pr.away_score_pred == 0:
                pred_winner_side = "NO SHOW"
            
            # --- Partage du Pool (PM) ---
            if real_winner_side == pred_winner_side:
                stats['winners'] += 1
                winners_count = match_winners_counts.get(m.id, 0)
                if winners_count > 0:
                    stats['pm'] += (m.weight // winners_count)

            # --- Bonus BO / BD (Uniquement si POOL) ---
            if is_pool_phase:
                if pr.bonus_home_pred:
                    stats['bo'] += scoring.SCORING_CONFIG['OFFENSIVE_BONUS_VALUE'] if m.bonus_offense_home else scoring.SCORING_CONFIG['BONUS_MALUS']
                if pr.bonus_away_pred:
                    stats['bo'] += scoring.SCORING_CONFIG['OFFENSIVE_BONUS_VALUE'] if m.bonus_offense_away else scoring.SCORING_CONFIG['BONUS_MALUS']
                
                real_bd = m.get_defense_bonus()
                player_diff = abs(pr.home_score_pred - pr.away_score_pred)
                pred_bd = None
                if player_diff <= match_threshold and pred_winner_side != "NO SHOW":
                    if pr.home_score_pred < pr.away_score_pred: pred_bd = 'HOME'
                    elif pr.away_score_pred < pr.home_score_pred: pred_bd = 'AWAY'
                    else: pred_bd = 'DRAW'
                
                if pred_bd in ['HOME', 'AWAY']:
                    if pred_bd == real_bd or m.home_score == m.away_score:
                        stats['bd'] += scoring.SCORING_CONFIG['DEFENSIVE_BONUS_VALUE']
                    elif real_bd is None:
                        stats['bd'] += scoring.SCORING_CONFIG['BONUS_MALUS']
                elif pred_bd == 'DRAW':
                    if real_bd: stats['bd'] += scoring.SCORING_CONFIG['DEFENSIVE_BONUS_VALUE']
                    else: stats['bd'] += scoring.SCORING_CONFIG['BONUS_MALUS']

            # --- Scores Exacts, Somme et Diff ---
            home_diff = abs(pr.home_score_pred - m.home_score)
            away_diff = abs(pr.away_score_pred - m.away_score)
            
            if pred_winner_side != "NO SHOW":
                if home_diff == 0: stats['dtp'] += scoring.SCORING_CONFIG['HALF_PERFECT_BONUS']
                if away_diff == 0: stats['dtp'] += scoring.SCORING_CONFIG['HALF_PERFECT_BONUS']
                if home_diff == 0 and away_diff == 0: stats['tp'] += scoring.SCORING_CONFIG['PERFECT_SCORE_BONUS']

                diff_err = abs((pr.home_score_pred - pr.away_score_pred) - (m.home_score - m.away_score))
                sum_err = abs((pr.home_score_pred + pr.away_score_pred) - (m.home_score + m.away_score))
                
                if sum_err in scoring.SCORING_CONFIG['SUM_TABLE']:
                    stats['somme'] += scoring.SCORING_CONFIG['SUM_TABLE'][sum_err]
                if diff_err in scoring.SCORING_CONFIG['DIFF_TABLE']:
                    stats['diff'] += scoring.SCORING_CONFIG['DIFF_TABLE'][diff_err]

            # --- ExtÃ©rieur et Nul ---
            real_winner_obj = m.winner()
            if real_winner_obj == m.away_team and pr.away_score_pred > pr.home_score_pred:
                stats['ext'] += scoring.SCORING_CONFIG['AWAY_WIN_BONUS']
            if real_winner_obj == "DRAW" and pr.home_score_pred == pr.away_score_pred and pred_winner_side != "NO SHOW":
                stats['draw'] += scoring.SCORING_CONFIG['DRAW_BONUS']

        # Bonus de Palier (basÃ© sur le nombre de gagnants trouvÃ©s)
        daily_bonus = 0
        for threshold in sorted(current_scale.keys(), reverse=True):
            if stats['winners'] >= threshold:
                daily_bonus = current_scale[threshold]
                break

        # Score final avec tous les multiplicateurs
        raw_score = (
            stats['pm'] + stats['tp'] + stats['dtp'] + stats['bo'] + 
            stats['bd'] + stats['diff'] + stats['somme'] + 
            stats['ext'] + stats['draw'] + daily_bonus
        )
        
        final_score = int(raw_score * phase_multiplier * comp_multiplier)

        totals_display.append({
            'player': p,
            'pm': stats['pm'],
            'winners': stats['winners'],
            'dtp': stats['dtp'],
            'bo': stats['bo'],
            'bd': stats['bd'],
            'diff': stats['diff'],
            'somme': stats['somme'],
            'ext': stats['ext'],
            'bonus': daily_bonus,
            'score': final_score,
            'rank_class': ''
        })

    # 7. Attribution des mÃ©dailles
    scores_uniques = sorted(list(set(t['score'] for t in totals_display if t['score'] > 0)), reverse=True)
    if scores_uniques:
        min_score = min(t['score'] for t in totals_display)
        for entry in totals_display:
            if entry['score'] > 0:
                if entry['score'] == scores_uniques[0]: entry['rank_class'] = 'gold'
                elif len(scores_uniques) > 1 and entry['score'] == scores_uniques[1]: entry['rank_class'] = 'silver'
                elif len(scores_uniques) > 2 and entry['score'] == scores_uniques[2]: entry['rank_class'] = 'bronze'
            if entry['score'] == min_score and len(totals_display) > 1:
                entry['rank_class'] = 'wooden-spoon'

    prev_round_id, next_round_id = _get_adjacent_rounds(rounds, round_id)
    context = {
        'round': round_obj,
        'rounds': rounds,
        'matches': matches,
        'players': players,
        'matrix': matrix,
        'totals': totals_display,
        'all_competitions': all_competitions,
        'seasons': seasons,
        'selected_comp': selected_comp,
        'selected_season': selected_season,
        'prev_round_id': prev_round_id,
        'next_round_id': next_round_id,
    }
    return render(request, 'round_board.html', context)

@staff_member_required
def bonus_view(request, round_id):
    round_obj = get_object_or_404(Round.objects.select_related("season__competition"), id=round_id)
    matches = Match.objects.filter(round=round_obj).select_related("home_team", "away_team").order_by("kickoff_at")

    if request.method == "POST":
        for match in matches:
            home_key = f"bo_home_{match.id}"
            away_key = f"bo_away_{match.id}"
            match.bonus_offense_home = home_key in request.POST
            match.bonus_offense_away = away_key in request.POST
            match.save()
        messages.success(request, "Bonus enregistrÃ©s")
        return HttpResponseRedirect(request.path)
    return render(request, "bonus.html", {
        "round": round_obj,
        "matches": matches,
    })

@staff_member_required
def compute_round_view(request, round_id):
    round_obj = get_object_or_404(Round, id=round_id)
    # On appelle ton script de scoring
    process_round_scores(round_obj)
    # Une fois fini, on revient sur la page des rÃ©sultats
    return redirect('round_board', round_id=round_id)

@login_required
def statistiques_view(request):
    competition_id = request.GET.get("competition", "").strip()
    season_id = request.GET.get("season", "").strip()
    
    competitions = Competition.objects.all().order_by("name")

    # 1. Gestion de la CompÃ©tition
    competition = None
    if competition_id and competition_id.isdigit():
        competition = Competition.objects.filter(id=int(competition_id)).first()

    # 2. Gestion des Saisons & Construction des libellÃ©s uniques pour le menu
    seasons_qs = Season.objects.filter(
        Q(rounds__dailyscore__points__gt=0) |
        Q(seasonscore__match_points__gt=0) |
        Q(seasonscore__ranking_points__gt=0) |
        Q(seasonscore__podium_points__gt=0) |
        Q(rounds__matches__kickoff_at__isnull=False)  # saisons avec matchs programmÃ©s (mÃªme sans scores)
    ).distinct().order_by("-year", "competition__name")
    
    if competition:
        seasons_qs = seasons_qs.filter(competition=competition)

    # Helper : extraire l'annÃ©e de dÃ©but d'une saison
    # "2025/2026" â†’ "2025", "2026" (6 Nations) â†’ "2025", "2024-2025" â†’ "2024"
    def get_season_key(year_str):
        if '/' in year_str:
            return year_str.split('/')[0]
        if '-' in year_str:
            return year_str.split('-')[0]
        if year_str.isdigit():
            return str(int(year_str) - 1)
        return year_str

    distinct_seasons = []
    season_key_to_id = {}     # "2025" â†’ 1 (pour le dropdown)
    season_groups = {}        # "2025" â†’ [Season.id, ...] (pour le filtrage)
    id_counter = 1

    for s in seasons_qs:
        if not competition:
            # Mode global : regrouper par clÃ© de saison (ex: Top14 2025/2026 + 6N 2026 â†’ "2025-2026")
            season_key = get_season_key(s.year)
            if season_key not in season_groups:
                season_groups[season_key] = []
            season_groups[season_key].append(s.id)

            if season_key not in season_key_to_id:
                season_key_to_id[season_key] = id_counter
                distinct_seasons.append({
                    'id': id_counter,
                    'label': f"Saison {season_key}-{int(season_key)+1}",
                    'year': season_key
                })
                id_counter += 1
        else:
            # Mode compÃ©tition spÃ©cifique : garder l'ID unique de la saison
            season_key = get_season_key(s.year)
            distinct_seasons.append({
                'id': s.id,
                'label': s.year,
                'year': s.year
            })

    # Trier du plus rÃ©cent au plus ancien
    if not competition:
        distinct_seasons.sort(key=lambda x: int(x['year']), reverse=True)
    else:
        distinct_seasons.sort(key=lambda x: int(get_season_key(x['year'])), reverse=True)

    # 3. SÃ©lection de la saison
    selected_season = None
    selected_year = None

    if season_id:
        if competition:
            # Mode compÃ©tition : season_id = Season.pk
            if season_id.isdigit():
                selected_season = Season.objects.filter(id=int(season_id)).first()
                if selected_season:
                    selected_year = selected_season.year
        else:
            # Mode global : season_id = ID entier du groupe
            if season_id.isdigit():
                season_id_int = int(season_id)
                for key, key_id in season_key_to_id.items():
                    if key_id == season_id_int:
                        selected_year = key
                        break
    
    # Si aucune saison sÃ©lectionnÃ©e, prendre la plus rÃ©cente par dÃ©faut
    if not selected_year and not selected_season:
        if not competition and distinct_seasons:
            selected_year = distinct_seasons[0]['year']
        elif competition and distinct_seasons:
            selected_season = Season.objects.filter(id=distinct_seasons[0]['id']).first()
            if selected_season:
                selected_year = selected_season.year
            
    # 4. Calcul des stats de base via ta fonction existante
    if not competition and selected_year and selected_year in season_groups:
        stats = compute_statistics(None, season_ids=season_groups[selected_year])
    else:
        stats = compute_statistics(competition, season=selected_season)

    # --- 5. SÃ‰CURISATION ET SYNCHRONISATION DES SCORES DEPUIS SEASONSCORE ---
    season_scores = {}
    try:
        qs = SeasonScore.objects.all()
        
        if competition:
            if selected_season:
                qs = qs.filter(season=selected_season)
        else:
            # Mode global : filtrer par les IDs des saisons du groupe sÃ©lectionnÃ©
            if selected_year and selected_year in season_groups:
                qs = qs.filter(season_id__in=season_groups[selected_year])
            
        user_points = qs.values('user__username').annotate(
            total_match=Sum('match_points'),
            total_ranking=Sum('ranking_points'),
            total_podium=Sum('podium_points')
        )
        
        for item in user_points:
            season_scores[item['user__username']] = {
                'match_pts': item['total_match'] or 0,
                'ranking_pts': item['total_ranking'] or 0,
                'podium_pts': item['total_podium'] or 0,
            }
    except Exception:
        season_scores = {}

    # --- 5B. INJECTION DES POINTS F/P DANS LES SÃ‰RIES GRAPHIQUES ---
    num_rounds = len(stats.labels)
    for username, scores in season_scores.items():
        if username in stats.flair_series and num_rounds > 0:
            stats.flair_series[username][-1] = scores['ranking_pts']
        if username in stats.podium_series and num_rounds > 0:
            stats.podium_series[username][-1] = scores['podium_pts']

    # Remplissage et mise Ã  jour de detailed_ranking
    for r in stats.detailed_ranking:
        username = r['username']
        user_scores = season_scores.get(username, {'match_pts': 0, 'ranking_pts': 0, 'podium_pts': 0})
        
        # On injecte les valeurs synchronisÃ©es
        r['match_pts'] = user_scores['match_pts'] if user_scores['match_pts'] > 0 else r.get('points', 0)
        r['ranking_pts'] = user_scores['ranking_pts']
        r['podium_pts'] = user_scores['podium_pts']
        
        # Recalcul strict du total
        r['total_global'] = r['match_pts'] + r['ranking_pts'] + r['podium_pts']

    # Tri par total global dÃ©croissant, puis par points de matchs
    stats.detailed_ranking.sort(key=lambda x: (x['total_global'], x['match_pts']), reverse=True)
    
    # On cherche la derniÃ¨re journÃ©e modifiÃ©e pour le bouton RÃ©sultats
    last_round_id = None
    if selected_season:
        lr = Round.objects.filter(
            season=selected_season,
            dailyscore__isnull=False
        ).order_by('-date', '-number').first()
        if not lr:
            lr = Round.objects.filter(
                season=selected_season,
                matches__home_score__isnull=False
            ).distinct().order_by('-date', '-number').first()
        if not lr:
            lr = Round.objects.filter(season=selected_season).order_by('-number').first()
        if lr:
            last_round_id = lr.id

    match_ranking = sorted(
        [r for r in stats.detailed_ranking if r.get('match_pts', 0) > 0],
        key=lambda x: x['match_pts'], reverse=True
    ) or stats.detailed_ranking
    podium_ranking = sorted(
        stats.detailed_ranking,
        key=lambda x: x.get('podium_pts', 0), reverse=True
    )
    context = {
        "competitions": competitions,
        "competition": competition,
        "seasons": distinct_seasons,
        "selected_season": selected_season,
        "kpi": stats.kpi,
        "labels": stats.labels,
        "score_series": stats.score_series,
        "rank_series": stats.rank_series,
        "flair_series": stats.flair_series,
        "podium_series": stats.podium_series,
        "detailed_ranking": stats.detailed_ranking,
        "choppes_or": stats.choppes_or,
        "chopes_cumulees": stats.chopes_cumulees,
        "cuilleres_bois": stats.cuilleres_bois,
        "flair_ranking": sorted(stats.detailed_ranking, key=lambda x: x.get('ranking_pts', 0), reverse=True),
        "victory_table": getattr(stats, 'victory_table', []),
        "last_round_id": last_round_id,
        "pie_labels": stats.pie_labels,
        "pie_values": stats.pie_values,
        "demi_tout_pile_table": stats.demi_tout_pile_table,
        "bonus_off_table": stats.bonus_off_table,
        "bonus_def_table": stats.bonus_def_table,
        "match_ranking": match_ranking,
        "podium_ranking": podium_ranking,
    }

    return render(request, "statistiques.html", context)


@login_required
def debug_scores_view(request):
    # 1. RÃ©cupÃ©rer toutes les compÃ©titions pour le premier menu
    competitions = Competition.objects.all().order_by('name')
    
    # 2. RÃ©cupÃ©rer la compÃ©tition sÃ©lectionnÃ©e
    competition_id = request.GET.get('competition')
    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
    else:
        selected_competition = competitions.first()

    if not selected_competition:
        return render(request, "debug_scores.html", {"error": "Aucune compÃ©tition trouvÃ©e"})

    # 3. RÃ©cupÃ©rer les SAISONS de cette compÃ©tition pour le deuxiÃ¨me menu
    seasons = Season.objects.filter(competition=selected_competition, year__gte=2025).order_by('-year')
    
    # 4. RÃ©cupÃ©rer la saison sÃ©lectionnÃ©e (ou la derniÃ¨re par dÃ©faut)
    season_id = request.GET.get('season')
    if season_id:
        selected_season = get_object_or_404(Season, id=season_id)
    else:
        selected_season = seasons.first()

    # 5. Filtrer les Rounds UNIQUEMENT pour cette saison
    rounds = Round.objects.filter(season=selected_season).select_related('season').order_by('number')
    players = _players_for_season(selected_season).filter(user__isnull=False).order_by('name')
    
    # 6. Matrice de scores (ton code reste le mÃªme, mais filtrÃ© par rounds de la saison)
    daily_scores = DailyScore.objects.filter(round__in=rounds).select_related('user', 'round')
    score_matrix = {}
    for score in daily_scores:
        if score.user_id not in score_matrix:
            score_matrix[score.user_id] = {}
        score_matrix[score.user_id][score.round_id] = score.points

    player_data = []
    for p in players:
        row = {'player': p, 'scores': [], 'total_calc': 0}
        for r in rounds:
            pts = score_matrix.get(p.user_id, {}).get(r.id, 0)
            row['scores'].append(pts)
            row['total_calc'] += pts
        player_data.append(row)

    return render(request, "debug_scores.html", {
        "selected_competition": selected_competition,
        "selected_season": selected_season,
        "competitions": competitions,
        "seasons": seasons,
        "rounds": rounds,
        "player_data": player_data,
    })    
    
@login_required
def recap_pronos_classement(request):
    competitions = Competition.objects.all()
    competition_id = request.GET.get("competition")
    season_id = request.GET.get("season")
    
    # Initialisation systÃ©matique pour Ã©viter les erreurs dans le template
    selected_competition = None
    real_rankings = {}
    real_winner = None
    result_obj = None
    season = None
    seasons = []
    players = Player.objects.all().order_by('name')
    matrix = {} 
    teams_by_block = {}
    bonus_preds = []

    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
        seasons = Season.objects.filter(competition=selected_competition, year__gte=2025).order_by("-year")
        
        # On rÃ©cupÃ¨re la saison
        season = seasons.filter(id=season_id).first() if season_id else seasons.first()
        
        if season:
            players = _players_for_season(season).order_by('name')
            # VÃ©rification du verrouillage
            if not season.has_started and not request.user.is_staff:
                messages.warning(request, "Les pronostics des autres joueurs seront visibles dÃ¨s le coup d'envoi !")
                return redirect('pronos')
            
            # RÃ©cupÃ©ration des rÃ©sultats rÃ©els (SORTI DU ELSE, il doit Ãªtre ici !)
            result_obj = CompetitionResult.objects.filter(season=season).first()
            if result_obj:
                real_rankings = result_obj.rankings_json
                real_winner = result_obj.real_winner

        # RÃ©cupÃ©ration des pronostics des joueurs
        preds = CompetitionTeamPrediction.objects.filter(competition=selected_competition, season=season).select_related('player', 'team')
        
        for p in preds:
            if p.block_key not in matrix:
                matrix[p.block_key] = {}
                teams_by_block[p.block_key] = []
            
            if p.team not in teams_by_block[p.block_key]:
                teams_by_block[p.block_key].append(p.team)
                
            if p.team.id not in matrix[p.block_key]:
                matrix[p.block_key][p.team.id] = {}
            
            matrix[p.block_key][p.team.id][p.player.id] = p.position

        bonus_preds = CompetitionBonusPrediction.objects.filter(competition=selected_competition, season=season).select_related('player', 'winner')

    return render(request, "pronos/recap_classement.html", {
        "competitions": competitions,
        "selected_competition": selected_competition,
        "players": players,
        "matrix": matrix,
        "teams_by_block": teams_by_block,
        "bonus_preds": bonus_preds,
        "real_rankings": real_rankings,
        "real_winner": real_winner,
        "real_results": result_obj,
        "season": season,
        "seasons": seasons,
    })
    
    
def compute_competition_points(season):
    result = CompetitionResult.objects.filter(season=season).first()
    if not result:
        return "Aucun rÃ©sultat saisi."

    rules = RUGBY_SCORING.get(season.competition.name, RUGBY_SCORING["Top 14"])
    players = _players_for_season(season)
    
    for player in players:
        pts_classement = 0
        pts_bonus_finaux = 0
        
        # 1. CALCUL CLASSEMENT : On filtre par season !
        user_preds = CompetitionTeamPrediction.objects.filter(
            player=player, 
            competition=season.competition,
            season=season  # Crucial
        )
        for p in user_preds:
            real_block = result.rankings_json.get(p.block_key, {})
            real_pos = real_block.get(str(p.team.id))
            if real_pos:
                diff = abs(p.position - int(real_pos))
                if diff == 0: pts_classement += rules["exact_rank"]
                elif diff == 1: pts_classement += rules["gap_1"]
                elif diff == 2: pts_classement += rules["gap_2"]

        # 2. CALCUL VAINQUEUR & BONUS : On filtre par season !
        bonus_pred = CompetitionBonusPrediction.objects.filter(
            player=player, 
            competition=season.competition,
            season=season  # Crucial
        ).first()
        
        if bonus_pred and result.real_winner:
            if bonus_pred.winner == result.real_winner:
                pts_bonus_finaux += rules["winner"]
            
            if result.real_best_try_scorer:
                if bonus_pred.best_try_scorer.lower().strip() == result.real_best_try_scorer.lower().strip():
                    pts_bonus_finaux += rules["bonus"]
            if result.real_best_point_scorer:
                if bonus_pred.best_point_scorer.lower().strip() == result.real_best_point_scorer.lower().strip():
                    pts_bonus_finaux += rules["bonus"]

        # 3. SAUVEGARDE : On utilise la saison pour identifier la bonne ligne
        if player.user:
            s_score, _ = SeasonScore.objects.get_or_create(
                user=player.user, 
                competition=season.competition,
                season=season  # Crucial pour ne pas Ã©craser 2025
            )
            s_score.ranking_points = pts_classement + pts_bonus_finaux
            s_score.save()       
        
@staff_member_required
def admin_saisie_resultats(request):
    competitions = Competition.objects.all()
    competition_id = request.GET.get("competition")
    selected_competition = None
    blocks = []
    season = None

    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
        season = Season.objects.filter(competition=selected_competition, year__gte=2025).order_by("-year").first()
        
        # PrÃ©paration des blocs (MÃªme logique que ta vue classement_prediction)
        if selected_competition.name.lower() == "champions cup":
            for pool in range(1, 5):
                comp_teams = CompetitionTeam.objects.filter(competition=selected_competition, season=season, pool=pool)
                blocks.append({
                    "key": f"pool{pool}",
                    "teams": [ct.team for ct in comp_teams],
                    "positions": list(range(1, 7))
                })
        else:
            teams = selected_competition.teams.all().order_by("name")
            blocks.append({
                "key": "all",
                "teams": teams,
                "positions": list(range(1, teams.count() + 1))
            })

    if request.method == "POST":
        res_obj, _ = CompetitionResult.objects.get_or_create(season=season)
        
        # 1. Sauvegarde des bonus rÃ©els
        res_obj.real_best_try_scorer = request.POST.get("real_best_try_scorer", "").strip()
        res_obj.real_best_point_scorer = request.POST.get("real_best_point_scorer", "").strip()
        winner_id = request.POST.get("real_winner")
        res_obj.real_winner_id = int(winner_id) if winner_id else None

        # 2. Construction du JSON des classements
        rank_data = {}
        for block in blocks:
            rank_data[block["key"]] = {}
            for pos in block["positions"]:
                team_id = request.POST.get(f"team_{block['key']}_{pos}")
                if team_id:
                    rank_data[block["key"]][str(team_id)] = pos
        
        res_obj.rankings_json = rank_data
        res_obj.save()
        messages.success(request, "RÃ©sultats officiels enregistrÃ©s !")
        return redirect(f"{request.path}?competition={selected_competition.id}")

    return render(request, "pronos/admin_saisie_resultats.html", {
        "competitions": competitions,
        "selected_competition": selected_competition,
        "blocks": blocks,
        "season": season,
    })
    
    
@staff_member_required
def declencher_calcul_points(request, season_id):
    season = get_object_or_404(Season, id=season_id)
    # On appelle la fonction de calcul dÃ©finie prÃ©cÃ©demment
    message_resultat = compute_competition_points(season)
    
    if isinstance(message_resultat, str):
        messages.error(request, message_resultat)
    else:
        messages.success(request, "Les points de classement ont Ã©tÃ© mis Ã  jour pour tous les joueurs !")
        
    return redirect('recap_classement')


def charte_view(request):
    return render(request, "pronos/charte.html")

@login_required
def statistics_view(request):
    comp_id = request.GET.get('competition')
    season_id = request.GET.get('season')

    # --- 1. LOGIQUE HISTORIQUE : LA MATRICE DES MATCHS ---
    query = Match.objects.filter(home_score__isnull=False, away_score__isnull=False, phase='POOL')

    if comp_id:
        query = query.filter(round__season__competition_id=comp_id)
    if season_id:
        query = query.filter(round__season_id=season_id)

    stats = query.values('home_score', 'away_score').annotate(total=Count('id'))

    matrix, row_totals, col_totals = {}, {}, {}
    max_occurence, max_h, max_a = 0, 0, 0

    for s in stats:
        h, a, t = s['home_score'], s['away_score'], s['total']
        if h not in matrix: matrix[h] = {}
        matrix[h][a] = t
        row_totals[h] = row_totals.get(h, 0) + t
        col_totals[a] = col_totals.get(a, 0) + t
        if t > max_occurence: max_occurence = t
        if h > max_h: max_h = h
        if a > max_a: max_a = a
    # --- 2. CLASSEMENT DÃ‰TAILLÃ‰ & PODIUM ---
    detailed_ranking = []
    flair_ranking = []
    
    # CONVERSION STRICTE DES PARAMÃˆTRES EN ENTIERS POUR L'ORM
    try:
        comp_id = int(comp_id) if comp_id else None
    except (ValueError, TypeError):
        comp_id = None

    try:
        season_id = int(season_id) if season_id else None
    except (ValueError, TypeError):
        season_id = None
    
    # 1. Gestion de la saison par dÃ©faut liÃ©e Ã  la compÃ©tition choisie
    if not season_id:
        if comp_id:
            # On cherche d'abord s'il y a une saison qui a des rÃ©sultats de fin de saison validÃ©s
            active_season_res = CompetitionResult.objects.filter(season__competition_id=comp_id).order_by('-season__year').first()
            if active_season_res:
                default_season = active_season_res.season
            else:
                default_season = Season.objects.filter(competition_id=comp_id, year__gte=2025).order_by('-year').first()
        else:
            default_season = Season.objects.all().order_by('-year').first()
            
        if default_season:
            season_id = default_season.id

    # 2. Extraction et calcul des scores
    if season_id or comp_id:
        scores_query = SeasonScore.objects.all()
        if comp_id:
            scores_query = scores_query.filter(competition_id=comp_id)
        if season_id:
            scores_query = scores_query.filter(season_id=season_id)
            
        scores = scores_query.select_related('user')
        
        # Si la requÃªte est vide ou ne donne rien, fallback de secours sur la compÃ©tition globale
        if not scores.exists() and comp_id:
            scores = SeasonScore.objects.filter(competition_id=comp_id).select_related('user')
        
        res = CompetitionResult.objects.filter(season_id=season_id).first()
        if not res and comp_id:
            res = CompetitionResult.objects.filter(season__competition_id=comp_id).first()

        # PrÃ©-chargement des bonus prÃ©dictions en une requÃªte
        bonus_preds_qs = CompetitionBonusPrediction.objects.select_related('player__user')
        if season_id:
            bonus_preds_qs = bonus_preds_qs.filter(season_id=season_id)
        elif comp_id:
            bonus_preds_qs = bonus_preds_qs.filter(competition_id=comp_id)
        bonus_by_user = {bp.player.user_id: bp for bp in bonus_preds_qs}
        
        for s in scores:
            m_pts = s.match_points if s.match_points is not None else 0
            f_pts = s.ranking_points if s.ranking_points is not None else 0
            p_pts = s.podium_points if s.podium_points is not None else 0
                
            t_pts = m_pts + f_pts + p_pts

            # --- LOGIQUE DES BADGES BONUS ---
            has_winner = False
            has_scorer = False
            has_realisateur = False

            bonus_pred = bonus_by_user.get(s.user.id)
            
            if bonus_pred and res:
                if bonus_pred.winner == res.real_winner and res.real_winner is not None:
                    has_winner = True
                
                if bonus_pred.best_try_scorer and res.real_best_try_scorer:
                    if bonus_pred.best_try_scorer.strip().lower() == res.real_best_try_scorer.strip().lower():
                        has_scorer = True

                if bonus_pred.best_point_scorer and res.real_best_point_scorer:
                    if bonus_pred.best_point_scorer.strip().lower() == res.real_best_point_scorer.strip().lower():
                        has_realisateur = True

            user_data = {
                'username': s.user.username,
                'match_pts': m_pts,
                'ranking_pts': f_pts,
                'podium_pts': p_pts, 
                'total_global': t_pts, 
                'has_winner': has_winner,
                'has_scorer': has_scorer, 
                'has_realisateur': has_realisateur,
            }
            detailed_ranking.append(user_data)
            
            flair_ranking.append({
                'username': s.user.username,
                'ranking_pts': f_pts
            })
        
        detailed_ranking.sort(key=lambda x: (x['total_global'], x['match_pts']), reverse=True)
        flair_ranking.sort(key=lambda x: x['ranking_pts'], reverse=True)
        
    # --- 3. FILTRAGE DES SAISONS POUR LE FORMULAIRE ---
    seasons = Season.objects.all().order_by('-year')
    if comp_id:
        seasons = seasons.filter(competition_id=comp_id)

    selected_competition = Competition.objects.filter(id=comp_id).first() if comp_id else None
    selected_season_obj = Season.objects.filter(id=season_id).first() if season_id else None

    # --- 4. CONTEXTE GLOBAL ---
    context = {
        'matrix': matrix,
        'row_totals': row_totals,
        'col_totals': col_totals,
        'range_h': range(0, max_h + 1),
        'range_a': range(0, max_a + 1),
        'max_occurence': max_occurence,
        
        'competitions': Competition.objects.all(),
        'seasons': seasons,
        'competition': selected_competition, 
        'selected_season': selected_season_obj,
        'selected_comp': int(comp_id) if comp_id else None,

        'detailed_ranking': detailed_ranking,
        'flair_ranking': flair_ranking,
        
        'kpi': {'tout_pile': 0, 'demi_tout_pile': 0, 'bon_bonus_off': 0, 'mauvais_bonus_off': 0, 'bon_bonus_def': 0, 'mauvais_bonus_def': 0},
        'choppes_or': [], 'chopes_cumulees': [], 'cuilleres_bois': [], 'victory_table': [],
        'labels': [], 'score_series': {}, 'rank_series': {},
    }
    
    return render(request, 'scores_statistics.html', context)


from django.http import HttpResponse
from django.conf import settings
from core.services.email_service import send_round_reminders
from core.services.scores_importer import import_scores


def cron_send_reminders(request, token):
    expected = settings.CRON_TOKEN
    if token != expected:
        return HttpResponse("Invalid token", status=403)
    send_round_reminders()
    return HttpResponse("OK")


def import_scores_view(request, token):
    expected = settings.CRON_TOKEN
    if token != expected:
        return HttpResponse("Invalid token", status=403)
    from core.models import Season
    from django.core.mail import send_mail
    seasons = Season.objects.filter(competition__name__in=["Top 14", "Champions Cup", "6 Nations"], year__gte=2025)
    if not seasons.exists():
        return HttpResponse("No seasons found", status=404)
    all_results = []
    total_created = 0
    total_updated = 0
    for season in seasons:
        result = import_scores(season, dry_run=False, quick=True)
        all_results.append(result)
        total_created += result.get('created', 0)
        total_updated += result.get('updated', 0)
    if total_created > 0 or total_updated > 0:
        msg_lines = ["NouveautÃ©s importÃ©es depuis TheSportsDB :"]
        for r in all_results:
            c = r.get('created', 0)
            u = r.get('updated', 0)
            if c or u:
                msg_lines.append(f"- {r['competition']}: {c} crÃ©Ã©s, {u} mis Ã  jour")
        try:
            send_mail(
                "[Prono Rugby] Nouveaux matchs importÃ©s",
                "\n".join(msg_lines),
                settings.DEFAULT_FROM_EMAIL,
                [settings.EMAIL_HOST_USER],
                fail_silently=True,
            )
        except Exception:
            pass
    return JsonResponse({"imports": all_results})


def bareme_view(request):
    return render(request, 'bareme.html', {
        'SCORING_CONFIG': SCORING_CONFIG,
        'PHASE_MULTIPLIERS': PHASE_MULTIPLIERS,
        'BONUS_SCALES': BONUS_SCALES,
        'RUGBY_SCORING': RUGBY_SCORING,
        't14': RUGBY_SCORING.get("Top 14"),
        'cc': RUGBY_SCORING.get("Champions Cup"),
        '6nations': RUGBY_SCORING.get("6 Nations"),
    })
    
def _compute_hof_entry(data, name, season_year, rank, total_players, current_year, is_active):
    n = current_year - season_year
    perf = ((total_players + 1 - rank) * 100) / total_players
    score_annee = perf * (0.9 ** n)

    if name not in data:
        data[name] = {
            'user_name': name,
            'score': 0,
            'seasons_count': 0,
            'best_rank': 999,
            'is_active': is_active,
            'history_details': []
        }

    data[name]['score'] += score_annee
    data[name]['seasons_count'] += 1
    data[name]['history_details'].append({
        'year': season_year,
        'rank': rank,
        'total': total_players,
        'perf_score': perf
    })

    if rank < data[name]['best_rank']:
        data[name]['best_rank'] = rank


def hall_of_fame_view(request):
    current_year = datetime.now().year
    data = {}

    # 1. Historique des saisons passÃ©es (SeasonHistory)
    histories = SeasonHistory.objects.all()
    for record in histories:
        _compute_hof_entry(
            data, record.display_name, record.season_year,
            record.rank, record.total_players, current_year,
            record.user is not None
        )

    # 2. Saison en cours (SeasonScore temps rÃ©el)
    now = timezone.now()
    if now.month < 8:
        start_year = current_year - 1
    else:
        start_year = current_year
    active_seasons = Season.objects.filter(year__startswith=str(start_year))
    active_ids = list(active_seasons.values_list('id', flat=True))

    if active_ids:
        ss_qs = SeasonScore.objects.filter(season_id__in=active_ids).select_related('user')
        totals = {}
        for ss in ss_qs:
            uname = ss.user.username
            totals[uname] = totals.get(uname, 0) + (ss.match_points or 0) + (ss.ranking_points or 0) + (ss.podium_points or 0)

        if totals:
            sorted_players = sorted(totals.items(), key=lambda x: -x[1])
            total_players = len(sorted_players)
            for i, (uname, _) in enumerate(sorted_players):
                _compute_hof_entry(
                    data, uname, current_year,
                    i + 1, total_players, current_year,
                    True
                )

    # Tri des dÃ©tails et classement final
    for player in data.values():
        player['history_details'].sort(key=lambda x: x['year'], reverse=True)

    ranking = sorted(data.values(), key=lambda x: x['score'], reverse=True)

    if ranking:
        max_score = ranking[0]['score']
        for entry in ranking:
            entry['relative_score'] = (entry['score'] / max_score) * 100

    return render(request, 'hall_of_fame.html', {'all_time_ranking': ranking})

@login_required
def home_view(request):
    player = request.user.player
    user = request.user
    now = timezone.now()

    # --- 0. SÃ‰LECTEUR DE SAISON (groupÃ© par annÃ©e) ---
    def get_season_key(year_str):
        if '/' in year_str:
            return year_str.split('/')[0]
        if '-' in year_str:
            return year_str.split('-')[0]
        if year_str.isdigit():
            return str(int(year_str) - 1)
        return year_str

    all_seasons = Season.objects.all().order_by("year")
    year_groups = {}
    for s in all_seasons:
        key = get_season_key(s.year)
        # Ne garder que 2025+ (2025-2026 et 2026-2027)
        if not key.isdigit() or int(key) < 2025:
            continue
        if key not in year_groups:
            year_groups[key] = {"label": f"{key}-{int(key)+1}", "season_ids": []}
        year_groups[key]["season_ids"].append(s.id)
    year_groups_list = sorted(year_groups.items(), key=lambda x: x[0], reverse=True)

    selected_year = request.GET.get("year", "").strip()
    if not selected_year or selected_year not in year_groups:
        selected_year = "2025" if "2025" in year_groups else (year_groups_list[0][0] if year_groups_list else "")

    active_seasons = Season.objects.filter(id__in=year_groups[selected_year]["season_ids"])
    round_dates = Round.objects.filter(season__in=active_seasons).aggregate(
        first=Min("date"), last=Max("date")
    )
    start_date = round_dates["first"] or now
    end_date = round_dates["last"] or now

    # --- 2. PROCHAIN MATCH ---
    next_match = Match.objects.filter(kickoff_at__gt=now).select_related('home_team', 'away_team').order_by('kickoff_at').first()

    # --- 3. STATS GÃ‰NÃ‰RALES (Classement gÃ©nÃ©ral) ---
    active_season_ids = list(active_seasons.values_list('id', flat=True))
    stats = compute_statistics(competition=None, season_ids=active_season_ids)

    # Enrichir avec les SeasonScores (flairs + podiums)
    ss_qs = SeasonScore.objects.filter(season_id__in=active_season_ids).select_related('user')
    season_scores_data = {}
    for ss in ss_qs:
        uname = ss.user.username
        if uname not in season_scores_data:
            season_scores_data[uname] = {'match_pts': 0, 'ranking_pts': 0, 'podium_pts': 0}
        season_scores_data[uname]['match_pts'] += ss.match_points or 0
        season_scores_data[uname]['ranking_pts'] += ss.ranking_points or 0
        season_scores_data[uname]['podium_pts'] += ss.podium_points or 0

    for r in stats.detailed_ranking:
        uname = r['username']
        ss = season_scores_data.get(uname, {})
        r['match_pts'] = ss.get('match_pts', 0) if ss.get('match_pts', 0) > 0 else r.get('points', 0)
        r['ranking_pts'] = ss.get('ranking_pts', 0)
        r['podium_pts'] = ss.get('podium_pts', 0)
        r['total_global'] = r['match_pts'] + r['ranking_pts'] + r['podium_pts']

    stats.detailed_ranking.sort(key=lambda x: (x['total_global'], x['match_pts']), reverse=True)

    user_row = next((row for row in stats.detailed_ranking if row['username'] == user.username), {})
    rank_general = next((i+1 for i, r in enumerate(stats.detailed_ranking) if r['username'] == user.username), "?")

    evolution = 0
    if stats.round_dates:
        seven_days_ago = (now - timedelta(days=7)).date()
        idx_7d = None
        for i, d_str in enumerate(stats.round_dates):
            try:
                rdate = datetime.strptime(d_str[:10], "%Y-%m-%d").date()
                if rdate <= seven_days_ago:
                    idx_7d = i
            except (ValueError, IndexError):
                continue
        if idx_7d is not None:
            # Classement enrichi Ã  J-7 (matches + flairs + podiums)
            enriched_past = {}
            for uname in stats.score_series:
                match_pts = stats.score_series[uname][idx_7d]
                ss = season_scores_data.get(uname, {})
                total = match_pts + ss.get('ranking_pts', 0) + ss.get('podium_pts', 0)
                enriched_past[uname] = total
            past_ranking = sorted(enriched_past.items(), key=lambda x: -x[1])
            past_rank = next((i+1 for i, (n, _) in enumerate(past_ranking) if n == user.username), None)
            if past_rank is not None:
                evolution = past_rank - rank_general
        elif len(stats.rank_series.get(user.username, [])) >= 2:
            evolution = stats.rank_series[user.username][-2] - rank_general

    # --- 4. HALL OF FAME ---
    hof_data = {}

    # 4a. Historique des saisons passÃ©es
    for record in SeasonHistory.objects.all():
        name_db = record.display_name.strip()
        n = now.year - record.season_year
        perf = ((record.total_players + 1 - record.rank) * 100) / record.total_players
        score_annee = perf * (0.9 ** n)
        hof_data[name_db] = hof_data.get(name_db, 0) + score_annee

    # 4b. Saison en cours (SeasonScore temps rÃ©el)
    if active_season_ids:
        ss_qs = SeasonScore.objects.filter(season_id__in=active_season_ids).select_related('user')
        totals = {}
        for ss in ss_qs:
            uname = ss.user.username
            totals[uname] = totals.get(uname, 0) + (ss.match_points or 0) + (ss.ranking_points or 0) + (ss.podium_points or 0)
        if totals:
            sorted_players = sorted(totals.items(), key=lambda x: -x[1])
            total_active = len(sorted_players)
            for i, (uname, _) in enumerate(sorted_players):
                perf = ((total_active + 1 - (i + 1)) * 100) / total_active
                hof_data[uname] = hof_data.get(uname, 0) + perf

    hof_ranking = sorted(hof_data.items(), key=lambda x: x[1], reverse=True)
    target_names = [user.username.lower(), player.name.lower()]
    hof_rank = next((i + 1 for i, (name, _) in enumerate(hof_ranking) if name.lower().strip() in target_names), "?")

    # --- 5. TROPHÃ‰ES ET RANGS ---
    all_users = User.objects.filter(player__isnull=False).distinct()
    user_ids_list = list(all_users.values_list('id', flat=True))
    user_counts = {u.id: {'chopes': 0, 'cuilleres': 0, 'perfects': 0, 'demis': 0} for u in all_users}

    # Toutes les prÃ©dictions de la pÃ©riode en UNE requÃªte
    all_preds = Prediction.objects.filter(
        match__kickoff_at__range=(start_date, now),
        match__home_score__isnull=False
    ).select_related('player__user', 'match')
    all_preds_list = list(all_preds)

    # Index par user_id
    preds_by_user = {uid: [] for uid in user_ids_list}
    for pr in all_preds_list:
        if pr.player.user_id in preds_by_user:
            preds_by_user[pr.player.user_id].append(pr)

    for u in all_users:
        for p in preds_by_user.get(u.id, []):
            m = p.match
            if p.home_score_pred == m.home_score and p.away_score_pred == m.away_score:
                user_counts[u.id]['perfects'] += 1
            elif p.home_score_pred == m.home_score or p.away_score_pred == m.away_score:
                user_counts[u.id]['demis'] += 1

    # Tous les DailyScores de la pÃ©riode en UNE requÃªte
    all_ds = DailyScore.objects.filter(
        round__date__range=(start_date, end_date)
    ).select_related('user', 'round__season__competition').order_by('round_id', '-points')
    ds_by_round = {}
    for ds in all_ds:
        ds_by_round.setdefault(ds.round_id, []).append(ds)

    relevant_rounds = Round.objects.filter(date__range=(start_date, end_date))
    debug_log = []
    current_user_preds = preds_by_user.get(user.id, [])
    current_user_preds_by_round = {}
    for p in current_user_preds:
        current_user_preds_by_round.setdefault(p.match.round_id, []).append(p)

    for r in relevant_rounds:
        day_scores = ds_by_round.get(r.id, [])
        if not day_scores:
            continue
        max_p, min_p = day_scores[0].points, day_scores[-1].points
        s_bo_p, s_bo_ok, s_bd_p, s_bd_ok = 0, 0, 0, 0

        prev_points = None
        rank = 0
        for idx, ds in enumerate(day_scores):
            if ds.points != prev_points:
                rank = idx + 1
                prev_points = ds.points
            if ds.points > 0:
                if rank == 1:
                    user_counts[ds.user.id]['chopes'] += 3
                elif rank == 2:
                    user_counts[ds.user.id]['chopes'] += 2
                elif rank == 3:
                    user_counts[ds.user.id]['chopes'] += 1
            if len(day_scores) >= 3 and ds.points == min_p and min_p < max_p:
                user_counts[ds.user.id]['cuilleres'] += 1

        if ds_by_round.get(r.id):
            for p in current_user_preds_by_round.get(r.id, []):
                if p.match.phase == "POOL":
                    if p.bonus_home_pred or p.bonus_away_pred:
                        s_bo_p += 1
                        if (p.bonus_home_pred and p.match.bonus_offense_home) or (p.bonus_away_pred and p.match.bonus_offense_away):
                            s_bo_ok += 1
                    threshold = r.season.competition.bonus_defense_threshold
                    if 1 <= abs(p.home_score_pred - p.away_score_pred) <= threshold:
                        s_bd_p += 1
                        if p.match.get_defense_bonus() is not None:
                            s_bd_ok += 1

        if s_bo_p > 0 or s_bd_p > 0:
            debug_log.append(f"ðŸ“… {str(r)} : BO {s_bo_ok}/{s_bo_p} | BD {s_bd_ok}/{s_bd_p}")

    my_stats = user_counts.get(user.id)
    rank_chopes = sum(1 for v in user_counts.values() if v['chopes'] > my_stats['chopes']) + 1
    rank_cuilleres = sum(1 for v in user_counts.values() if v['cuilleres'] > my_stats['cuilleres']) + 1
    rank_perfects = sum(1 for v in user_counts.values() if v['perfects'] > my_stats['perfects']) + 1
    rank_demis = sum(1 for v in user_counts.values() if v['demis'] > my_stats['demis']) + 1

    # --- 6. ANALYSE PAR COMPÃ‰TITION ---
    all_past_matches = Match.objects.filter(kickoff_at__range=(start_date, now))
    preds_done = Prediction.objects.filter(
        player=player, match__in=all_past_matches
    ).select_related('match__round__season__competition')
    preds_done_list = list(preds_done)
    
    global_bo_prono, global_bo_ok = 0, 0
    global_bd_prono, global_bd_ok = 0, 0

    comp_analysis = []
    for season in active_seasons:
        s_preds = [p for p in preds_done_list if p.match.round.season_id == season.id and p.match.home_score is not None]
        if not s_preds:
            continue

        s_bo_p, s_bo_ok, s_bd_p, s_bd_ok, s_bons = 0, 0, 0, 0, 0
        for p in s_preds:
            m = p.match
            rh, ra = m.home_score, m.away_score
            ph, pa = p.home_score_pred, p.away_score_pred
            if (ph > pa and rh > ra) or (ph < pa and rh < ra) or (ph == pa and rh == ra):
                s_bons += 1
            if m.phase == "POOL":
                if p.bonus_home_pred or p.bonus_away_pred:
                    s_bo_p += 1
                    if (p.bonus_home_pred and m.bonus_offense_home) or (p.bonus_away_pred and m.bonus_offense_away):
                        s_bo_ok += 1
                threshold = season.competition.bonus_defense_threshold
                if 1 <= abs(ph - pa) <= threshold:
                    s_bd_p += 1
                    if m.get_defense_bonus() is not None:
                        s_bd_ok += 1

        global_bo_prono += s_bo_p; global_bo_ok += s_bo_ok
        global_bd_prono += s_bd_p; global_bd_ok += s_bd_ok

        u_sscore = SeasonScore.objects.filter(user=user, season=season).first()
        match_pts = DailyScore.objects.filter(user=user, round__season=season).aggregate(Sum('points'))['points__sum'] or 0
        total_pts = match_pts + (u_sscore.ranking_points if u_sscore else 0)
        
        leaderboard = DailyScore.objects.filter(round__season=season).values('user').annotate(total_m=Sum('points'))
        s_rank = 1
        for entry in leaderboard:
            adv_flair = SeasonScore.objects.filter(user_id=entry['user'], season=season).values_list('ranking_points', flat=True).first() or 0
            if (entry['total_m'] + adv_flair) > total_pts:
                s_rank += 1

        comp_analysis.append({
            'name': season.competition.name, 'bons': s_bons, 'total': len(s_preds),
            'ratio': round((s_bons / len(s_preds) * 100), 1) if s_preds else 0,
            'rank': s_rank, 'pts': total_pts, 'bo': f"{s_bo_ok}/{s_bo_p}", 'bd': f"{s_bd_ok}/{s_bd_p}"
        })

    # --- 7. DÃ‰TECTION NO-SHOW ---
    pred_match_ids = {p.match_id for p in preds_done_list}
    no_show_list = []
    for m in all_past_matches:
        if m.id not in pred_match_ids:
            no_show_list.append(m)
            debug_log.append(f"âŒ NO-SHOW : {m.home_team} vs {m.away_team} ({m.kickoff_at.strftime('%d/%m %H:%M')})")

    context = {
        'year_groups': year_groups_list,
        'selected_year': selected_year,
        'rank_general': rank_general, 'total_players': len(user_ids_list),
        'evolution': evolution,
        'hof_rank': hof_rank, 'total_points_all': user_row.get('total_global', 0),
        'perfects': my_stats['perfects'], 'rank_perfects': rank_perfects,
        'chopes_count': my_stats['chopes'], 'rank_chopes': rank_chopes,
        'cuilleres_count': my_stats['cuilleres'], 'rank_cuilleres': rank_cuilleres,
        'global_demi': my_stats['demis'], 'rank_demis': rank_demis,
        'comp_analysis': sorted(comp_analysis, key=lambda x: x['pts'], reverse=True),
        'global_bons': sum(c['bons'] for c in comp_analysis), 
        'global_total': sum(c['total'] for c in comp_analysis),
        'global_ratio': round((sum(c['bons'] for c in comp_analysis) / sum(c['total'] for c in comp_analysis) * 100), 1) if sum(c['total'] for c in comp_analysis) > 0 else 0,
        'bonus_off_ok': global_bo_ok, 'bonus_off_prono': global_bo_prono,
        'bonus_def_ok': global_bd_ok, 'bonus_def_prono': global_bd_prono,
        'no_show': len(no_show_list), # On utilise la longueur de notre nouvelle liste
        'next_match': next_match, 'debug_log': debug_log
    }
    return render(request, 'home.html', context)
