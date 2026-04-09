from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout, update_session_auth_hash
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import F, Prefetch, Sum, Count, Max, Q
from django.contrib.admin.views.decorators import staff_member_required
from datetime import datetime

# Modèles conservés
from .models import (
    Competition, Season, Round, Match, Team, Player, 
    Prediction, DailyScore, SeasonScore, CompetitionResult,
    CompetitionTeam, CompetitionTeamPrediction, CompetitionBonusPrediction, SeasonHistory
)

# Services
from .services import scoring
from .services.scoring import PHASE_MULTIPLIERS, SCORING_CONFIG, RUGBY_SCORING, process_round_scores, get_winner_side, calculate_match_points, BONUS_SCALES
from .services.statistics import compute_statistics

# CONFIGURATION DU BAREME DES POINTS


# ------------------
# PRONOS VIEW
# ------------------
@login_required
def pronos_view(request):
    user = request.user
    try:
        player = user.player
    except Player.DoesNotExist:
        messages.error(request, "Votre compte n’est pas encore lié à un joueur.")
        return redirect("logout")

    # 1. RÉCUPÉRATION DES PARAMÈTRES
    competition_id = request.GET.get("competition")
    season_id = request.GET.get("season")
    round_id = request.GET.get("round")
    now = timezone.now()

    # 2. LOGIQUE DES MENUS DÉROULANTS
    competitions = Competition.objects.all().order_by('name')
    
    # Choix de la compétition
    if competition_id:
        selected_comp = competitions.filter(id=competition_id).first()
    else:
        # Par défaut : compétition du prochain round à venir
        next_r = Round.objects.filter(date__gte=now.date()).order_by("date").first()
        selected_comp = next_r.season.competition if next_r else competitions.first()

    # Choix de la saison
    seasons = Season.objects.filter(competition=selected_comp,year__gte=2025).order_by('-year')
    if season_id:
        selected_season = seasons.filter(id=season_id).first()
    else:
        selected_season = seasons.first()

    # Choix du round
    rounds = Round.objects.filter(season=selected_season).order_by('number')
    if not round_id:
        # On cherche le prochain round de CETTE saison
        current_r_obj = rounds.filter(date__gte=now.date()).order_by("date").first()
        if not current_r_obj:
            current_r_obj = rounds.last()
        round_id = str(current_r_obj.id) if current_r_obj else None
    else:
        current_r_obj = rounds.filter(id=round_id).first()

    # 3. GESTION DU POST (SAUVEGARDE)
    # On garde ta logique de sauvegarde très robuste, elle est parfaite.
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

        messages.success(request, "Pronostics enregistrés !")
        return redirect(f"{request.path}?competition={selected_comp.id}&season={selected_season.id}&round={round_id}")

    # 4. PRÉPARATION AFFICHAGE
    matches = Match.objects.filter(round_id=round_id).select_related("home_team", "away_team").order_by("kickoff_at")
    predictions_by_match = {p.match_id: p for p in Prediction.objects.filter(player=player, match__round_id=round_id)}

    submit_disabled = True
    for match in matches:
        match.user_prediction = predictions_by_match.get(match.id)
        if not match.is_locked: submit_disabled = False

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
    })
