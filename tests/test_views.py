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
