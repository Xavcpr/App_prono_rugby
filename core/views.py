from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.contrib import messages

from .models import (
    Match,
    Prediction,
    Competition,
    Round,
    Player
)

from .services.scoring import calculate_points

@login_required
def pronos_view(request):
    """
    Vue principale pour les pronostics.
    - Un seul formulaire pour tous les matchs.
    - Sauvegarde tous les pronos en une seule fois.
    - Filtres par compétition et journée.
    """
    user = request.user

    # Vérification Player
    try:
        player = user.player
    except Player.DoesNotExist:
        messages.error(request, "Votre compte n’est pas encore lié à un joueur. Contactez l’admin.")
        return redirect("logout")

    # ------------------
    # Filtres GET
    # ------------------
    competition_id = request.GET.get("competition")
    round_id = request.GET.get("round")

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

    # ------------------
    # Sauvegarde de tous les pronostics
    # ------------------
    if request.method == "POST":
        match_ids = request.POST.getlist("match_ids")  # tous les matchs affichés

        for mid in match_ids:
            match = get_object_or_404(Match, id=mid)

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

            # Calcul des points sécurisé
            try:
                prediction.points = calculate_points(prediction, match)
            except Exception as e:
                print("ERREUR calculate_points :", e)
                prediction.points = 0

            prediction.save()

        messages.success(request, "Tous vos pronostics ont été enregistrés !")
        return redirect("pronostics")

    # ------------------
    # Pronostics existants
    # ------------------
    predictions = Prediction.objects.filter(player=player)
    predictions_by_match = {p.match_id: p for p in predictions}

    for match in matches:
        match.user_prediction = predictions_by_match.get(match.id)

    # ------------------
    # Données pour filtres
    # ------------------
    competitions = Competition.objects.all()
    rounds = Round.objects.all()

    return render(
        request,
        "pronos.html",
        {
            "player": player,
            "matches": matches,
            "competitions": competitions,
            "rounds": rounds,
        }
    )
