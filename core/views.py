from urllib import request
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.forms import modelform_factory, modelformset_factory
from .forms import CompetitionRankingPredictionForm, TeamRankingPredictionFormSet, TeamRankingFormSet
from .constants import COMPETITION_RULES
from .services.scoring import process_round_scores, get_winner_side
from .services import scoring

from .models import CompetitionTeam, Match, Prediction, Competition, Round, Player, Season, Team, CompetitionTeamPrediction, CompetitionRankingPrediction, TeamRankingPrediction, CompetitionBonusPrediction
from .services.scoring import calculate_match_points
from django.db.models import Prefetch




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
    rankings = []

    if selected_competition_id:
        selected_competition = get_object_or_404(Competition, id=selected_competition_id)
        # Récupère tous les classements de cette compétition
        rankings = TeamRankingPrediction.objects.filter(ranking__competition=selected_competition)\
                                                .order_by("position")

    return render(request, "pronos/classement.html", {
        "competitions": competitions,
        "selected_competition": selected_competition,
        "rankings": rankings,
    })


    # Form pour les champs libres (vainqueur, meilleurs marqueurs)
    CompetitionRankingForm = modelform_factory(
        CompetitionRankingPrediction,
        fields=["winner_team", "best_try_scorer", "best_kicker"]
    )

    # Formset pour les équipes
    TeamRankingFormSet = modelformset_factory(
        TeamRankingPrediction,
        fields=["team", "position", "pool"],
        extra=0,
        can_delete=False
    )

    # Initialisation du formset avec les équipes de cette compétition
    team_rankings = TeamRankingPrediction.objects.filter(ranking=ranking)
    if not team_rankings.exists():
        # Génère les objets TeamRankingPrediction vierges pour chaque équipe
        teams = list(competition.teams.all())
        for idx, team in enumerate(teams):
            TeamRankingPrediction.objects.create(ranking=ranking, team=team, position=idx+1)
        team_rankings = TeamRankingPrediction.objects.filter(ranking=ranking)

    form = CompetitionRankingForm(request.POST or None, instance=ranking)
    formset = TeamRankingFormSet(request.POST or None, queryset=team_rankings)

    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Classement enregistré !")
            return redirect("pronostics")

    return render(request, "classement_par_competition.html", {
        "competitions": competitions,
        "competition": competition,
        "season": season,
        "form": form,
        "formset": formset,
        "player": player
    })

def _ensure_lines(qs, count, ranking, pool=None):
    existing = qs.count()
    if existing < count:
        TeamRankingPrediction.objects.bulk_create([
            TeamRankingPrediction(
                ranking=ranking,
                position=i + 1,
                pool=pool
            )
            for i in range(existing, count)
        ])


# ------------------
# CLASSEMENT_PREDICTION VIEW
# ------------------
@login_required
def classement_prediction(request):
    competitions = Competition.objects.all()
    competition_id = request.GET.get("competition")

    selected_competition = None
    blocks = []
    bonus = None
    winner_teams = []

    if competition_id:
        selected_competition = get_object_or_404(Competition, id=competition_id)
        
        # Récupération des bonus (Structure Simple)
        bonus, _ = CompetitionBonusPrediction.objects.get_or_create(
            player=request.user.player,
            competition=selected_competition
        )
        
        # Liste des équipes pour le menu "Vainqueur"
        winner_teams = selected_competition.teams.all().order_by("name")

        # Configuration des blocs (Poule ou Général)
        if selected_competition.name.lower() == "champions cup":
            season = Season.objects.filter(competition=selected_competition).order_by("-year").first()
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
        # 1. Sauvegarde des Bonus
        bonus.best_try_scorer = request.POST.get("best_try_scorer", "").strip()
        bonus.best_point_scorer = request.POST.get("best_point_scorer", "").strip()
        
        winner_id = request.POST.get("winner")
        bonus.winner_id = int(winner_id) if winner_id and winner_id.isdigit() else None
        bonus.save()

        # 2. Nettoyage du classement existant
        CompetitionTeamPrediction.objects.filter(
            competition=selected_competition, 
            player=request.user.player
        ).delete()

        # 3. Enregistrement des nouvelles positions avec SECURITÉ DOUBLONS
        recorded_teams = set()  # Pour suivre les équipes déjà sauvées
        
        for block in blocks:
            for pos in block["positions"]:
                field_name = f"team_{block['key']}_{pos}"
                team_id_raw = request.POST.get(field_name)
                
                if team_id_raw and team_id_raw.isdigit():
                    t_id = int(team_id_raw)
                    
                    # SI L'ÉQUIPE EST DÉJÀ CHOISIE DANS CETTE COMPÉTITION, ON PASSE
                    if t_id in recorded_teams:
                        continue
                    
                    CompetitionTeamPrediction.objects.create(
                        competition=selected_competition,
                        player=request.user.player,
                        team_id=t_id,
                        position=pos,
                        block_key=block["key"]
                    )
                    recorded_teams.add(t_id) # On marque l'équipe comme enregistrée
        
        messages.success(request, "Vos pronostics ont été enregistrés ! (Les équipes en doublon ont été ignorées)")
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
        "competitions": competitions,
        "selected_competition": selected_competition,
        "blocks": blocks,
        "bonus": bonus,
        "winner_teams": winner_teams,
        "last_saved_ranking": last_saved_ranking,
    })
 
