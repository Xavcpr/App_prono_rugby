import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from core.models import Competition, Season, SeasonHistory, SeasonScore


@pytest.mark.django_db
def test_archive_season_writes_seasonhistory():
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year="2025/2026")
    u1 = User.objects.create_user(username="Alice", password="x")
    u2 = User.objects.create_user(username="Bob", password="x")
    SeasonScore.objects.create(user=u1, season=season, competition=comp, match_points=500)
    SeasonScore.objects.create(user=u2, season=season, competition=comp, match_points=300)

    call_command("archive_season", "2026")

    rows = list(SeasonHistory.objects.filter(season_year=2026).order_by("rank"))
    assert len(rows) == 2
    assert rows[0].user == u1 and rows[0].rank == 1
    assert rows[1].user == u2 and rows[1].rank == 2
    assert rows[0].total_players == 2
    assert rows[0].display_name == "Alice"


@pytest.mark.django_db
def test_archive_season_is_idempotent():
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year="2025/2026")
    u1 = User.objects.create_user(username="Alice", password="x")
    SeasonScore.objects.create(user=u1, season=season, competition=comp, match_points=100)

    call_command("archive_season", "2026")
    call_command("archive_season", "2026")

    assert SeasonHistory.objects.filter(season_year=2026).count() == 1


@pytest.mark.django_db
def test_archive_season_dry_run_writes_nothing():
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year="2025/2026")
    u1 = User.objects.create_user(username="Alice", password="x")
    SeasonScore.objects.create(user=u1, season=season, competition=comp, match_points=100)

    call_command("archive_season", "2026", dry_run=True)

    assert not SeasonHistory.objects.filter(season_year=2026).exists()


@pytest.mark.django_db
def test_archive_season_aggregates_across_competitions():
    comp14 = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    comp6n = Competition.objects.create(name="6 Nations", bonus_defense_threshold=7)
    s14 = Season.objects.create(competition=comp14, year="2025/2026")
    s6n = Season.objects.create(competition=comp6n, year="2025")
    u1 = User.objects.create_user(username="Alice", password="x")
    u2 = User.objects.create_user(username="Bob", password="x")
    SeasonScore.objects.create(user=u1, season=s14, competition=comp14, match_points=500)
    SeasonScore.objects.create(user=u1, season=s6n, competition=comp6n, match_points=100)
    SeasonScore.objects.create(user=u2, season=s14, competition=comp14, match_points=300)

    call_command("archive_season", "2026")

    rows = {r.user.username: r for r in SeasonHistory.objects.filter(season_year=2026)}
    assert rows["Alice"].rank == 1
    assert rows["Bob"].rank == 2