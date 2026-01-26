from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.forms import modelform_factory, modelformset_factory
from django.db import transaction
from .forms import CompetitionRankingPredictionForm, TeamRankingPredictionFormSet, TeamRankingFormSet
from .constants import COMPETITION_RULES

from .models import CompetitionTeam, Match, Prediction, Competition, Round, Player, Season, Team, CompetitionTeamPrediction, CompetitionRankingPrediction, TeamRankingPrediction, CompetitionBonusPrediction
from .services.scoring import calculate_points


@login_required
def pronos_view(request):
    user = request.user

    # Vérification Player
    try:
        player = user.player
    except Player.DoesNotExist:
        messages.error(
            request,
            "Votre compte n’est pas encore lié à un joueur. Contactez l’admin."
        )
        return redirect("logout")

    # ------------------
    # Filtres GET / journée par défaut
    # ------------------
    competition_id = request.GET.get("competition")
    round_id = request.GET.get("round")

    # Si aucun round_id passé en GET, on prend la prochaine journée à venir

    now = timezone.now().date()

    # 🎯 Journée par défaut = prochaine journée à venir
    if round_id is None:
        next_round = (
            Round.objects
            .filter(date__gte=now)
            .order_by("date")
            .first()
        )
        if next_round:
            round_id = str(next_round.id)

    matches = Match.objects.select_related(
        "round__season__competition",
        "home_team",
        "away_team",
    )

    if competition_id:
        matches = matches.filter(round__season__competition_id=competition_id)

    if round_id:
        matches = matches.filter(round_id=round_id)

    matches = matches.order_by(
        "round__season__competition__name",
        "round__number",
        "kickoff_at"
    )

    now = timezone.now()

    # Sauvegarde des pronostics
    if request.method == "POST":
        match_ids = request.POST.getlist("match_ids")

        for mid in match_ids:
            match = get_object_or_404(Match, id=mid)

            # 🔒 Ignore les matchs déjà commencés
            if match.kickoff_at <= now:
                continue

            try:
                home_score = int(request.POST.get(f"home_score_{mid}", 0))
                away_score = int(request.POST.get(f"away_score_{mid}", 0))
            except ValueError:
                home_score = 0
                away_score = 0

            bonus_home = request.POST.get(f"bonus_home_{mid}") == "on"
            bonus_away = request.POST.get(f"bonus_away_{mid}") == "on"

            prediction, created = Prediction.objects.get_or_create(
                match=match,
                player=player,
                defaults={
                    "home_score_pred": home_score,
                    "away_score_pred": away_score,
                    "bonus_home_pred": bonus_home,
                    "bonus_away_pred": bonus_away,
                },
            )

            if not created:
                prediction.home_score_pred = home_score
                prediction.away_score_pred = away_score
                prediction.bonus_home_pred = bonus_home
                prediction.bonus_away_pred = bonus_away

            try:
                prediction.points = calculate_points(prediction, match)
            except Exception as e:
                print("ERREUR calculate_points :", e)
                prediction.points = 0

            prediction.save()

        messages.success(
            request,
            "Vos pronostics ont été enregistrés (hors matchs déjà commencés)."
        )
        return redirect("pronostics")

    # Pronostics existants
    predictions = Prediction.objects.filter(player=player)
    predictions_by_match = {p.match_id: p for p in predictions}

    submit_disabled = True
    for match in matches:
        match.user_prediction = predictions_by_match.get(match.id)
        match.is_locked = match.kickoff_at <= now
        if not match.is_locked:
            submit_disabled = False

    competitions = Competition.objects.all()
    rounds = Round.objects.all()
    
    if competition_id:
        rounds = rounds.filter(season__competition_id=competition_id)

    return render(
        request,
        "pronos/pronos.html",
        {
            "player": player,
            "matches": matches,
            "competitions": competitions,
            "rounds": rounds,
            "submit_disabled": submit_disabled,
            "selected_round": round_id,  
        }
    )