def all_pronos_view(request):
    now = timezone.now()
    
    round_id_raw = request.GET.get("round")
    all_rounds = Round.objects.select_related('season__competition').order_by('season__competition', 'number')

    selected_round_id = None
    if round_id_raw and round_id_raw.isdigit():
        selected_round_id = int(round_id_raw)
    else:
        current_r = Round.objects.filter(date__gte=now.date()).order_by("date").first()
        if not current_r:
            current_r = Round.objects.order_by("-date").first()
        selected_round_id = current_r.id if current_r else None

    current_round_obj = all_rounds.filter(id=selected_round_id).first()

    matches = Match.objects.filter(round_id=selected_round_id).select_related('home_team', 'away_team').order_by("kickoff_at")
    players = Player.objects.all().select_related('user').order_by('user__username')
    predictions = Prediction.objects.filter(match__round_id=selected_round_id)

    rows = []
    for m in matches:
        is_locked = now > m.kickoff_at if m.kickoff_at else False
        player_pronos = []
        
        # On définit si le résultat réel est déjà connu
        has_result = m.home_score is not None and m.away_score is not None
        
        for p in players:
            prono = next((pred for pred in predictions if pred.match_id == m.id and pred.player_id == p.id), None)
            
            p_dict = {
                'score_home': None,
                'score_away': None,
                'bonus_home': False,
                'bonus_away': False,
                'bonus_home_success': False,
                'bonus_home_fail': False,
                'bonus_away_success': False,
                'bonus_away_fail': False,
                'is_perfect_home': False,
                'is_perfect_away': False,
                'class': "",
                'display_locked': False
            }

            if not is_locked:
                p_dict['display_locked'] = True
            elif prono:
                p_dict['score_home'] = prono.home_score_pred
                p_dict['score_away'] = prono.away_score_pred
                p_dict['bonus_home'] = prono.bonus_home_pred
                p_dict['bonus_away'] = prono.bonus_away_pred
                
                # --- Logique des Bonus (Vert / Rouge / Orange) ---
                if prono.bonus_home_pred:
                    if has_result:
                        if m.bonus_offense_home:
                            p_dict['bonus_home_success'] = True # Vert
                        else:
                            p_dict['bonus_home_fail'] = True    # Rouge
                    # Si pas de résultat, bonus_home reste True -> Orange dans le HTML

                if prono.bonus_away_pred:
                    if has_result:
                        if m.bonus_offense_away:
                            p_dict['bonus_away_success'] = True # Vert
                        else:
                            p_dict['bonus_away_fail'] = True    # Rouge
                
                # --- Test Score Exact ---
                if m.home_score is not None:
                    p_dict['is_perfect_home'] = (prono.home_score_pred == m.home_score)
                if m.away_score is not None:
                    p_dict['is_perfect_away'] = (prono.away_score_pred == m.away_score)

                # --- Classes de couleurs de fond (Gagnant/Perdant) ---
                if prono.home_score_pred > prono.away_score_pred:
                    p_dict['class'] = "bg-home-win"
                elif prono.away_score_pred > prono.home_score_pred:
                    p_dict['class'] = "bg-away-win"
                elif prono.home_score_pred == prono.away_score_pred:
                    p_dict['class'] = "bg-draw"

            player_pronos.append(p_dict)

        rows.append({
            'info': f"{m.home_team.name if m.home_team else 'TBD'} - {m.away_team.name if m.away_team else 'TBD'}",
            'reel_home': m.home_score,
            'reel_away': m.away_score,
            'bonus_home_reel': m.bonus_offense_home,
            'bonus_away_reel': m.bonus_offense_away,
            'player_pronos': player_pronos
        })

    return render(request, "pronos/all_pronos.html", {
        "rows": rows,
        "players": players,
        "rounds": all_rounds,
        "selected_round": selected_round_id,
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
    threshold = round_obj.season.competition.bonus_defense_threshold
    current_scale = BONUS_SCALES.get(comp_name, {})

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
            if m.home_score is None or m.away_score is None: continue
            
            # # 1. On cumule les points totaux du match
            # stats['pm'] += pr.points if pr.points else 0

            # --- CALCUL DU "PM" PUR (Partage du pool uniquement) ---
            winners_count = match_winners_counts.get(m.id, 0)
            real_winner_side = get_winner_side(m.home_score, m.away_score)
            pred_winner_side = get_winner_side(pr.home_score_pred, pr.away_score_pred)
            
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
            home_diff = abs(pr.home_score_pred - m.home_score)
            player_diff = abs((pr.home_score_pred - pr.away_score_pred))
            pred_bd = None
            
            if player_diff <= threshold :
                if pr.home_score_pred < pr.away_score_pred:
                    pred_bd = 'HOME'
                else:
                    pred_bd = 'AWAY'    
                
            if pred_bd == 'HOME' : 
                if real_bd == "HOME":
                    stats['bd'] += scoring.SCORING_CONFIG['DEFENSIVE_BONUS_VALUE']
                elif real_bd is None:
                    stats['bd'] += scoring.SCORING_CONFIG['BONUS_MALUS'] # Malus si le joueur a pris un bonus défensif alors qu'il n'y en avait pas
            
            if pred_bd == 'AWAY' :
                if real_bd == "AWAY":
                    stats['bd'] += scoring.SCORING_CONFIG['DEFENSIVE_BONUS_VALUE']
                elif real_bd is None:
                    stats['bd'] += scoring.SCORING_CONFIG['BONUS_MALUS'] # Malus si le joueur a pris un bonus défensif alors qu'il n'y en avait pas
        

            # 3. Somme, Différence et DTP (Exact score)
            
            away_diff = abs(pr.away_score_pred - m.away_score)
            
            if home_diff == 0: stats['dtp'] += scoring.SCORING_CONFIG['HALF_PERFECT_BONUS'] # Score exact une équipe
            if away_diff == 0: stats['dtp'] += scoring.SCORING_CONFIG['HALF_PERFECT_BONUS'] # Score exact une équipe
            
            #3.1 tout-pile
            if home_diff == 0 and away_diff == 0: stats['tp'] += scoring.SCORING_CONFIG['PERFECT_SCORE_BONUS'] # Score exact total

            diff = abs((pr.home_score_pred - pr.away_score_pred) - (m.home_score - m.away_score))
            sum = abs((pr.home_score_pred + pr.away_score_pred) - (m.home_score + m.away_score))       
            
            if sum in scoring.SCORING_CONFIG['SUM_TABLE'].keys():
                stats['somme'] += scoring.SCORING_CONFIG['SUM_TABLE'][sum]
            
            if diff in scoring.SCORING_CONFIG['DIFF_TABLE'].keys():
                stats['diff'] += scoring.SCORING_CONFIG['DIFF_TABLE'][diff]
            

            # 4. Victoire à l'extérieur trouvée
            real_winner = m.winner()
            if real_winner == m.away_team and pr.away_score_pred > pr.home_score_pred:
                stats['ext'] += scoring.SCORING_CONFIG['AWAY_WIN_BONUS']    
                

            # 4.1. Match nul trouvé
            if real_winner == "DRAW" and pr.home_score_pred == pr.away_score_pred:
                stats['draw'] += scoring.SCORING_CONFIG['DRAW_BONUS']  
            
            # # 5. Compteur vainqueurs simple
            
            # if (pr.home_score_pred > pr.away_score_pred and m.home_score > m.away_score) or \
            #    (pr.away_score_pred > pr.home_score_pred and m.away_score > m.home_score) or \
            #    (pr.home_score_pred == pr.away_score_pred and m.home_score == m.away_score):
            #     stats['winners'] += 1

        # Calcul du Bonus journée Palier (comme avant)
        daily_bonus = 0
        for threshold in sorted(current_scale.keys(), reverse=True):
            if stats['winners'] >= threshold:
                daily_bonus = current_scale[threshold]
                break

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
            'score': stats['pm'] + stats['tp'] + stats['dtp'] + stats['bo'] + stats['bd'] + stats['diff'] + stats['somme'] + stats['ext'] + stats['draw'] + daily_bonus,
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