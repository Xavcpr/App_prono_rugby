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

from .models import CompetitionTeam, Match, Prediction, Competition, Round, Player, Season, Team, CompetitionTeamPrediction, CompetitionRankingPrediction, TeamRankingPrediction, CompetitionBonusPrediction
from .services.scoring import calculate_points




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