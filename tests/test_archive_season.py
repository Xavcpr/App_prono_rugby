import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from core.models import (
    Competition, DailyScore, Match, Player, Prediction, Round, Season, SeasonHistory,
    SeasonScore, Team,
)


def _participate(user, season):
    """Crée un pronostic (signal de participation) pour un user dans une saison."""
    player, _ = Player.objects.get_or_create(user=user, defaults={"name": user.username})
    rnd, _ = Round.objects.get_or_create(
        season=season, number=1, defaults={"date": "2025-09-01", "phase": "POOL"}
    )
    home, _ = Team.objects.get_or_create(name="Home")
    away, _ = Team.objects.get_or_create(name="Away")
    match, _ = Match.objects.get_or_create(
        round=rnd, home_team=home, away_team=away,
        defaults={"kickoff_at": "2025-09-01 20:00:00+00", "weight": 680, "phase": "POOL"},
    )
    Prediction.objects.get_or_create(
        player=player, match=match,
        defaults={
            "home_score_pred": 1, "away_score_pred": 0,
            "bonus_home_pred": False, "bonus_away_pred": False, "points": 0,
        },
    )
    return player


@pytest.mark.django_db
def test_archive_season_writes_seasonhistory():
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year="2025/2026")
    u1 = User.objects.create_user(username="Alice", password="x")
    u2 = User.objects.create_user(username="Bob", password="x")
    _participate(u1, season)
    _participate(u2, season)
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
    _participate(u1, season)
    SeasonScore.objects.create(user=u1, season=season, competition=comp, match_points=100)

    call_command("archive_season", "2026")
    call_command("archive_season", "2026")

    assert SeasonHistory.objects.filter(season_year=2026).count() == 1


@pytest.mark.django_db
def test_archive_season_dry_run_writes_nothing():
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year="2025/2026")
    u1 = User.objects.create_user(username="Alice", password="x")
    _participate(u1, season)
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
    _participate(u1, s14)
    _participate(u1, s6n)
    _participate(u2, s14)
    SeasonScore.objects.create(user=u1, season=s14, competition=comp14, match_points=500)
    SeasonScore.objects.create(user=u1, season=s6n, competition=comp6n, match_points=100)
    SeasonScore.objects.create(user=u2, season=s14, competition=comp14, match_points=300)

    call_command("archive_season", "2026")

    rows = {r.user.username: r for r in SeasonHistory.objects.filter(season_year=2026)}
    assert rows["Alice"].rank == 1
    assert rows["Bob"].rank == 2


@pytest.mark.django_db
def test_archive_season_excludes_non_participants():
    comp14 = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    comp6n = Competition.objects.create(name="6 Nations", bonus_defense_threshold=7)
    s14 = Season.objects.create(competition=comp14, year="2025/2026")
    s6n = Season.objects.create(competition=comp6n, year="2025")
    u1 = User.objects.create_user(username="Alice", password="x")
    ghost = User.objects.create_user(username="Newcomer", password="x")
    _participate(u1, s14)
    # « Newcomer » a rejoint cette année : il n'a aucun pronostic en 2025-2026,
    # mais un SeasonScore fantôme à 0 pt peut exister (créé par sync) :
    SeasonScore.objects.create(user=ghost, season=s14, competition=comp14, match_points=0)
    SeasonScore.objects.create(user=ghost, season=s6n, competition=comp6n, match_points=0)
    SeasonScore.objects.create(user=u1, season=s14, competition=comp14, match_points=100)

    call_command("archive_season", "2026")

    rows = list(SeasonHistory.objects.filter(season_year=2026).order_by("rank"))
    assert len(rows) == 1
    assert rows[0].user == u1
    assert rows[0].total_players == 1
    assert rows[0].rank == 1


@pytest.mark.django_db
def test_archive_season_includes_end_year_six_nations():
    # La saison 2025-2026 comprend aussi le 6 Nations joué début 2026
    # (Season.year = "2026"). Sans lui, le classement est faux.
    comp14 = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    comp6n = Competition.objects.create(name="6 Nations", bonus_defense_threshold=7)
    s14 = Season.objects.create(competition=comp14, year="2025/2026")
    s6n_end = Season.objects.create(competition=comp6n, year="2026")
    u1 = User.objects.create_user(username="Alice", password="x")
    u2 = User.objects.create_user(username="Bob", password="x")
    _participate(u1, s14)
    _participate(u1, s6n_end)
    _participate(u2, s14)
    SeasonScore.objects.create(user=u1, season=s14, competition=comp14, match_points=500)
    SeasonScore.objects.create(user=u1, season=s6n_end, competition=comp6n, match_points=100)
    SeasonScore.objects.create(user=u2, season=s14, competition=comp14, match_points=550)

    call_command("archive_season", "2026")

    rows = {r.user.username: r for r in SeasonHistory.objects.filter(season_year=2026)}
    # Avec le 6 Nations 2026 : Alice 600 > Bob 550.
    assert rows["Alice"].rank == 1
    assert rows["Bob"].rank == 2


@pytest.mark.django_db
def test_archive_season_fallback_daily_score():
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year="2025/2026")
    u1 = User.objects.create_user(username="Alice", password="x")
    u2 = User.objects.create_user(username="Bob", password="x")
    _participate(u1, season)
    _participate(u2, season)
    rnd = Round.objects.get(season=season, number=1)
    DailyScore.objects.create(user=u1, round=rnd, points=700)
    DailyScore.objects.create(user=u2, round=rnd, points=300)
    # Alice a un SeasonScore à 0 pt : on retombe sur la somme des DailyScore
    # (même règle que home_view), Bob n'a aucun SeasonScore → fallback aussi.
    SeasonScore.objects.create(user=u1, season=season, competition=comp, match_points=0)

    call_command("archive_season", "2026")

    rows = {r.user.username: r for r in SeasonHistory.objects.filter(season_year=2026)}
    assert rows["Alice"].rank == 1
    assert rows["Bob"].rank == 2