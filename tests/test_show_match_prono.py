import pytest
from django.core.management import call_command

from core.models import Prediction


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


@pytest.mark.django_db
def test_show_match_prono_sort_diff_optimistic_home_first(prediction, match_with_scores, player, capsys):
    Prediction.objects.create(
        player=player,
        match=match_with_scores,
        home_score_pred=35,
        away_score_pred=10,
        points=0,
    )
    call_command("show_match_prono", str(match_with_scores.id), "--sort", "diff")
    out = capsys.readouterr().out
    assert "28-14" in out
    assert out.index("[+25]") < out.index("[+14]")


@pytest.mark.django_db
def test_show_match_prono_sort_diff_tie_break_on_home_points(prediction, match_with_scores, player, capsys):
    prediction.home_score_pred = 28
    prediction.away_score_pred = 18
    prediction.save()
    Prediction.objects.create(
        player=player,
        match=match_with_scores,
        home_score_pred=35,
        away_score_pred=25,
        points=0,
    )
    call_command("show_match_prono", str(match_with_scores.id), "--sort", "diff")
    out = capsys.readouterr().out
    assert "[+10]" in out
    assert out.index("35-25") < out.index("28-18")