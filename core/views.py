from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout, update_session_auth_hash
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Prefetch, Sum, Count, Max
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
from .services.scoring import PHASE_MULTIPLIERS, SCORING_CONFIG, process_round_scores, get_winner_side, calculate_match_points, BONUS_SCALES
from .services.statistics import compute_statistics


# CONFIGURATION DU BAREME DES POINTS
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
        "winner": 150,
        "exact_rank": 50,
        "gap_1": 0,
        "gap_2": 0,
        "all_class" : 100,
        "1st" : 50,
        "2nd" : 25,
        "3rd" : 10,
    }
}

# ------------------
# PRONOS VIEW
# ------------------
@login_required
def pronos_view(request):
    print("--- LA VUE EST TRES BIEN CHARGÉE ---")
    user = request.user
    try:
        player = user.player
    except Player.DoesNotExist:
        messages.error(request, "Votre compte n’est pas encore lié à un joueur.")
        return redirect("logout")

    competition_id = request.GET.get("competition")
    round_id = request.GET.get("round")
    now = timezone.now()
    today = now.date()

    # --- Round par défaut ---
    if round_id is None:
        rounds_query = Round.objects.filter(date__gte=today)
        if competition_id:
            rounds_query = rounds_query.filter(season__competition_id=competition_id)
        
        next_round = rounds_query.order_by("date").first()
        if next_round:
            round_id = str(next_round.id)

    # --- Récupération des matchs ---
    matches = Match.objects.select_related(
        "round__season__competition",
        "home_team",
        "away_team",
    )

    if competition_id:
        matches = matches.filter(round__season__competition_id=competition_id)
    if round_id:
        matches = matches.filter(round_id=round_id)

    matches = matches.order_by("kickoff_at")

    # ------------------
    # POST = SAUVEGARDE
    # ------------------
    if request.method == "POST":
        for match in matches:
            mid = match.id
            
            # 1. Ne pas traiter si verrouillé
            if match.is_locked:
                continue

            # 2. Récupération et nettoyage immédiat des espaces
            h_score_raw = request.POST.get(f"home_score_{mid}", "").strip()
            a_score_raw = request.POST.get(f"away_score_{mid}", "").strip()

            # 3. Vérification stricte : si l'un des deux est vide, on ignore TOTALEMENT le match
            if not h_score_raw or not a_score_raw:
                continue

            # 4. Tentative de conversion en nombre
            try:
                home_score = int(h_score_raw)
                away_score = int(a_score_raw)
            except (ValueError, TypeError):
                # Si ce n'est pas un chiffre (ex: du texte), on ignore le match
                continue

            # 5. Récupération des bonus
            bonus_home = f"bonus_home_{mid}" in request.POST
            bonus_away = f"bonus_away_{mid}" in request.POST

            # 6. SAUVEGARDE : On utilise update_or_create pour être plus propre
            Prediction.objects.update_or_create(
                match=match,
                player=player,
                defaults={
                    'home_score_pred': home_score,
                    'away_score_pred': away_score,
                    'bonus_home_pred': bonus_home,
                    'bonus_away_pred': bonus_away,
                }
            )

        messages.success(request, "Pronostics enregistrés !")
        return redirect(f"{request.path}?competition={competition_id or ''}&round={round_id or ''}")

    # ------------------
    # PREPARATION AFFICHAGE
    # ------------------
    predictions_by_match = {p.match_id: p for p in Prediction.objects.filter(player=player)}

    submit_disabled = True
    for match in matches:
        match.user_prediction = predictions_by_match.get(match.id)
        if not match.is_locked:
            submit_disabled = False

    competitions = Competition.objects.all()
    all_rounds = Round.objects.select_related('season__competition').all()
    if competition_id:
        all_rounds = all_rounds.filter(season__competition_id=competition_id)

    return render(request, "pronos/pronos.html", {
        "player": player,
        "matches": matches,
        "competitions": competitions,
        "rounds": all_rounds,
        "submit_disabled": submit_disabled,
        "selected_round": round_id,
        "selected_competition": competition_id,
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
    
    # 1. RÉCUPÉRATION DES IDs DEPUIS L'URL
    comp_id = request.GET.get("comp")
    season_id = request.GET.get("season")
    round_id = request.GET.get("round")

    # 2. LISTES POUR LES MENUS DÉROULANTS
    all_competitions = Competition.objects.all().order_by('name')
    
    # Sélection de la compétition par défaut (la première ou la sélectionnée)
    if comp_id:
        selected_comp = all_competitions.filter(id=comp_id).first()
    else:
        # Par défaut, on cherche s'il y a un round proche d'aujourd'hui pour deviner la compétition
        near_round = Round.objects.filter(date__gte=now.date()).order_by("date").first()
        selected_comp = near_round.season.competition if near_round else all_competitions.first()

    # Liste des saisons pour la compétition choisie
    seasons = Season.objects.filter(competition=selected_comp).order_by('-year_start')
    
    # Sélection de la saison par défaut
    if season_id:
        selected_season = seasons.filter(id=season_id).first()
    else:
        selected_season = seasons.first() # La plus récente

    # Liste des journées pour la saison choisie
    rounds = Round.objects.filter(season=selected_season).order_by('number')

    # 3. IDENTIFICATION DU ROUND FINAL À AFFICHER
    if round_id:
        current_round_obj = rounds.filter(id=round_id).first()
    else:
        # Automatisme : round le plus proche du présent dans cette saison
        current_round_obj = rounds.filter(date__gte=now.date()).order_by("date").first()
        if not current_round_obj:
            current_round_obj = rounds.last()

    # 4. RÉCUPÉRATION DES DONNÉES DE MATCH ET PRONOS
    matches = []
    players = Player.objects.all().select_related('user').order_by('user__username')
    rows = []

    if current_round_obj:
        matches = Match.objects.filter(round=current_round_obj).select_related('home_team', 'away_team').order_by("kickoff_at")
        predictions = Prediction.objects.filter(match__round=current_round_obj)

        for m in matches:
            is_locked = now > m.kickoff_at if m.kickoff_at else False
            player_pronos = []
            has_result = m.home_score is not None and m.away_score is not None
            
            for p in players:
                prono = next((pred for pred in predictions if pred.match_id == m.id and pred.player_id == p.id), None)
                
                p_dict = {
                    'has_prono': prono is not None,
                    'score_home': None,
                    'score_away': None,
                    'class': "",
                    'display_locked': False,
                    # ... (tes autres clés de bonus success/fail ici)
                }

                # Logique de visibilité
                if not is_locked and not is_admin:
                    p_dict['display_locked'] = True
                
                if (is_locked or is_admin) and prono:
                    p_dict.update({
                        'score_home': prono.home_score_pred,
                        'score_away': prono.away_score_pred,
                        # Ajoute ici tes calculs de bonus success/fail que tu avais déjà
                    })
                    # Calcul de la classe CSS
                    if prono.home_score_pred > prono.away_score_pred: p_dict['class'] = "bg-home-win"
                    elif prono.away_score_pred > prono.home_score_pred: p_dict['class'] = "bg-away-win"
                    else: p_dict['class'] = "bg-draw"

                player_pronos.append(p_dict)

            rows.append({
                'info': f"{m.home_team.name if m.home_team else 'TBD'} - {m.away_team.name if m.away_team else 'TBD'}",
                'reel_home': m.home_score,
                'reel_away': m.away_score,
                'player_pronos': player_pronos,
                'is_locked': is_locked
            })

    return render(request, "pronos/all_pronos.html", {
        "rows": rows,
        "players": players,
        "competitions": all_competitions,
        "seasons": seasons,
        "rounds": rounds,
        "selected_comp": selected_comp,
        "selected_season": selected_season,
        "current_round_obj": current_round_obj,
    })
    

def round_results_board(request, round_id):
    round_obj = get_object_or_404(Round, id=round_id)
    players = Player.objects.all().order_by('name')
    matches = Match.objects.filter(round=round_obj).order_by('kickoff_at')
    all_competitions = Competition.objects.prefetch_related(
        Prefetch('seasons', queryset=Season.objects.all().order_by('-year'))
    ).distinct()

    # 1. Barème des Bonus de Journée (Vainqueurs trouvés)
    BONUS_SCALES = {
        "Top 14": {7: 150, 6: 60, 5: 20},
        "Champions Cup": {12: 300, 11: 150, 10: 100, 9: 40}
    }
    comp_name = round_obj.season.competition.name
    current_scale = BONUS_SCALES.get(comp_name, {})
    # AJOUT DU MULTIPLICATEUR DE COMPÉTITION
    comp_multiplier = 1
    if "6 Nations" in comp_name or "Six Nations" in comp_name:
        comp_multiplier = 2

    # 0. On pré-calcule le nombre de gagnants par match pour le partage du pool
    match_winners_counts = {}
    for m in matches:
        if m.home_score is not None and m.away_score is not None:
            # On définit le côté gagnant réel
            if m.home_score > m.away_score: real_side = "HOME"
            elif m.away_score > m.home_score: real_side = "AWAY"
            else: real_side = "DRAW"
            
            # On compte combien de prédictions correspondent
            winners_count = Prediction.objects.filter(
                match=m,
                # Logique pour trouver le bon côté dans les scores prédits
            ).extra(where=[
                "(home_score_pred > away_score_pred AND %s = 'HOME') OR "
                "(away_score_pred > home_score_pred AND %s = 'AWAY') OR "
                "(home_score_pred = away_score_pred AND %s = 'DRAW')"
            ], params=[real_side, real_side, real_side]).count()
            
            match_winners_counts[m.id] = winners_count
        else:
            match_winners_counts[m.id] = 0



    # 2. Construction de la matrice des points par match (Détail cellules)
    matrix = {}
    for m in matches:
        matrix[m.id] = {}
        for p in players:
            pred = Prediction.objects.filter(match=m, player=p).first()
            matrix[m.id][p.id] = pred.points if (pred and pred.points is not None) else 0

    # 3. Calcul des totaux et des stats par joueur
    totals_display = []
    for p in players:
        player_preds = Prediction.objects.filter(match__round=round_obj, player=p)
        
        # Initialisation des compteurs
        stats = {
            'pm': 0, 'winners': 0, 'bonus_comp': 0,
            'bo': 0, 'bd': 0, 'diff': 0, 'somme': 0, 'ext': 0, 'dtp': 0, 'draw' :0, 'tp': 0
        }

        for pr in player_preds:
            m = pr.match
            match_threshold = m.round.season.competition.bonus_defense_threshold
            if m.home_score is None or m.away_score is None: continue
            
            # # 1. On cumule les points totaux du match
            # --- CALCUL DU "PM" PUR (Partage du pool uniquement) ---
            winners_count = match_winners_counts.get(m.id, 0)
            real_winner_side = get_winner_side(m.home_score, m.away_score)
            pred_winner_side = get_winner_side(pr.home_score_pred, pr.away_score_pred)
            if pr.home_score_pred + pr.away_score_pred ==0 :
                pred_winner_side = "NO SHOW" # Cas où le joueur n'a pas du tout pronostiqué (0-0 sans bonus)
            
            if real_winner_side == pred_winner_side:
                stats['winners'] += 1 # On incrémente le compteur de victoires trouvées
                
                if winners_count > 0:
                    # Ici, on n'ajoute QUE la part du poids du match
                    stats['pm'] += (m.weight // winners_count)



            # 2. Logique des bonus spécifiques (Basé sur ton barème probable)
            # Bonus Offensif trouvé
            if pr.bonus_home_pred:
                if m.bonus_offense_home: stats['bo'] += scoring.SCORING_CONFIG['OFFENSIVE_BONUS_VALUE']
                else: stats['bo'] += scoring.SCORING_CONFIG['BONUS_MALUS']
            if pr.bonus_away_pred:
                if m.bonus_offense_away: stats['bo'] += scoring.SCORING_CONFIG['OFFENSIVE_BONUS_VALUE']
                else: stats['bo'] += scoring.SCORING_CONFIG['BONUS_MALUS']  
            
            # Bonus Défensif trouvé
            real_bd = m.get_defense_bonus() # HOME ou AWAY
            player_diff = abs((pr.home_score_pred - pr.away_score_pred))
            pred_bd = None
            
            if player_diff <= match_threshold and pred_winner_side != "NO SHOW": # Si je prédis une victoire serrée (diff <= seuil) et que je ne prédis pas un nul, alors je prédis un bonus défensif pour le côté que je pense perdant
                if pr.home_score_pred < pr.away_score_pred:
                    pred_bd = 'HOME'
                elif pr.away_score_pred < pr.home_score_pred:
                    pred_bd = 'AWAY'    
                else: pred_bd = 'DRAW'
                
            if pred_bd == 'HOME' : #si je prédis un bonus défensif pour l'équipe à domicile
                if real_bd == "HOME" or m.home_score == m.away_score : # et que le bonus défensif est bien pour l'équipe à domicile ou s'il y a un nul, le joueur mérite le bonus défensif
                    stats['bd'] += scoring.SCORING_CONFIG['DEFENSIVE_BONUS_VALUE']
                elif real_bd is None:
                    stats['bd'] += scoring.SCORING_CONFIG['BONUS_MALUS'] # Malus si le joueur a pris un bonus défensif alors qu'il n'y en avait pas
            
            if pred_bd == 'AWAY' :
                if real_bd == "AWAY" or m.home_score == m.away_score:
                    stats['bd'] += scoring.SCORING_CONFIG['DEFENSIVE_BONUS_VALUE']
                elif real_bd is None:
                    stats['bd'] += scoring.SCORING_CONFIG['BONUS_MALUS'] # Malus si le joueur a pris un bonus défensif alors qu'il n'y en avait pas

            # si je prédis un nul et qu'il y a quand même un bonus défensif, je mérite le bonus défensif. s'il n'y en a pas, je mérite le malus
            if pred_bd == 'DRAW' :
                if real_bd == "HOME" or real_bd == "AWAY":
                    stats['bd'] += scoring.SCORING_CONFIG['DEFENSIVE_BONUS_VALUE']
                else:
                    stats['bd'] += scoring.SCORING_CONFIG['BONUS_MALUS'] # Malus si le joueur a pris un bonus défensif alors qu'il n'y en avait pas
                    
            # 3. Somme, Différence et DTP (Exact score)
            home_diff = abs(pr.home_score_pred - m.home_score)
            away_diff = abs(pr.away_score_pred - m.away_score)
            
            if home_diff == 0 and pred_winner_side != "NO SHOW": stats['dtp'] += scoring.SCORING_CONFIG['HALF_PERFECT_BONUS'] # Score exact une équipe
            if away_diff == 0 and pred_winner_side != "NO SHOW": stats['dtp'] += scoring.SCORING_CONFIG['HALF_PERFECT_BONUS'] # Score exact une équipe
            
            #3.1 tout-pile
            if home_diff == 0 and away_diff == 0: stats['tp'] += scoring.SCORING_CONFIG['PERFECT_SCORE_BONUS'] # Score exact total

            diff = abs((pr.home_score_pred - pr.away_score_pred) - (m.home_score - m.away_score))
            sum = abs((pr.home_score_pred + pr.away_score_pred) - (m.home_score + m.away_score))       
            
            if sum in scoring.SCORING_CONFIG['SUM_TABLE'].keys() and pred_winner_side != "NO SHOW":
                stats['somme'] += scoring.SCORING_CONFIG['SUM_TABLE'][sum]
            
            if diff in scoring.SCORING_CONFIG['DIFF_TABLE'].keys() and pred_winner_side != "NO SHOW":
                stats['diff'] += scoring.SCORING_CONFIG['DIFF_TABLE'][diff]
            

            # 4. Victoire à l'extérieur trouvée
            real_winner = m.winner()
            if real_winner == m.away_team and pr.away_score_pred > pr.home_score_pred:
                stats['ext'] += scoring.SCORING_CONFIG['AWAY_WIN_BONUS']    
                

            # 4.1. Match nul trouvé
            if real_winner == "DRAW" and pr.home_score_pred == pr.away_score_pred and pred_winner_side != "NO SHOW":
                stats['draw'] += scoring.SCORING_CONFIG['DRAW_BONUS']  

        # Calcul du Bonus journée Palier (comme avant)
        daily_bonus = 0
        for threshold in sorted(current_scale.keys(), reverse=True):
            if stats['winners'] >= threshold:
                daily_bonus = current_scale[threshold]
                break

        # Calcul du score brut (tout inclus)
        raw_score = (
            stats['pm'] + stats['tp'] + stats['dtp'] + stats['bo'] + 
            stats['bd'] + stats['diff'] + stats['somme'] + 
            stats['ext'] + stats['draw'] + daily_bonus
        )

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
            'score': raw_score * comp_multiplier, # Application du multiplicateur de compétition    
            'rank_class': ''
        })

    # 4. Attribution des chopes de bière (sur le score final)
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
    }
    return render(request, 'round_board.html', context)

