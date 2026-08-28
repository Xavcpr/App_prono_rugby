import pytest
import base64
from datetime import date, timedelta
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

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
        assert "Clubs, équipes ou joueurs préférés" in resp.content.decode()

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
class TestAlertEmail:
    def test_post_saves_alert_email(self, client, player):
        client.force_login(player.user)
        client.post(
            reverse("profil"),
            {"birth_date": "", "aime": "", "aime_pas": "", "alert_email": "alerts@example.com"},
            secure=True,
        )
        player.refresh_from_db()
        assert player.alert_email == "alerts@example.com"

    def test_not_shown_in_trombinoscope(self, client, player, season):
        player.alert_email = "secrete@example.com"
        player.seasons.add(season)
        player.save()
        client.force_login(player.user)
        resp = client.get(reverse("trombinoscope"), secure=True)
        html = resp.content.decode()
        assert "secrete@example.com" not in html
        assert "alert_email" not in html

    def _make_reminder_round(self, season):
        from core.models import Round
        return Round.objects.create(
            season=season,
            number=5,
            date=timezone.now().date() + timedelta(days=1),
            phase="POOL",
        )

    def test_send_round_reminders_uses_alert_email(self, monkeypatch, season, player, user):
        from core.services import email_service
        rnd = self._make_reminder_round(season)
        sent_to = []
        monkeypatch.setattr(
            email_service,
            "send_mail",
            lambda subject, message, frm, to: sent_to.append(to[0]),
        )
        user.email = "user@test.com"
        user.save()
        player.alert_email = "alert@test.com"
        player.save()
        email_service.send_round_reminders()
        assert sent_to == ["alert@test.com"]

    def test_send_round_reminders_falls_back_to_user_email(self, monkeypatch, season, player, user):
        from core.services import email_service
        self._make_reminder_round(season)
        sent_to = []
        monkeypatch.setattr(
            email_service,
            "send_mail",
            lambda subject, message, frm, to: sent_to.append(to[0]),
        )
        user.email = "user@test.com"
        user.save()
        email_service.send_round_reminders()
        assert sent_to == ["user@test.com"]

    def test_send_round_reminders_skips_player_without_any_email(self, monkeypatch, season, player, user):
        from core.services import email_service
        self._make_reminder_round(season)
        sent_to = []
        monkeypatch.setattr(
            email_service,
            "send_mail",
            lambda subject, message, frm, to: sent_to.append(to[0]),
        )
        email_service.send_round_reminders()
        assert sent_to == []

    def test_notify_new_round_uses_alert_email(self, monkeypatch, season, player, user):
        from core.services import email_service
        sent_to = []
        monkeypatch.setattr(
            email_service,
            "send_mail",
            lambda subject, message, frm, to: sent_to.extend(to),
        )
        user.email = "user@test.com"
        user.save()
        player.alert_email = "alert@test.com"
        player.save()
        rnd = self._make_reminder_round(season)
        email_service.notify_new_round(rnd)
        assert "alert@test.com" in sent_to
        assert "user@test.com" not in sent_to


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