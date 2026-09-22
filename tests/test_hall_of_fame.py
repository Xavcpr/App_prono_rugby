import pytest
from django.urls import reverse

from core.models import SeasonHistory


@pytest.mark.django_db
def test_hall_of_fame_uses_archived_seasons_only(client):
    SeasonHistory.objects.create(
        season_year=2025, rank=1, total_players=16, player_name_legacy="Alex Laval"
    )
    SeasonHistory.objects.create(
        season_year=2019, rank=1, total_players=9, player_name_legacy="Alex Collet"
    )
    resp = client.get(reverse("hall_of_fame"), secure=True)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Alex Laval" in content
    assert "Alex Collet" in content
    assert "2025-2026" in content
    assert "2019-2020" in content
    # Pas de bloc « saison en cours » fantôme (SeasonScore vide en test) :
    assert "2026-2027" not in content