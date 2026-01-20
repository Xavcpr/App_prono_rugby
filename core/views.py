from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Match, Prediction
from .services.scoring import calculate_points


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

            bonus_home = bonus_home_key in request.POST
            bonus_away = bonus_away_key in request.POST

            prediction, created = Prediction.objects.get_or_create(
                match=match,
                player=request.user.player,
                defaults={
                    'home_score_pred': home_score,
                    'away_score_pred': away_score,
                    'bonus_home_pred': bonus_home,
                    'bonus_away_pred': bonus_away,
                }
            )

            if not created:
                prediction.home_score_pred = home_score
                prediction.away_score_pred = away_score
                prediction.bonus_home_pred = bonus_home
                prediction.bonus_away_pred = bonus_away

            prediction.points = calculate_points(prediction, match)
            prediction.save()

    return redirect('pronos')


  # ⚠️ même nom que dans urls.py

    return render(request, 'pronos.html', {'matches': matches})
