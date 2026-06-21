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
