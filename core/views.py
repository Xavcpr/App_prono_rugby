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
    - 1 match = 1 formulaire = 1 sauvegarde
    - Filtres par compétition et journée
    """
    user = request.user

    # ------------------
    # Vérification Player
    # ------------------
    try:
        player = user.player
    except Player.DoesNotExist:
        messages.error(
            request,
            "Votre compte n’est pas encore lié à un joueur. Contactez l’admin."
        )
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
        matches = matches.filter(
            round__season__competition_id=competition_id
        )

    if round_id:
        matches = matches.filter(round_id=round_id)

    matches = matches.order_by(
        "round__season__competition__name",
        "round__number",
        "kickoff_at"
    )

    # ------------------
    # Enregistrement d’un prono
    # ------------------
    if request.method == "POST":
        match_id = request.POST.get("match_id")
        match = get_object_or_404(Match, id=match_id)

        try:
            home_score = int(request.POST.get("home_score"))
            away_score = int(request.POST.get("away_score"))
        except (TypeError, ValueError):
            messages.error(request, "Scores invalides.")
            return redirect("pronostics")

        bonus_home = request.POST.get("bonus_home") == "on"
        bonus_away = request.POST.get("bonus_away") == "on"

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

        messages.success(
            request,
            f"Prono enregistré pour {match.home_team} – {match.away_team}"
        )

        return redirect("pronostics")

    # ------------------
    # Pronostics existants
    # ------------------
    predictions = Prediction.objects.filter(player=player)
    predictions_by_match = {
        p.match_id: p for p in predictions
    }

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


@login_required
def logout_view(request):
    auth_logout(request)
    return redirect("login")
