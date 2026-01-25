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

from .models import Match, Prediction, Competition, Round, Player, Team, CompetitionRankingPrediction, TeamRankingPrediction
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
    user = request.user
    player = get_object_or_404(Player, user=user)

    # Filtre sur compétition
    competition_id = request.GET.get("competition")
    competition = Competition.objects.filter(id=competition_id).first() if competition_id else None
    competitions = Competition.objects.all()

    if not competition:
        return render(request, "classement_par_competition.html", {
            "competitions": competitions,
            "player": player,
        })

    # Saison actuelle (on prend la dernière saison créée pour la compétition)
    season = competition.seasons.order_by("-year").first()
    if not season:
        messages.error(request, "Aucune saison définie pour cette compétition.")
        return redirect("pronostics")

    # Récupération ou création du classement du joueur pour cette compétition
    ranking, _ = CompetitionRankingPrediction.objects.get_or_create(
        player=player,
        competition=competition,
        season=season
    )

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
    competition_id = request.GET.get("competition")
    competition = get_object_or_404(Competition, id=competition_id)

    rules = COMPETITION_RULES[competition.code]

    ranking, _ = CompetitionRankingPrediction.objects.get_or_create(
        player=request.user,
        competition=competition,
        season=competition.current_season,
    )

    formsets = {}

    if rules["type"] == "league":
        qs = TeamRankingPrediction.objects.filter(ranking=ranking)
        _ensure_lines(qs, rules["positions"], ranking)

        formsets["ALL"] = TeamRankingFormSet(
            queryset=qs,
            form_kwargs={"competition": competition}
        )

    else:  # GROUPS
        for pool in rules["pools"]:
            qs = TeamRankingPrediction.objects.filter(
                ranking=ranking, pool=pool
            )
            _ensure_lines(qs, rules["positions"], ranking, pool)

            formsets[pool] = TeamRankingFormSet(
                queryset=qs,
                form_kwargs={"competition": competition}
            )

    ranking_form = CompetitionRankingPredictionForm(
        instance=ranking,
        competition=competition
    )

    if request.method == "POST":
        valid = ranking_form.is_valid()
        for fs in formsets.values():
            valid &= fs.is_valid()

        if valid:
            ranking_form.save()

            for pool, fs in formsets.items():
                instances = fs.save(commit=False)
                for idx, obj in enumerate(instances, start=1):
                    obj.position = idx
                    obj.pool = None if pool == "ALL" else pool
                    obj.ranking = ranking
                    obj.save()

            if rules["winner_is_first"]:
                ranking.winner_team = TeamRankingPrediction.objects.filter(
                    ranking=ranking, position=1
                ).first().team
                ranking.save()

            return redirect(
                f"{request.path}?competition={competition.id}"
            )

    return render(request, "pronos/classement.html", {
        "competition": competition,
        "rules": rules,
        "formsets": formsets,
        "ranking_form": ranking_form,
    })


# def competition_ranking_view(request):
#     user = request.user
#     player = user.player

#     competition_id = request.GET.get("competition")
#     competitions = Competition.objects.all()
#     ranking_instance = None
#     team_formset = None
#     ranking_form = None

#     if competition_id:
#         competition = get_object_or_404(Competition, id=competition_id)
#         season, _ = Season.objects.get_or_create(
#             competition=competition,
#             year=competition.season
#         )
#         ranking_instance, _ = CompetitionRankingPrediction.objects.get_or_create(
#             player=player,
#             competition=competition,
#             season=season
#         )

#         # Check verrouillage
#         first_match = competition.seasons.first().rounds.order_by("date").first()
#         if first_match and first_match.date:
#             if timezone.now().date() >= first_match.date:
#                 ranking_instance.locked_at = timezone.now()
#                 ranking_instance.save()

#         # Formulaire global
#         ranking_form = CompetitionRankingPredictionForm(
#             request.POST or None,
#             instance=ranking_instance,
#             competition=competition
#         )

#         # Formset des équipes
#         qs = TeamRankingPrediction.objects.filter(ranking=ranking_instance)
#         # Si pas d'existant, créer les TeamRankingPrediction pour toutes les équipes
#         if not qs.exists():
#             for idx, team in enumerate(competition.teams.all(), start=1):
#                 TeamRankingPrediction.objects.create(
#                     ranking=ranking_instance,
#                     team=team,
#                     position=idx
#                 )
#             qs = TeamRankingPrediction.objects.filter(ranking=ranking_instance)

#         team_formset = TeamRankingPredictionFormSet(
#             request.POST or None,
#             queryset=qs,
#             form_kwargs={"competition": competition}
#         )

#         # Sauvegarde POST
#         if request.method == "POST" and ranking_form.is_valid() and team_formset.is_valid():
#             ranking_form.save()
#             team_formset.save()
#             return redirect(f"{request.path}?competition={competition_id}")

#     return render(request, "classement_par_competition.html", {
#         "competitions": competitions,
#         "selected_competition_id": int(competition_id) if competition_id else None,
#         "ranking_form": ranking_form,
#         "team_formset": team_formset,
#     })