def compute_round_view(request, round_id):
    round_obj = get_object_or_404(Round, id=round_id)
    # On appelle ton script de scoring
    process_round_scores(round_obj)
    # Une fois fini, on revient sur la page des résultats
    return redirect('round_board', round_id=round_id)

# ------------------
# STATISTIQUES VIEW
# ------------------
@login_required
def statistiques_view(request):
    competition_id = request.GET.get("competition", "").strip()
    competitions = Competition.objects.all().order_by("name")

    competition = None
    if competition_id.isdigit():
        competition = get_object_or_404(Competition, id=int(competition_id))

    # Calcul des stats via le service
    stats = compute_statistics(competition)

    # --- SÉCURISATION DU CRASH SeasonScore ---
    season_scores = {}
    try:
        if competition:
            # On récupère les scores s'ils existent
            qs = SeasonScore.objects.filter(competition=competition).values('user__username', 'ranking_points')
            season_scores = {item['user__username']: item['ranking_points'] for item in qs}
        else:
            qs = SeasonScore.objects.values('user__username').annotate(total_rk=Sum('ranking_points'))
            season_scores = {item['user__username']: item['total_rk'] for item in qs}
    except Exception:
        # Si la colonne n'existe vraiment pas, on met 0 pour tout le monde au lieu de crasher
        season_scores = {}

    for r in stats.detailed_ranking:
        r['match_pts'] = r.get('points', 0)
        # On récupère le score de classement, sinon 0
        r['ranking_pts'] = season_scores.get(r['username'], 0)
        r['total_global'] = r['match_pts'] + r['ranking_pts']

    # Tri final sur le total global
    stats.detailed_ranking.sort(key=lambda x: x['total_global'], reverse=True)
    for i, r in enumerate(stats.detailed_ranking, 1):
        r['rank'] = i
        
    # 1. On crée le classement Flair (trié par ranking_pts)
    flair_ranking = sorted(stats.detailed_ranking, key=lambda x: x.get('ranking_pts', 0), reverse=True)
    
    # 2. On récupère le tableau des victoires depuis l'objet stats (calculé par compute_statistics)
    # Note: Vérifie que compute_statistics renvoie bien 'victory_table'
    victory_table = getattr(stats, 'victory_table', [])
    
    # On cherche la dernière journée pour le bouton "Résultats"
    last_round_id = None
    if competition:
        # On récupère la dernière journée de la compétition sélectionnée
        # On part de la saison la plus récente et de la journée la plus haute
        from .models import Round # Assure-toi que l'import est là
        lr = Round.objects.filter(season__competition=competition).order_by('-number').first()
        if lr:
            last_round_id = lr.id
    
    # ... reste du context identique ...
    context = {
        "competitions": competitions,
        "competition": competition,
        "kpi": stats.kpi,
        "labels": stats.labels,
        "score_series": stats.score_series,
        "detailed_ranking": stats.detailed_ranking,
        "choppes_or": stats.choppes_or,
        "chopes_cumulees": stats.chopes_cumulees,
        "cuilleres_bois": stats.cuilleres_bois,
        "flair_ranking": flair_ranking,
        "victory_table": victory_table,
        "last_round_id": last_round_id,
    }

    return render(request, "statistiques.html", context)


