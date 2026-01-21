from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from .models import Match, Prediction
from .services.scoring import calculate_points
from django.urls import path

@login_required
def pronos_view(request):
    matches = Match.objects.all().order_by('round__date')

    if request.method == 'POST':
        for match in matches:
            home_key = f"home_{match.id}"
            away_key = f"away_{match.id}"
            bonus_home_key = f"bonus_home_{match.id}"
            bonus_away_key = f"bonus_away_{match.id}"

            if home_key in request.POST and away_key in request.POST:
                home_score = int(request.POST[home_key])
                away_score = int(request.POST[away_key])
                bonus_offense_home = bonus_home_key in request.POST
                bonus_offense_away = bonus_away_key in request.POST

                prediction, created = Prediction.objects.get_or_create(
                    match=match,
                    player=request.user.player,
                    defaults={
                        'home_score_pred': home_score,
                        'away_score_pred': away_score,
                        'bonus_offense_home_pred': bonus_offense_home,
                        'bonus_offense_away_pred': bonus_offense_away,
                    }
                )

                if not created:
                    prediction.home_score_pred = home_score
                    prediction.away_score_pred = away_score
                    prediction.bonus_offense_home_pred = bonus_offense_home
                    prediction.bonus_offense_away_pred = bonus_offense_away

                prediction.points = calculate_points(prediction, match)
                prediction.save()

        return redirect('pronostics')

    return render(request, 'pronostics.html', {'matches': matches})

@login_required
def logout_view(request):
    auth_logout(request)
    return redirect('login')  # redirige vers /accounts/login/
