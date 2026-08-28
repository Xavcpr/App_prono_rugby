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
    def _prono_season(self, competition, year="2026/2027"):
        from core.models import Season
        return Season.objects.create(competition=competition, year=year)

    def test_redirect_if_not_logged(self, client):
        resp = client.get(reverse("trombinoscope"), secure=True)
        assert resp.status_code == 302

    def test_lists_players(self, client, competition):
        from core.models import Player
        from django.contrib.auth.models import User
        u = User.objects.create_user(username="trombi-user", password="x")
        player = Player.objects.create(user=u, name="Trombi",
                                       birth_date=date(1990, 1, 1),
                                       aime="Le rugby", aime_pas="Les poux")
        player.seasons.add(self._prono_season(competition))
        client.force_login(u)
        resp = client.get(reverse("trombinoscope"), secure=True)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Trombinoscope" in html
        assert player.name in html
        assert "Le rugby" in html
        assert "Les poux" in html

    def test_only_prono_years_shown(self, client, player, competition):
        cur = self._prono_season(competition)
        self._prono_season(competition, year="2024/2025")
        self._prono_season(competition, year="2005-2006")
        player.seasons.add(cur)
        player.save()
        client.force_login(player.user)
        resp = client.get(reverse("trombinoscope"), secure=True)
        html = resp.content.decode()
        assert "2026/2027" in html
        assert "2024/2025" not in html
        assert "2005-2006" not in html
        assert html.count("<option") == 1
        assert player.name in html

    def test_old_season_player_hidden(self, client, player, competition):
        player.seasons.add(self._prono_season(competition, year="2024/2025"))
        player.save()
        client.force_login(player.user)
        resp = client.get(reverse("trombinoscope"), secure=True)
        assert player.name not in resp.content.decode()

    def test_2025_2026_option_present(self, client, player, competition):
        self._prono_season(competition)
        self._prono_season(competition, year="2025/2026")
        self._prono_season(competition, year="2024/2025")
        client.force_login(player.user)
        resp = client.get(reverse("trombinoscope"), secure=True)
        html = resp.content.decode()
        assert "2026/2027" in html
        assert "2025/2026" in html
        assert "2024/2025" not in html
        assert html.count("<option") == 2

    def test_player_without_season_always_shown(self, client, player, competition):
        self._prono_season(competition)
        client.force_login(player.user)
        resp = client.get(reverse("trombinoscope"), secure=True)
        assert player.name in resp.content.decode()