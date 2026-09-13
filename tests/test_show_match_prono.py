import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_show_match_prono_lists_player_and_score(prediction, match_with_scores, capsys):
    call_command("show_match_prono", str(match_with_scores.id))
    out = capsys.readouterr().out
    assert prediction.player.name in out
    assert f"{prediction.home_score_pred}-{prediction.away_score_pred}" in out
    assert f"#{match_with_scores.id}" in out


@pytest.mark.django_db
def test_show_match_prono_list_outputs_match_ids(match_with_scores, capsys):
    call_command("show_match_prono", "--list")
    out = capsys.readouterr().out
    assert f"#{match_with_scores.id}" in out
    assert "Stade Toulousain" in out
    assert "28-14" in out


@pytest.mark.django_db
def test_show_match_prono_search_by_team_name(prediction, match_with_scores, capsys):
    call_command("show_match_prono", "Stade Toulousain")
    out = capsys.readouterr().out
    assert prediction.player.name in out
    assert f"{prediction.home_score_pred}-{prediction.away_score_pred}" in out