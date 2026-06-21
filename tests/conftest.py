import pytest

from django.contrib.auth.models import User
from core.models import Season, Competition, Round, Match, Team, Player, Prediction


@pytest.fixture
def competition():
    return Competition.objects.create(name="Top 14", bonus_defense_threshold=7)


@pytest.fixture
def season(competition):
    return Season.objects.create(competition=competition, year="2025/2026")


@pytest.fixture
def round_obj(season):
    return Round.objects.create(season=season, number=1, date="2025-09-01", phase="POOL")


@pytest.fixture
def teams():
    return [
        Team.objects.create(name="Stade Toulousain"),
        Team.objects.create(name="Stade Français"),
    ]


@pytest.fixture
def user():
    return User.objects.create_user(username="testuser", password="testpass")


@pytest.fixture
def player(user):
    return Player.objects.create(user=user, name="Test User")


@pytest.fixture
def match_with_scores(round_obj, teams):
    return Match.objects.create(
        round=round_obj,
        home_team=teams[0],
        away_team=teams[1],
        home_score=28,
        away_score=14,
        kickoff_at="2025-09-01 20:00:00+00",
        weight=680,
        phase="POOL",
    )


@pytest.fixture
def prediction(player, match_with_scores):
    return Prediction.objects.create(
        player=player,
        match=match_with_scores,
        home_score_pred=28,
        away_score_pred=14,
        bonus_home_pred=False,
        bonus_away_pred=False,
        points=0,
    )
