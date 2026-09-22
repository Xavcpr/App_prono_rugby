from datetime import datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import Competition, Season, SeasonHistory, SeasonScore


@pytest.mark.django_db
def test_hall_of_fame_archives_use_end_year_labels(client):
    # Convention SeasonHistory : season_year = année de FIN de saison.
    # 2025 → saison 2024-2025 ; 2019 → 2018-2019.
    SeasonHistory.objects.create(
        season_year=2025, rank=3, total_players=16, player_name_legacy="Alex Laval"
    )
    SeasonHistory.objects.create(
        season_year=2019, rank=1, total_players=9, player_name_legacy="Alex Collet"
    )
    resp = client.get(reverse("hall_of_fame"), secure=True)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Alex Laval" in content
    assert "Alex Collet" in content
    assert "2024-2025" in content
    assert "2018-2019" in content
    assert "2025-2026" not in content


@pytest.mark.django_db
def test_hall_of_fame_includes_live_current_season(client):
    now = datetime.now()
    start_year = now.year if now.month >= 8 else now.year - 1
    season_year = f"{start_year}/{start_year + 1}"

    u = User.objects.create_user(username="Robin", password="testpass")
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year=season_year)
    SeasonScore.objects.create(
        user=u, season=season, competition=comp, match_points=21, ranking_points=0,
        podium_points=0,
    )

    resp = client.get(reverse("hall_of_fame"), secure=True)
    assert resp.status_code == 200
    content = resp.content.decode()
    # Le bloc live est présent et labellisé « 2026-2027 » (jamais « 2026 »).
    expected_label = f"{start_year}-{start_year + 1}"
    assert expected_label in content
    assert "Robin" in content