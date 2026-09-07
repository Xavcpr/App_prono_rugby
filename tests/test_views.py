import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestViewsAuth:

    def test_pronos_view_redirect_if_not_logged_in(self, client):
        url = reverse("pronos")
        response = client.get(url, secure=True)
        assert response.status_code == 302

    def test_home_view_ok(self, client, prediction):
        client.force_login(prediction.player.user)
        url = reverse("home")
        response = client.get(url, secure=True)
        assert response.status_code == 200

    def test_compute_round_no_auth_redirect(self, client, round_obj):
        url = reverse("compute_points", args=[round_obj.id])
        response = client.get(url, secure=True)
        assert response.status_code in (302, 403)

    def test_version_endpoint(self, client):
        from core.version import __version__
        url = reverse("version")
        response = client.get(url, secure=True)
        assert response.status_code == 200
        assert response.json() == {"version": __version__}


@pytest.mark.django_db
class TestBonusScoresEntry:
    def _staff_client(self, client, prediction):
        user = prediction.player.user
        user.is_staff = True
        user.save()
        client.force_login(user)
        return client

    def test_post_scores_updates_match_and_recomputes(self, client, prediction, match_with_scores, round_obj):
        from core.models import DailyScore
        client = self._staff_client(client, prediction)
        m = match_with_scores
        url = reverse("round_bonus", args=[round_obj.id])
        resp = client.post(url, {f"score_home_{m.id}": "31", f"score_away_{m.id}": "17"}, secure=True, HTTP_HOST="localhost")
        assert resp.status_code == 302
        m.refresh_from_db()
        assert (m.home_score, m.away_score) == (31, 17)
        assert DailyScore.objects.filter(user=prediction.player.user, round=round_obj).exists()

    def test_partial_score_not_saved(self, client, prediction, match_with_scores, round_obj):
        from core.models import DailyScore
        client = self._staff_client(client, prediction)
        m = match_with_scores
        url = reverse("round_bonus", args=[round_obj.id])
        resp = client.post(url, {f"score_home_{m.id}": "31"}, secure=True, HTTP_HOST="localhost")
        assert resp.status_code == 302
        m.refresh_from_db()
        assert m.home_score == 28
        assert m.away_score == 14
        assert not DailyScore.objects.filter(user=prediction.player.user, round=round_obj).exists()

    def test_bonus_checkboxes_still_saved(self, client, prediction, match_with_scores, round_obj):
        client = self._staff_client(client, prediction)
        m = match_with_scores
        url = reverse("round_bonus", args=[round_obj.id])
        resp = client.post(url, {f"bo_home_{m.id}": "on"}, secure=True, HTTP_HOST="localhost")
        assert resp.status_code == 302
        m.refresh_from_db()
        assert m.bonus_offense_home is True
        assert m.bonus_offense_away is False
