import pytest

from core.models import Match, Player, Prediction, Round, SeasonScore, Team
from core.services.scoring import sync_season_match_points


@pytest.mark.django_db
def test_sync_removes_ghost_rows_for_non_participants(season, competition):
    """Un compte sans aucun pronostic dans la saison ne doit pas avoir de
    SeasonScore (entrée fantôme à 0 pt), ni en garder un existant."""
    from django.contrib.auth.models import User
    u = User.objects.create_user(username="Newcomer", password="x")
    Player.objects.create(user=u, name="Newcomer")
    SeasonScore.objects.create(user=u, season=season, competition=competition, match_points=0)

    sync_season_match_points(season)

    assert not SeasonScore.objects.filter(user=u, season=season).exists()


@pytest.mark.django_db
def test_sync_keeps_zero_point_participant(season, competition, prediction):
    """Un joueur ayant déposé des pronos doit garder sa ligne même à 0 pt."""
    sync_season_match_points(season)
    ss = SeasonScore.objects.get(user=prediction.player.user, season=season)
    assert ss.match_points == 0


@pytest.mark.django_db
def test_sync_sets_match_points_for_participant(season, competition, prediction, match_with_scores):
    from django.db.models import Sum
    from core.models import DailyScore
    from core.services.scoring import process_round_scores

    process_round_scores(match_with_scores.round)
    expected = DailyScore.objects.filter(
        user=prediction.player.user, round__season=season
    ).aggregate(total=Sum("points"))["total"]

    sync_season_match_points(season)
    ss = SeasonScore.objects.get(user=prediction.player.user, season=season)
    assert ss.match_points == expected
    assert ss.match_points > 0