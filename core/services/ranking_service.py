from django.db.models import Sum
from core.models import DailyScore, SeasonScore


def compute_daily_scores(journee):
    DailyScore.objects.filter(journee=journee).delete()

    predictions = (
        Prediction.objects
        .filter(match__journee=journee)
        .select_related("user")
    )

    scores = {}
    for p in predictions:
        scores.setdefault(p.user, 0)
        scores[p.user] += p.points

    for user, pts in scores.items():
        DailyScore.objects.create(
            user=user,
            journee=journee,
            points=pts
        )


def update_season_ranking(competition):
    SeasonScore.objects.filter(competition=competition).delete()

    totals = (
        DailyScore.objects
        .filter(journee__competition=competition)
        .values("user")
        .annotate(total=Sum("points"))
    )

    for row in totals:
        SeasonScore.objects.create(
            user_id=row["user"],
            competition=competition,
            points=row["total"]
        )
