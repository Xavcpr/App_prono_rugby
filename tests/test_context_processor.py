from datetime import timedelta

import pytest

from django.utils import timezone

from core.context_processors import global_params
from core.models import Competition, Round, Season, Match


def make_match(round_obj, teams, days):
    return Match.objects.create(
        round=round_obj,
        home_team=teams[0],
        away_team=teams[1],
        home_score=1,
        away_score=0,
        kickoff_at=timezone.now() + timedelta(days=days),
        weight=680,
        phase="POOL",
    )


@pytest.mark.django_db
def test_picks_round_of_most_recent_kicked_off_match(competition, teams):
    Season.objects.create(competition=competition, year="2025/2026")
    old = Season.objects.create(competition=competition, year="2026/2027")
    r1 = Round.objects.create(season=old, number=1, date="2026-09-01", phase="POOL")
    r2 = Round.objects.create(season=old, number=2, date="2026-09-05", phase="POOL")
    make_match(r1, teams, -2)
    make_match(r2, teams, -1)
    ctx = global_params(object())
    assert ctx["GLOBAL_LAST_ROUND_ID"] == r2.id


@pytest.mark.django_db
def test_ignores_future_matches(competition, teams):
    Season.objects.create(competition=competition, year="2025/2026")
    old = Season.objects.create(competition=competition, year="2026/2027")
    r1 = Round.objects.create(season=old, number=1, date="2026-09-01", phase="POOL")
    r2 = Round.objects.create(season=old, number=2, date="2026-09-06", phase="POOL")
    make_match(r1, teams, -2)
    make_match(r2, teams, +3)
    ctx = global_params(object())
    assert ctx["GLOBAL_LAST_ROUND_ID"] == r1.id


@pytest.mark.django_db
def test_fallback_first_round_of_latest_season(competition):
    Season.objects.create(competition=competition, year="2025/2026")
    latest = Season.objects.create(competition=competition, year="2026/2027")
    Round.objects.create(season=latest, number=2, date="2026-10-01", phase="POOL")
    r1 = Round.objects.create(season=latest, number=1, date="2026-09-05", phase="POOL")
    ctx = global_params(object())
    assert ctx["GLOBAL_LAST_ROUND_ID"] == r1.id


@pytest.mark.django_db
def test_no_data_returns_empty(competition):
    ctx = global_params(object())
    assert ctx == {}