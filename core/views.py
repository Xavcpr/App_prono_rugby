# from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth.decorators import login_required
# from django.contrib.auth import logout as auth_logout
# from django.contrib import messages
# from .models import Match, Prediction, Competition, Round
# # , Player
# from .services.scoring import calculate_points

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
    - Possibilité de filtrer par compétition et round
    """
    user = request.user

    # ⚠ Vérifie que l'utilisateur a un Player
    try:
        player = user.player
    except Player.DoesNotExist:
        messages.error(request, "Aucun profil joueur associé à votre compte.")
        return redirect("admin:index")

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
    # Sauvegarde d'un prono unique
    # ------------------
    if request.method == "POST":
        match_id = request.POST.get("match_id")
        match = get_object_or_404(Match, id=match_id)

        try:
            home_score = int(request.POST.get("home_score"))
            away_score = int(request.POST.get("away_score"))
        except (TypeError, ValueError):
            messages.error(request, "Scores invalides")
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

        prediction.points = calculate_points(prediction, match)
        prediction.save()

        messages.success(request, f"Prono enregistré pour {match}")
        return redirect(request.path)
    # ------------------
    # Récupération des pronos existants pour l'utilisateur
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
            "matches": matches,
            "competitions": competitions,
            "rounds": rounds,
        }
    )


@login_required
def logout_view(request):
    auth_logout(request)
    return redirect("login")



# from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth.decorators import login_required
# from django.contrib.auth import logout as auth_logout
# from django.contrib import messages

# from .models import Match, Prediction
# from .services.scoring import calculate_points


# @login_required
# def pronos_view(request):
#     """
#     Affichage des matchs + enregistrement des pronostics
#     (1 match = 1 formulaire = 1 sauvegarde)
#     """

#     # Tous les matchs, bien ordonnés pour l'affichage
#     matches = (
#         Match.objects
#         .select_related(
#             "round",
#             "round__season",
#             "round__season__competition",
#             "home_team",
#             "away_team",
#         )
#         .order_by(
#             "round__season__competition__name",
#             "round__number",
#             "match_datetime",
#         )
#     )

#     if request.method == "POST":
#         match_id = request.POST.get("match_id")
#         match = get_object_or_404(Match, id=match_id)

#         try:
#             home_score = int(request.POST.get("home_score"))
#             away_score = int(request.POST.get("away_score"))
#         except (TypeError, ValueError):
#             messages.error(request, "Scores invalides")
#             return redirect("pronostics")

#         bonus_home = request.POST.get("bonus_home") == "on"
#         bonus_away = request.POST.get("bonus_away") == "on"

#         prediction, created = Prediction.objects.get_or_create(
#             match=match,
#             player=request.user.player,
#             defaults={
#                 "home_score_pred": home_score,
#                 "away_score_pred": away_score,
#                 "bonus_home_pred": bonus_home,
#                 "bonus_away_pred": bonus_away,
#             },
#         )

#         if not created:
#             prediction.home_score_pred = home_score
#             prediction.away_score_pred = away_score
#             prediction.bonus_home_pred = bonus_home
#             prediction.bonus_away_pred = bonus_away

#         prediction.points = calculate_points(prediction, match)
#         prediction.save()

#         messages.success(
#             request,
#             f"Prono enregistré pour {match}"
#         )

#         return redirect("pronostics")

#     return render(
#         request,
#         "pronostics.html",
#         {
#             "matches": matches,
#         },
#     )


# @login_required
# def logout_view(request):
#     auth_logout(request)
#     return redirect("login")



# # from django.shortcuts import render, redirect
# # from django.contrib.auth.decorators import login_required
# # from django.contrib.auth import logout as auth_logout
# # from .models import Match, Prediction
# # from .services.scoring import calculate_points
# # from django.urls import path

# # @login_required
# # def pronos_view(request):
# #     matches = Match.objects.all().order_by('round__date')

# #     if request.method == 'POST':
# #         for match in matches:
# #             home_key = f"home_{match.id}"
# #             away_key = f"away_{match.id}"
# #             bonus_home_key = f"bonus_home_{match.id}"
# #             bonus_away_key = f"bonus_away_{match.id}"

# #             if home_key in request.POST and away_key in request.POST:
# #                 home_score = int(request.POST[home_key])
# #                 away_score = int(request.POST[away_key])
# #                 bonus_offense_home = bonus_home_key in request.POST
# #                 bonus_offense_away = bonus_away_key in request.POST

# #                 prediction, created = Prediction.objects.get_or_create(
# #                     match=match,
# #                     player=request.user.player,
# #                     defaults={
# #                         'home_score_pred': home_score,
# #                         'away_score_pred': away_score,
# #                         'bonus_offense_home_pred': bonus_offense_home,
# #                         'bonus_offense_away_pred': bonus_offense_away,
# #                     }
# #                 )

# #                 if not created:
# #                     prediction.home_score_pred = home_score
# #                     prediction.away_score_pred = away_score
# #                     prediction.bonus_offense_home_pred = bonus_offense_home
# #                     prediction.bonus_offense_away_pred = bonus_offense_away

# #                 prediction.points = calculate_points(prediction, match)
# #                 prediction.save()

# #         return redirect('pronostics')

# #     return render(request, 'pronostics.html', {'matches': matches})

# # @login_required
# # def logout_view(request):
# #     auth_logout(request)
# #     return redirect('login')  # redirige vers /accounts/login/

# @login_required
# def pronos(request):
#     user = request.user
#     player = user.player

#     # ------------------
#     # Filtres
#     # ------------------
#     competition_id = request.GET.get("competition")
#     round_id = request.GET.get("round")

#     matches = Match.objects.select_related(
#         "round__season__competition",
#         "home_team",
#         "away_team",
#     )

#     if competition_id:
#         matches = matches.filter(
#             round__season__competition_id=competition_id
#         )

#     if round_id:
#         matches = matches.filter(round_id=round_id)

#     matches = matches.order_by(
#         "round__season__competition__name",
#         "round__number",
#         "kickoff_at"
#     )

#     # ------------------
#     # Récupération des pronos du joueur
#     # ------------------
#     predictions = Prediction.objects.filter(player=player)

#     predictions_by_match = {
#         p.match_id: p for p in predictions
#     }

#     # 🔥 ICI le code IMPORTANT
#     for match in matches:
#         match.user_prediction = predictions_by_match.get(match.id)

#     # ------------------
#     # Données pour filtres
#     # ------------------
#     competitions = Competition.objects.all()
#     rounds = Round.objects.all()

#     return render(
#         request,
#         "pronos.html",
#         {
#             "matches": matches,
#             "competitions": competitions,
#             "rounds": rounds,
#         }
#     )