from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Match, Prediction
from .services.scoring import calculate_points  # ta fonction existante

@login_required
def pronostics_view(request):
    # On prend tous les matchs à venir ou non encore pronostiqués par l'utilisateur
    matches = Match.objects.all().order_by('round__date')

    if request.method == 'POST':
        for match in matches:
            # Lecture des champs envoyés depuis le formulaire
            home_key = f"home_{match.id}"
            away_key = f"away_{match.id}"
            bonus_key = f"bonus_{match.id}"

            if home_key in request.POST and away_key in request.POST:
                home_score = int(request.POST[home_key])
                away_score = int(request.POST[away_key])
                bonus_offense = bonus_key in request.POST

                # Crée ou récupère le pronostic de l'utilisateur pour ce match
                prediction, created = Prediction.objects.get_or_create(
                    match=match,
                    player=request.user.player,  # on suppose que chaque User a un Player lié
                    defaults={
                        'home_score_pred': home_score,
                        'away_score_pred': away_score,
                        'bonus_offense_pred': bonus_offense
                    }
                )

                if not created:
                    prediction.home_score_pred = home_score
                    prediction.away_score_pred = away_score
                    prediction.bonus_offense_pred = bonus_offense

                # Calcul des points
                prediction.points = calculate_points(prediction, match)
                prediction.save()

        return redirect('pronostics')  # reload la page après envoi

    return render(request, 'pronostics.html', {'matches': matches})
