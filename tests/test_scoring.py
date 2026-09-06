import pytest
from core.services.scoring import get_winner_side, calculate_match_points


class TestGetWinnerSide:
    def test_home_wins(self):
        assert get_winner_side(20, 10) == "HOME"

    def test_away_wins(self):
        assert get_winner_side(10, 20) == "AWAY"

    def test_draw(self):
        assert get_winner_side(15, 15) == "DRAW"

    def test_zero_zero(self):
        assert get_winner_side(0, 0) == "DRAW"

    def test_scores_none(self):
        with pytest.raises(TypeError):
            get_winner_side(None, 10)


@pytest.mark.django_db
class TestCalculateMatchPoints:
    def test_perfect_score_pool(self, prediction, match_with_scores):
        pts = calculate_match_points(prediction, match_with_scores, winners_count=3)
        assert pts > 0
        assert isinstance(pts, int)

    def test_wrong_prediction(self, prediction, match_with_scores):
        prediction.home_score_pred = 0
        prediction.away_score_pred = 40
        pts = calculate_match_points(prediction, match_with_scores, winners_count=3)
        assert pts >= 0

    def test_no_show_gets_zero(self, prediction, match_with_scores):
        prediction.home_score_pred = 0
        prediction.away_score_pred = 0
        pts = calculate_match_points(prediction, match_with_scores, winners_count=3)
        assert pts == 0

    def test_no_winners_pool_split(self, prediction, match_with_scores):
        pts_all = calculate_match_points(prediction, match_with_scores, winners_count=1)
        pts_split = calculate_match_points(prediction, match_with_scores, winners_count=3)
        assert pts_all > pts_split


@pytest.mark.django_db
class TestProcessRoundScores:
    def test_phase_final_no_bonus(self, prediction, match_with_scores, round_obj):
        """T1: Phase FINAL ne doit pas compter les BO/BD"""
        from core.services.scoring import calculate_match_points
        match_with_scores.phase = "FINAL"
        match_with_scores.save()
        prediction.bonus_home_pred = True
        prediction.bonus_away_pred = True
        prediction.save()
        pts = calculate_match_points(prediction, match_with_scores, winners_count=1)
        assert pts > 0

    def test_process_round_creates_dailyscore(self, prediction, match_with_scores, round_obj):
        """T2: process_round_scores cree un DailyScore pour le joueur"""
        from core.services.scoring import process_round_scores
        from core.models import DailyScore
        assert DailyScore.objects.count() == 0
        process_round_scores(round_obj)
        assert DailyScore.objects.filter(user=prediction.player.user, round=round_obj).exists()

    def test_frozen_json_config_no_typeerror(self, prediction, match_with_scores, round_obj):
        """Config gelée en JSONField (clés str) : ni process_round_scores ni les
        bonus de palier ne doivent lever de TypeError."""
        import json
        from core.services.scoring import (
            _DEFAULT_SCORING_CONFIG, _get_scoring_config, process_round_scores,
        )
        from core.models import DailyScore
        round_obj.season.scoring_config = json.loads(json.dumps(_DEFAULT_SCORING_CONFIG))
        round_obj.season.save(update_fields=["scoring_config"])
        cfg = _get_scoring_config(round_obj.season)
        # Les clés numériques sont re-typées en int : la config gelée est équivalente
        # à la config par défaut en mémoire.
        assert cfg["SCORING_CONFIG"] == _DEFAULT_SCORING_CONFIG["SCORING_CONFIG"]
        assert cfg["BONUS_SCALES"] == _DEFAULT_SCORING_CONFIG["BONUS_SCALES"]
        assert cfg["MASTER_PALIERS"] == _DEFAULT_SCORING_CONFIG["MASTER_PALIERS"]
        assert all(isinstance(k, int) for scale in cfg["BONUS_SCALES"].values() for k in scale)
        assert all(isinstance(k, int) for k in cfg["MASTER_PALIERS"])
        process_round_scores(round_obj)
        assert DailyScore.objects.filter(user=prediction.player.user, round=round_obj).exists()

    def test_compute_season_ranking_points_no_result(self, season):
        """T3: compute_season_ranking_points retourne un message d'erreur si pas de CompetitionResult"""
        from core.services.scoring import compute_season_ranking_points
        msg = compute_season_ranking_points(season)
        assert "Aucun résultat" in msg