@login_required
def logout_view(request):
    auth_logout(request)
    return redirect("login")


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

@login_required
def classement_prediction(request):
    player = request.user.player
    competitions = Competition.objects.all().order_by("name")
    selected_competition = None
    season = None
    blocks = []
    bonus = {"best_try_scorer": "", "best_point_scorer": ""}

    # ==================== Sélection compétition ====================
    competition_id = request.GET.get("competition")
    if competition_id:
        try:
            selected_competition = Competition.objects.get(id=competition_id)
        except Competition.DoesNotExist:
            selected_competition = None

    if not selected_competition:
        return render(request, "pronos/classement.html", {
            "competitions": competitions,
            "selected_competition": None
        })

    # On prend la dernière saison disponible pour cette compétition
    season = selected_competition.seasons.order_by("-year").first()

    # ==================== Récupérer ou créer les pronos ====================
    ranking, _ = CompetitionRankingPrediction.objects.get_or_create(
        player=player,
        season=season,
        competition=selected_competition
    )

    bonus_pred, _ = CompetitionBonusPrediction.objects.get_or_create(
        player=player,
        competition=selected_competition
    )
    bonus["best_try_scorer"] = bonus_pred.best_try_scorer
    bonus["best_point_scorer"] = bonus_pred.best_point_scorer

    # ==================== POST ====================
    if request.method == "POST":
        with transaction.atomic():
            # ----- Bonus -----
            bonus_pred.best_try_scorer = request.POST.get("best_try_scorer", "")
            bonus_pred.best_point_scorer = request.POST.get("best_point_scorer", "")
            bonus_pred.save()

            # ----- Classement équipes -----
            # On parcourt les champs envoyés
            for key, value in request.POST.items():
                if key.startswith("team_") and value:
                    _, block_key, pos = key.split("_")
                    pos = int(pos)
                    team_id = int(value)
                    team_obj = None
                    # Recherche team dans CompetitionTeam ou directement Team
                    ct = CompetitionTeam.objects.filter(
                        competition=selected_competition,
                        season=season,
                        team_id=team_id
                    ).first()
                    if ct:
                        team_obj = ct.team
                    else:
                        from core.models import Team
                        team_obj = Team.objects.get(id=team_id)

                    trp, _ = TeamRankingPrediction.objects.update_or_create(
                        ranking=ranking,
                        team=team_obj,
                        defaults={"position": pos}
                    )

        return redirect(f"{request.path}?competition={selected_competition.id}")

    # ==================== Construction des blocs ====================
    comp_teams = CompetitionTeam.objects.filter(
        competition=selected_competition,
        season=season
    ).order_by("pool", "team__name")

    saved_rankings = TeamRankingPrediction.objects.filter(ranking=ranking)
    saved_dict = {tr.position: tr.team.id for tr in saved_rankings}

    if comp_teams.exists() and any(ct.pool is not None for ct in comp_teams):
        # ----- Compétition avec poules -----
        pools = comp_teams.values_list("pool", flat=True).distinct()
        for pool in pools:
            teams_in_pool = comp_teams.filter(pool=pool).order_by("team__name")
            blocks.append({
                "pool": pool,
                "positions": range(1, teams_in_pool.count() + 1),
                "teams": [ct.team for ct in teams_in_pool],
                "key": f"pool_{pool}",
                "saved": saved_dict
            })
    else:
        # ----- Compétition sans poules -----
        # On prend toutes les équipes de la compétition
        teams_in_comp = selected_competition.teams.all().order_by("name")
        blocks.append({
            "pool": None,
            "positions": range(1, teams_in_comp.count() + 1),
            "teams": list(teams_in_comp),
            "key": "general",
            "saved": saved_dict
        })

    return render(request, "pronos/classement.html", {
        "competitions": competitions,
        "selected_competition": selected_competition,
        "blocks": blocks,
        "bonus": bonus
    })
