import pytest
import base64
from datetime import date
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.mark.django_db
class TestPlayerProfileModel:
    def test_initials(self, player):
        player.name = "Jean Dupont"
        assert player.initials == "JD"

    def test_initials_single(self, player):
        player.name = "Marco"
        assert player.initials == "M"

    def test_age(self, player):
        player.birth_date = date(1990, 1, 1)
        assert player.age == date.today().year - 1990

    def test_age_none(self, player):
        assert player.age is None


@pytest.mark.django_db
class TestProfilPage:
    def test_redirect_if_not_logged(self, client):
        resp = client.get(reverse("profil"), secure=True)
        assert resp.status_code == 302

    def test_get_renders(self, client, player):
        client.force_login(player.user)
        resp = client.get(reverse("profil"), secure=True)
        assert resp.status_code == 200
        assert "J'aime" in resp.content.decode()

    def test_post_saves(self, client, player):
        client.force_login(player.user)
        resp = client.post(
            reverse("profil"),
            {
                "birth_date": "1990-05-15",
                "aime": "Le rugby, le café",
                "aime_pas": "La pluie",
            },
            secure=True,
        )
        assert resp.status_code == 302
        player.refresh_from_db()
        assert player.birth_date == date(1990, 5, 15)
        assert player.aime == "Le rugby, le café"
        assert player.aime_pas == "La pluie"

    def test_post_clears_birth(self, client, player):
        player.birth_date = date(1990, 5, 15)
        player.save()
        client.force_login(player.user)
        client.post(reverse("profil"), {"birth_date": "", "aime": "", "aime_pas": ""}, secure=True)
        player.refresh_from_db()
        assert player.birth_date is None

    def test_upload_photo(self, client, player):
        client.force_login(player.user)
        photo = SimpleUploadedFile("photo.png", PNG_1PX, content_type="image/png")
        resp = client.post(
            reverse("profil"),
            {"birth_date": "", "aime": "", "aime_pas": "", "photo": photo},
            secure=True,
        )
        assert resp.status_code == 302
        player.refresh_from_db()
        assert player.photo
        assert player.photo.name.endswith(".png")

    def test_upload_then_clear_photo(self, client, player):
        client.force_login(player.user)
        photo = SimpleUploadedFile("photo.png", PNG_1PX, content_type="image/png")
        client.post(reverse("profil"), {"birth_date": "", "aime": "", "aime_pas": "", "photo": photo}, secure=True)
        client.post(
            reverse("profil"),
            {"birth_date": "", "aime": "", "aime_pas": "", "photo_clear": "on"},
            secure=True,
        )
        player.refresh_from_db()
        assert not player.photo

    def test_photo_served(self, client, player):
        client.force_login(player.user)
        photo = SimpleUploadedFile("photo.png", PNG_1PX, content_type="image/png")
        client.post(reverse("profil"), {"birth_date": "", "aime": "", "aime_pas": "", "photo": photo}, secure=True)
        player.refresh_from_db()
        resp = client.get(player.photo.url, secure=True)
        assert resp.status_code == 200


@pytest.mark.django_db
class TestTrombinoscope:
    def test_redirect_if_not_logged(self, client):
        resp = client.get(reverse("trombinoscope"), secure=True)
        assert resp.status_code == 302

    def test_lists_players(self, client, player, season):
        player.birth_date = date(1990, 1, 1)
        player.aime = "Le rugby"
        player.aime_pas = "Les poux"
        player.seasons.add(season)
        player.save()
        client.force_login(player.user)
        resp = client.get(reverse("trombinoscope"), secure=True)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Trombinoscope" in html
        assert player.name in html
        assert "Le rugby" in html
        assert "Les poux" in html