# ... reste de tes vues (logout, settings, etc.) inchangé ...

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
        form = PasswordChangeForm(user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # garder la session ouverte
            messages.success(request, 'Mot de passe mis à jour !')
            return redirect('settings')
        else:
            messages.error(request, 'Corrigez les erreurs ci-dessous.')
    else:
        form = PasswordChangeForm(user)

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
        
        # On récupère la saison la plus récente pour cette compétition
        selected_season = Season.objects.filter(competition=selected_competition).order_by('-year').first()
        
        if selected_season:
            # On récupère les pronos de classement liés au joueur ET à la saison
            rankings = CompetitionTeamPrediction.objects.filter(
                player__user=request.user, # On filtre par l'utilisateur connecté
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
    competitions = Competition.objects.all()
    # On unifie la récupération de l'ID de compétition (POST ou GET)
    competition_id = request.POST.get("competition_id") or request.GET.get("competition")

    selected_competition = None
    blocks = []
    bonus = None
    winner_teams = []
    season = None

    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
        # On définit la saison immédiatement
        season = Season.objects.filter(competition=selected_competition).order_by("-year").first()
        
        # Récupération des bonus
        bonus, _ = CompetitionBonusPrediction.objects.get_or_create(
            player=request.user.player,
            competition=selected_competition
        )
        
        winner_teams = selected_competition.teams.all().order_by("name")

        # --- On prépare les BLOCKS ici pour qu'ils existent en GET ET en POST ---
        if selected_competition.name.lower() == "champions cup":
            for pool in range(1, 5):
                comp_teams = CompetitionTeam.objects.filter(
                    competition=selected_competition, season=season, pool=pool
                ).select_related("team")
                blocks.append({
                    "key": f"pool{pool}",
                    "teams": [ct.team for ct in comp_teams],
                    "positions": list(range(1, 7)),
                    "pool": pool
                })
        else:
            teams = selected_competition.teams.all().order_by("name")
            blocks.append({
                "key": "all",
                "teams": teams,
                "positions": list(range(1, teams.count() + 1)),
                "pool": None
            })

    # --- SAUVEGARDE (POST) ---
    if request.method == "POST" and selected_competition:
        
        # VERROU : On vérifie si la compétition a commencé
        if season and season.has_started:
            messages.error(request, "La compétition a déjà commencé ! Modification impossible.")
            return redirect(f"{request.path}?competition={selected_competition.id}")
        
        # 1. Sauvegarde des Bonus
        bonus.best_try_scorer = request.POST.get("best_try_scorer", "").strip()
        bonus.best_point_scorer = request.POST.get("best_point_scorer", "").strip()
        winner_id = request.POST.get("winner")
        bonus.winner_id = int(winner_id) if winner_id and winner_id.isdigit() else None
        bonus.save()

        # 2. Nettoyage et 3. Enregistrement
        CompetitionTeamPrediction.objects.filter(
            competition=selected_competition, player=request.user.player
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
        
        messages.success(request, "Vos pronostics ont été enregistrés !")
        return redirect(f"{request.path}?competition={selected_competition.id}")

    # --- RÉCUPÉRATION POUR AFFICHAGE (GET) ---
    if selected_competition:
        for block in blocks:
            saved_preds = CompetitionTeamPrediction.objects.filter(
                competition=selected_competition,
                player=request.user.player,
                block_key=block["key"]
            )
            # CRUCIAL : On s'assure que la clé est un entier (pos) 
            # et la valeur est un entier (ID de l'équipe)
            block["saved"] = {int(p.position): int(p.team.id) for p in saved_preds}
            
    # Récupération propre pour l'affichage du récapitulatif
    last_saved_ranking = []
    if selected_competition:
        last_saved_ranking = CompetitionTeamPrediction.objects.filter(
            competition=selected_competition,
            player=request.user.player
        ).select_related('team').order_by('block_key', 'position')

    return render(request, "pronos/classement.html", {
        "season": season,
        "competitions": competitions,
        "selected_competition": selected_competition,
        "blocks": blocks,
        "bonus": bonus,
        "winner_teams": winner_teams,
        "last_saved_ranking": last_saved_ranking,
    })

def all_pronos_view(request):
    now = timezone.now()
    is_admin = request.user.is_staff or request.user.is_superuser
    
    # 1. Récupération des IDs
    comp_id = request.GET.get("comp")
    season_id = request.GET.get("season")
    round_id = request.GET.get("round")

    all_competitions = Competition.objects.all().order_by('name')
    
    # 2. Détermination de la compétition
    if comp_id:
        selected_comp = all_competitions.filter(id=comp_id).first()
    else:
        # Automatisme par défaut au premier chargement
        near_round = Round.objects.filter(date__gte=now.date()).order_by("date").first()
        selected_comp = near_round.season.competition if near_round else all_competitions.first()

    # 3. Détermination de la saison (FILTRÉE par la compétition choisie)
    seasons = Season.objects.filter(competition=selected_comp, year__gte=2025).order_by('-year')
    
    if season_id and seasons.filter(id=season_id).exists():
        selected_season = seasons.filter(id=season_id).first()
    else:
        # Si on change de comp, season_id devient invalide, on prend la plus récente de la nouvelle comp
        selected_season = seasons.first()

    # 4. Détermination des journées (FILTRÉES par la saison choisie)
    rounds = Round.objects.filter(season=selected_season).order_by('number')

    # 5. Détermination du Round final à afficher
    # 5. DÉTERMINATION DU ROUND FINAL À AFFICHER
    # On initialise à None
    current_round_obj = None

    # PRIORITÉ 1 : L'utilisateur a choisi un round manuellement
    if round_id and round_id.isdigit():
        current_round_obj = rounds.filter(id=round_id).first()

    # PRIORITÉ 2 : Si aucun round choisi (ou ID invalide), on lance l'automatisme
    if not current_round_obj:
        # On cherche le round le plus proche de maintenant dans la saison sélectionnée
        current_round_obj = rounds.filter(date__gte=now.date()).order_by("date").first()
        
        # PRIORITÉ 3 : Si tous les rounds sont passés, on prend le dernier
        if not current_round_obj:
            current_round_obj = rounds.last()

    # ... (Le reste de ton code pour les matches et les lignes reste identique)

    rows = []
    players = Player.objects.all().select_related('user').order_by('user__username')

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
                
                # Init du dictionnaire de données pour le template
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
                        
                        # 3. Bonus Défensifs (BD) - Logique Auto
                        # Home prédit BD
                        if prono.home_score_pred < prono.away_score_pred and (prono.away_score_pred - prono.home_score_pred) <= threshold:
                            if real_bd == 'HOME' or m.home_score == m.away_score: p_dict['bd_home_ok'] = True
                            else: p_dict['bd_home_ko'] = True
                        # Away prédit BD
                        if prono.away_score_pred < prono.home_score_pred and (prono.home_score_pred - prono.away_score_pred) <= threshold:
                            if real_bd == 'AWAY' or m.home_score == m.away_score: p_dict['bd_away_ok'] = True
                            else: p_dict['bd_away_ko'] = True
                    else:
                        # Match non joué : Orange si un bonus est "dans les tuyaux"
                        if prono.bonus_home_pred or (prono.home_score_pred < prono.away_score_pred and (prono.away_score_pred - prono.home_score_pred) <= threshold):
                            p_dict['pending_home'] = True
                        if prono.bonus_away_pred or (prono.away_score_pred < prono.home_score_pred and (prono.home_score_pred - prono.away_score_pred) <= threshold):
                            p_dict['pending_away'] = True

                    # Background couleur selon vainqueur prédit
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

    return render(request, "pronos/all_pronos.html", {
        "rows": rows, "players": players, "competitions": all_competitions,
        "seasons": seasons, "rounds": rounds, "selected_comp": selected_comp,
        "selected_season": selected_season, "current_round_obj": current_round_obj,
    })  

def round_results_board(request, round_id):
    # 1. Récupération de l'objet et gestion des changements via GET
    round_obj = get_object_or_404(Round, id=round_id)
    
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

    # 2. Préparation des données de base
    selected_comp = round_obj.season.competition
    selected_season = round_obj.season
    
    seasons = Season.objects.filter(competition=selected_comp, year__gte=2025).order_by('-year')
    rounds = Round.objects.filter(season=selected_season).order_by('number')
    players = Player.objects.all().order_by('name')
    matches = Match.objects.filter(round=round_obj).order_by('kickoff_at')
    all_competitions = Competition.objects.prefetch_related(
        Prefetch('seasons', queryset=Season.objects.all().order_by('-year'))
    ).distinct()

    # 3. Configuration du Barème et des Multiplicateurs
    comp_name = round_obj.season.competition.name
    current_scale = scoring.BONUS_SCALES.get(comp_name, {})
    
    # Multiplicateur de compétition (ex: 6 Nations)
    comp_multiplier = 2 if ("6 Nations" in comp_name or "Six Nations" in comp_name) else 1
    
    # Multiplicateur de phase (ex: POOL=1, R16=1.25, QF=1.5...)
    phase_multiplier = scoring.PHASE_MULTIPLIERS.get(round_obj.phase, 1.0)
    
    # Sécurité pour les bonus BO/BD (Uniquement en POOL)
    is_pool_phase = (round_obj.phase == "POOL")

    # 4. Pré-calcul des gagnants par match (Partage du pool)
    match_winners_counts = {}
    for m in matches:
        if m.home_score is not None and m.away_score is not None:
            real_side = get_winner_side(m.home_score, m.away_score)
            winners_count = Prediction.objects.filter(
                match=m
            ).extra(where=[
                "(home_score_pred > away_score_pred AND %s = 'HOME') OR "
                "(away_score_pred > home_score_pred AND %s = 'AWAY') OR "
                "(home_score_pred = away_score_pred AND %s = 'DRAW')"
            ], params=[real_side, real_side, real_side]).count()
            match_winners_counts[m.id] = winners_count
        else:
            match_winners_counts[m.id] = 0

    # 5. Construction de la matrice des points (Points bruts stockés)
    matrix = {}
    for m in matches:
        matrix[m.id] = {}
        for p in players:
            pred = Prediction.objects.filter(match=m, player=p).first()
            matrix[m.id][p.id] = pred.points if (pred and pred.points is not None) else 0

    # 6. Calcul des totaux et stats par joueur
    totals_display = []
    for p in players:
        player_preds = Prediction.objects.filter(match__round=round_obj, player=p)
        stats = {
            'pm': 0, 'winners': 0, 'bo': 0, 'bd': 0, 'diff': 0, 
            'somme': 0, 'ext': 0, 'dtp': 0, 'draw': 0, 'tp': 0
        }

        for pr in player_preds:
            m = pr.match
            match_threshold = m.round.season.competition.bonus_defense_threshold
            if m.home_score is None or m.away_score is None: continue
            
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
                # Bonus Offensif
                if pr.bonus_home_pred:
                    stats['bo'] += scoring.SCORING_CONFIG['OFFENSIVE_BONUS_VALUE'] if m.bonus_offense_home else scoring.SCORING_CONFIG['BONUS_MALUS']
                if pr.bonus_away_pred:
                    stats['bo'] += scoring.SCORING_CONFIG['OFFENSIVE_BONUS_VALUE'] if m.bonus_offense_away else scoring.SCORING_CONFIG['BONUS_MALUS']
                
                # Bonus Défensif
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

            # --- Extérieur et Nul ---
            real_winner_obj = m.winner()
            if real_winner_obj == m.away_team and pr.away_score_pred > pr.home_score_pred:
                stats['ext'] += scoring.SCORING_CONFIG['AWAY_WIN_BONUS']
            if real_winner_obj == "DRAW" and pr.home_score_pred == pr.away_score_pred and pred_winner_side != "NO SHOW":
                stats['draw'] += scoring.SCORING_CONFIG['DRAW_BONUS']

        # Bonus de Palier (basé sur le nombre de gagnants trouvés)
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

    # 7. Attribution des médailles
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

    context = {
        'round': round_obj,
        'players': players,
        'matches': matches,
        'matrix': matrix,
        'totals': totals_display,
        'all_competitions': all_competitions,
        'seasons': seasons,
        'rounds': rounds,
        'selected_comp': selected_comp,
        'selected_season': selected_season,
    }
    return render(request, 'round_board.html', context)

def compute_round_view(request, round_id):
    round_obj = get_object_or_404(Round, id=round_id)
    # On appelle ton script de scoring
    process_round_scores(round_obj)
    # Une fois fini, on revient sur la page des résultats
    return redirect('round_board', round_id=round_id)

@login_required
def statistiques_view(request):
    competition_id = request.GET.get("competition", "").strip()
    season_id = request.GET.get("season", "").strip()
    
    competitions = Competition.objects.all().order_by("name")

    # 1. Gestion de la Compétition
    competition = None
    if competition_id and competition_id.isdigit():
        competition = Competition.objects.filter(id=int(competition_id)).first()

    # 2. Gestion des Saisons
    # Si competition est None, on montre TOUTES les saisons >= 2025 de TOUTES les compétitions
    seasons = Season.objects.filter(year__gte=2025)
    if competition:
        seasons = seasons.filter(competition=competition)
    seasons = seasons.order_by("-year", "competition__name")

    # 3. Sélection de la saison
    selected_season = None
    if season_id.isdigit():
        selected_season = seasons.filter(id=int(season_id)).first()
    
    # --- LA CORRECTION EST ICI ---
    # Si on est en mode "Toutes les compétitions", on ne veut PAS forcément 
    # forcer selected_season sur la première venue, sinon on filtre par cette saison.
    # On ne force un selected_season que si une compétition est choisie.
    if not selected_season and competition:
        selected_season = seasons.first()

    # 4. Calcul des stats
    # On passe competition (qui peut être None) et selected_season (qui peut être None)
    stats = compute_statistics(competition, season=selected_season)

    # --- SÉCURISATION DU CRASH SeasonScore ---
    season_scores = {}
    try:
        # Si selected_season est None, on agrège les points de toutes les saisons
        qs = SeasonScore.objects.all()
        if selected_season:
            qs = qs.filter(season=selected_season)
        
        # On somme les points par utilisateur si on est en mode global
        user_points = qs.values('user__username').annotate(total_ranking=Sum('ranking_points'))
        season_scores = {item['user__username']: item['total_ranking'] for item in user_points}
    except Exception:
        season_scores = {}

    # ... (Le reste de ta logique de calcul de ranking reste identique) ...
    for r in stats.detailed_ranking:
        r['match_pts'] = r.get('points', 0)
        r['ranking_pts'] = season_scores.get(r['username'], 0)
        r['total_global'] = r['match_pts'] + r['ranking_pts']

    stats.detailed_ranking.sort(key=lambda x: x['total_global'], reverse=True)
    
    # On cherche la dernière journée pour le bouton
    last_round_id = None
    if selected_season:
        lr = Round.objects.filter(season=selected_season).order_by('-number').first()
        if lr: last_round_id = lr.id

    context = {
        "competitions": competitions,
        "competition": competition,
        "seasons": seasons,
        "selected_season": selected_season,
        "kpi": stats.kpi,
        "labels": stats.labels,
        "score_series": stats.score_series,
        "rank_series": stats.rank_series,
        "detailed_ranking": stats.detailed_ranking,
        "choppes_or": stats.choppes_or,
        "chopes_cumulees": stats.chopes_cumulees,
        "cuilleres_bois": stats.cuilleres_bois,
        "flair_ranking": sorted(stats.detailed_ranking, key=lambda x: x.get('ranking_pts', 0), reverse=True),
        "victory_table": getattr(stats, 'victory_table', []),
        "last_round_id": last_round_id,
        "pie_labels": stats.pie_labels, # Assure-toi que ces noms correspondent
        "pie_values": stats.pie_values,
    }

    return render(request, "statistiques.html", context)

@login_required
def debug_scores_view(request):
    # 1. Récupérer toutes les compétitions pour le premier menu
    competitions = Competition.objects.all().order_by('name')
    
    # 2. Récupérer la compétition sélectionnée
    competition_id = request.GET.get('competition')
    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
    else:
        selected_competition = competitions.first()

    if not selected_competition:
        return render(request, "debug_scores.html", {"error": "Aucune compétition trouvée"})

    # 3. Récupérer les SAISONS de cette compétition pour le deuxième menu
    seasons = Season.objects.filter(competition=selected_competition).order_by('-year')
    
    # 4. Récupérer la saison sélectionnée (ou la dernière par défaut)
    season_id = request.GET.get('season')
    if season_id:
        selected_season = get_object_or_404(Season, id=season_id)
    else:
        selected_season = seasons.first()

    # 5. Filtrer les Rounds UNIQUEMENT pour cette saison
    rounds = Round.objects.filter(season=selected_season).order_by('number')
    players = Player.objects.filter(user__isnull=False).order_by('name')
    
    # 6. Matrice de scores (ton code reste le même, mais filtré par rounds de la saison)
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
    
    # Initialisation systématique pour éviter les erreurs dans le template
    selected_competition = None
    real_rankings = {}
    real_winner = None
    result_obj = None
    players = Player.objects.all().order_by('name')
    matrix = {} 
    teams_by_block = {}
    bonus_preds = []

    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
        
        # On récupère la saison MAINTENANT que selected_competition est défini
        season = Season.objects.filter(competition=selected_competition).order_by("-year").first()
        
        if season:
            # Vérification du verrouillage
            if not season.has_started and not request.user.is_staff:
                messages.warning(request, "Les pronostics des autres joueurs seront visibles dès le coup d'envoi !")
                return redirect('pronos')
            
            # Récupération des résultats réels (SORTI DU ELSE, il doit être ici !)
            result_obj = CompetitionResult.objects.filter(season=season).first()
            if result_obj:
                real_rankings = result_obj.rankings_json
                real_winner = result_obj.real_winner

        # Récupération des pronostics des joueurs
        preds = CompetitionTeamPrediction.objects.filter(competition=selected_competition).select_related('player', 'team')
        
        for p in preds:
            if p.block_key not in matrix:
                matrix[p.block_key] = {}
                teams_by_block[p.block_key] = []
            
            if p.team not in teams_by_block[p.block_key]:
                teams_by_block[p.block_key].append(p.team)
                
            if p.team.id not in matrix[p.block_key]:
                matrix[p.block_key][p.team.id] = {}
            
            matrix[p.block_key][p.team.id][p.player.id] = p.position

        bonus_preds = CompetitionBonusPrediction.objects.filter(competition=selected_competition).select_related('player', 'winner')

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
    })
    
    
def compute_competition_points(season):
    result = CompetitionResult.objects.filter(season=season).first()
    if not result:
        return "Aucun résultat saisi."

    rules = RUGBY_SCORING.get(season.competition.name, RUGBY_SCORING["Top 14"])
    players = Player.objects.all()
    
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
                season=season  # Crucial pour ne pas écraser 2025
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
        season = Season.objects.filter(competition=selected_competition).order_by("-year").first()
        
        # Préparation des blocs (Même logique que ta vue classement_prediction)
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
        
        # 1. Sauvegarde des bonus réels
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
        messages.success(request, "Résultats officiels enregistrés !")
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
    # On appelle la fonction de calcul définie précédemment
    message_resultat = compute_competition_points(season)
    
    if isinstance(message_resultat, str):
        messages.error(request, message_resultat)
    else:
        messages.success(request, "Les points de classement ont été mis à jour pour tous les joueurs !")
        
    return redirect('recap_classement')


def charte_view(request):
    return render(request, "pronos/charte.html")

def statistics_view(request):
    comp_id = request.GET.get('competition')
    season_id = request.GET.get('season')

    query = Match.objects.filter(home_score__isnull=False, away_score__isnull=False, phase='POOL')

    if comp_id:
        query = query.filter(round__season__competition_id=comp_id)
    if season_id:
        query = query.filter(round__season_id=season_id)

    # Agrégation des scores
    stats = query.values('home_score', 'away_score').annotate(total=Count('id'))

    matrix = {}
    row_totals = {} # Sommes par ligne (Domicile)
    col_totals = {} # Sommes par colonne (Extérieur)
    max_occurence = 0
    max_h, max_a = 0, 0

    for s in stats:
        h, a, t = s['home_score'], s['away_score'], s['total']
        
        # Remplissage matrice
        if h not in matrix: matrix[h] = {}
        matrix[h][a] = t
        
        # Calcul des totaux
        row_totals[h] = row_totals.get(h, 0) + t
        col_totals[a] = col_totals.get(a, 0) + t
        
        # Mise à jour des max pour le rendu
        if t > max_occurence: max_occurence = t
        if h > max_h: max_h = h
        if a > max_a: max_a = a

    # Filtrage des saisons selon la compétition choisie
    seasons = Season.objects.all().order_by('-year')
    if comp_id:
        seasons = seasons.filter(competition_id=comp_id)

    context = {
        'matrix': matrix,
        'row_totals': row_totals,
        'col_totals': col_totals,
        'range_h': range(0, max_h + 1), # Y : Domicile
        'range_a': range(0, max_a + 1), # X : Extérieur
        'max_occurence': max_occurence,
        'competitions': Competition.objects.all(),
        'seasons': seasons,
        'selected_comp': int(comp_id) if comp_id else None,
        'selected_season': int(season_id) if season_id else None,
    }
    return render(request, 'scores_statistics.html', context)

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
    
def get_all_time_ranking():
    current_year = datetime.now().year
    histories = SeasonHistory.objects.all()
    all_time_scores = {}

    for record in histories:
        n = current_year - record.season_year
        name = record.display_name
        is_active = record.user is not None  # True si le joueur a un compte
        # Ton algo combiné :
        # 1. Score de performance (0 à 100)
        performance = ((record.total_players + 1 - record.rank) * 100) / record.total_players
        
        # 2. Coefficient temporel (0.9^n)
        time_coeff = 0.9 ** n
        
        weighted_score = performance * time_coeff
        
        # 3. Cumul par utilisateur
        user_name = record.user.username
        all_time_scores[user_name] = all_time_scores.get(user_name, 0) + weighted_score

    # Trier par score décroissant
    return sorted(all_time_scores.items(), key=lambda x: x[1], reverse=True)

def hall_of_fame_view(request):
    current_year = datetime.now().year
    histories = SeasonHistory.objects.all()
    data = {}

    for record in histories:
        name = record.display_name
        n = current_year - record.season_year
        
        # Calcul de la performance saisonnière (sur 100)
        perf = ((record.total_players + 1 - record.rank) * 100) / record.total_players
        # Application de la dépréciation temporelle (0.9^n)
        score_annee = perf * (0.9 ** n)
        
        if name not in data:
            data[name] = {
                'user_name': name,
                'score': 0,
                'seasons_count': 0,
                'best_rank': 999,
                'is_active': record.user is not None,
                'history_details': [] 
            }
        
        data[name]['score'] += score_annee
        data[name]['seasons_count'] += 1
        
        # Ajout du détail pour la modale
        data[name]['history_details'].append({
            'year': record.season_year,
            'rank': record.rank,
            'total': record.total_players,
            'perf_score': perf
        })
        
        if record.rank < data[name]['best_rank']:
            data[name]['best_rank'] = record.rank

    # Tri des détails par année (plus récent en haut) pour chaque joueur
    for player in data.values():
        player['history_details'].sort(key=lambda x: x['year'], reverse=True)

    # Tri du classement All-Time par score décroissant
    ranking = sorted(data.values(), key=lambda x: x['score'], reverse=True)
    
    if ranking:
        max_score = ranking[0]['score']
        for entry in ranking:
            entry['relative_score'] = (entry['score'] / max_score) * 100

    return render(request, 'hall_of_fame.html', {'all_time_ranking': ranking})

@login_required
def home_view(request):
    player = request.user.player
    now = timezone.now()

    # 1. PROCHAIN MATCH (Alerte temporelle)
    next_match = Match.objects.filter(kickoff_at__gt=now).order_by('kickoff_at').first()

    # 2. LOGIQUE SAISON (Août à Août)
    if now.month <= 7:
        current_year_label = f"{now.year - 1}/{now.year}"
    else:
        current_year_label = f"{now.year}/{now.year + 1}"

    # On récupère toutes les compétitions de cette période (Top 14, 6 Nations, CC...)
    active_seasons = Season.objects.filter(year=current_year_label)

    # 3. STATS VIA TON MOTEUR (Global pour l'année)
    # On passe None en compétition pour avoir le général
    stats = compute_statistics(competition=None, season=None)

    # 4. EXTRACTION DES DONNÉES UTILISATEUR
    rank_general = "?"
    user_row = {}
    total_players = len(stats.detailed_ranking)
    
    for index, row in enumerate(stats.detailed_ranking):
        if row['username'] == request.user.username:
            rank_general = index + 1
            user_row = row
            break

    # 5. DERNIÈRE PERFORMANCE (Toutes compétitions confondues)
    last_finished_round = Round.objects.filter(
        season__in=active_seasons,
        matches__home_score__isnull=False
    ).distinct().order_by('-matches__kickoff_at').first()

    last_perf = None
    if last_finished_round:
        ds = DailyScore.objects.filter(user=request.user, round=last_finished_round).first()
        if ds:
            r_rank = DailyScore.objects.filter(round=last_finished_round, points__gt=ds.points).count() + 1
            last_perf = {'name': str(last_finished_round), 'points': ds.points, 'rank': r_rank}

    # 6. CALCULS TECHNIQUES (Bonus, Ratio, Demi-tout-pile)
    user_preds = Prediction.objects.filter(
        player=player, 
        match__round__season__in=active_seasons
    ).exclude(match__home_score__isnull=True)
    
    total_p = user_preds.count()
    bons_vainqueurs = 0
    demi_tout_pile = 0
    
    for p in user_preds:
        # Vainqueur
        real_h, real_a = p.match.home_score, p.match.away_score
        pred_h, pred_a = p.home_score_pred, p.away_score_pred
        
        if (pred_h > pred_a and real_h > real_a) or \
           (pred_h < pred_a and real_h < real_a) or \
           (pred_h == pred_a and real_h == real_a):
            bons_vainqueurs += 1
            
        # Demi-Tout-Pile
        if (pred_h == real_h or pred_a == real_a) and not (pred_h == real_h and pred_a == real_a):
            demi_tout_pile += 1

    # 7. CHOPES ET CUILLÈRES (Depuis ton objet stats car pas en BDD)
    # Ton moteur compute_statistics renvoie généralement ces dicts {username: count}
    chopes = stats.chopes_cumulees.get(request.user.username, 0) if isinstance(stats.chopes_cumulees, dict) else 0
    cuilleres = stats.cuilleres_bois.get(request.user.username, 0) if isinstance(stats.cuilleres_bois, dict) else 0

    context = {
        'player': player,
        'next_match': next_match,
        'rank_general': rank_general,
        'total_players': total_players,
        'last_perf': last_perf,
        'comp_rankings': SeasonScore.objects.filter(user=request.user, season__in=active_seasons).select_related('competition', 'season').order_by('-match_points'),
        'perfects': user_row.get('perfects', 0),
        'points_matchs': user_row.get('points', 0),
        'chopes_count': chopes,
        'cuilleres_count': cuilleres,
        'win_ratio': round((bons_vainqueurs / total_p * 100), 1) if total_p > 0 else 0,
        'demi_tout_pile': demi_tout_pile,
        'bonus_off_prono': user_preds.filter(bonus_off_pred=True).count(),
        'bonus_def_prono': user_preds.filter(bonus_def_pred=True).count(),
        'GLOBAL_LAST_ROUND_ID': last_finished_round.id if last_finished_round else None,
    }
    return render(request, 'home.html', context)