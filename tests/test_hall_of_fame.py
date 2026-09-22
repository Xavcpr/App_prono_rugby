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


@pytest.mark.django_db
def test_hall_of_fame_current_season_excludes_previous_six_nations(client):
    # La saison en cours = Top14/CC "start/(start+1)" + 6N "start+1".
    # Le 6N "start" (joué début d'année) appartient à la SAISON PRÉCÉDENTE
    # et ne doit pas être compté dans le bloc live du HOF.
    now = datetime.now()
    start_year = now.year if now.month >= 8 else now.year - 1
    prev_6n_year = str(start_year)
    cur_6n_year = str(start_year + 1)
    cur_top_year = f"{start_year}/{start_year + 1}"

    comp14 = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    comp6n = Competition.objects.create(name="6 Nations", bonus_defense_threshold=7)
    s_prev6n = Season.objects.create(competition=comp6n, year=prev_6n_year)
    s_cur6n = Season.objects.create(competition=comp6n, year=cur_6n_year)
    s_cur_top = Season.objects.create(competition=comp14, year=cur_top_year)

    robin = User.objects.create_user(username="Robin", password="x")
    merlin = User.objects.create_user(username="Merlin", password="x")
    # Robin cartonne sur le 6N de l'an dernier → ne doit pas compter.
    SeasonScore.objects.create(user=robin, season=s_prev6n, competition=comp6n, match_points=9000)
    SeasonScore.objects.create(user=robin, season=s_cur_top, competition=comp14, match_points=5)
    # Merlin brille sur la saison en cours (Top14 + 6N de la saison).
    SeasonScore.objects.create(user=merlin, season=s_cur_top, competition=comp14, match_points=900)
    SeasonScore.objects.create(user=merlin, season=s_cur6n, competition=comp6n, match_points=100)

    resp = client.get(reverse("hall_of_fame"), secure=True)
    content = resp.content.decode()
    assert content.index("Merlin") < content.index("Robin")


@pytest.mark.django_db
def test_hall_of_fame_modal_seasons_newest_first(client):
    # Le modal d'un joueur liste ses saisons de la plus récente à la plus ancienne.
    now = datetime.now()
    start_year = now.year if now.month >= 8 else now.year - 1
    cur_label = f"{start_year}-{start_year + 1}"
    prev1_label = f"{start_year - 1}-{start_year}"
    prev2_label = f"{start_year - 2}-{start_year - 1}"

    u = User.objects.create_user(username="Arthur", password="x")
    SeasonHistory.objects.create(
        season_year=start_year - 1, rank=4, total_players=10, player_name_legacy="Arthur"
    )
    SeasonHistory.objects.create(
        season_year=start_year, rank=2, total_players=10, player_name_legacy="Arthur"
    )
    # Entrée « saison en cours ».
    comp = Competition.objects.create(name="Top 14", bonus_defense_threshold=7)
    season = Season.objects.create(competition=comp, year=f"{start_year}/{start_year + 1}")
    SeasonScore.objects.create(user=u, season=season, competition=comp, match_points=10)

    resp = client.get(reverse("hall_of_fame"), secure=True)
    content = resp.content.decode()
    assert content.index(f"Historique : {u.username}") > 0
    assert content.index(cur_label) < content.index(prev1_label) < content.index(prev2_label)