@login_required
def debug_scores_view(request):
    # 1. Récupérer la compétition sélectionnée (ou la dernière par défaut)
    competition_id = request.GET.get('competition')
    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
    else:
        selected_competition = Competition.objects.first()

    if not selected_competition:
        return render(request, "pronos/debug_scores.html", {"error": "Aucune compétition trouvée"})

    # 2. Récupérer les rounds et les joueurs
    rounds = Round.objects.filter(season__competition=selected_competition).order_by('number')
    players = Player.objects.all().select_related('user').order_by('name')
    
    # 3. Récupérer tous les scores de cette compétition
    # On utilise DailyScore qui semble être ton modèle de stockage par round
    daily_scores = DailyScore.objects.filter(round__in=rounds).select_related('user', 'round')

    # 4. Construire la matrice de données
    # Structure : { user_id: { round_id: points } }
    score_matrix = {}
    for score in daily_scores:
        if score.user_id not in score_matrix:
            score_matrix[score.user_id] = {}
        score_matrix[score.user_id][score.round_id] = score.points

    # 5. Calculer le total par joueur pour vérification
    player_data = []
    for p in players:
        row = {
            'player': p,
            'scores': [],
            'total_calc': 0
        }
        for r in rounds:
            # On récupère le score stocké en base
            pts = score_matrix.get(p.user_id, {}).get(r.id, 0)
            row['scores'].append(pts)
            row['total_calc'] += pts
        player_data.append(row)

    competitions = Competition.objects.all()

    return render(request, "debug_scores.html", {
        "selected_competition": selected_competition,
        "competitions": competitions,
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