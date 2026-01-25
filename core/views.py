from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash

from .models import Match, Prediction, Competition, Round, Player
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
        "pronos.html",
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
