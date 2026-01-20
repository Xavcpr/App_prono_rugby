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
            bonus_key = f"bonus_{match.id}"

            if home_key in request.POST and away_key in request.POST:
                home_score = int(request.POST[home_key])
                away_score = int(request.POST[away_key])
                bonus_offense = bonus_key in request.POST

                prediction, _ = Prediction.objects.update_or_create(
                    match=match,
                    player=request.user,   # ✅ ON UTILISE DIRECTEMENT LE USER
                    defaults={
                        'home_score_pred': home_score,
                        'away_score_pred': away_score,
                        'bonus_offense_pred': bonus_offense,
                    }
                )

                # calcul des points
                prediction.points = calculate_points(prediction, match)
                prediction.save()

        return redirect('pronos')  # ⚠️ même nom que dans urls.py

    return render(request, 'pronos.html', {'matches': matches})
