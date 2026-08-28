import pytest

from core.models import Round, Match, Team, Player, Prediction, User
from core.services.statistics import compute_statistics


@pytest.fixture
def round2(season):
    return Round.objects.create(season=season, number=2, date="2025-09-08", phase="POOL")


def _play(user, round_obj, winners):
    """Crée des Matchs (résultat réel = victoire 'home') et fait pronostiquer `user`.
    winners: liste de 'home'/'away'/'draw' (ou autre) par match pour l'utilisateur."""
    teams = [Team.objects.create(name=f"Équipe {i} {user.username}") for i in range(3)]
    player, _ = Player.objects.get_or_create(user=user, defaults={"name": user.username})
    for w in winners:
        match = Match.objects.create(
            round=round_obj,
            home_team=teams[0],
            away_team=teams[1],
            home_score=20,
            away_score=10,
            kickoff_at="2025-09-01 20:00:00+00",
            weight=800,
            phase="POOL",
        )
        if w == "home":
            f, s = 20, 10
        elif w == "away":
            f, s = 10, 20
        elif w == "draw":
            f, s = 10, 10
        else:
            f, s = 21, 11  # mauvais prono (real = 20-10)
        Prediction.objects.create(
            player=player,
            match=match,
            home_score_pred=f,
            away_score_pred=s,
            bonus_home_pred=False,
            bonus_away_pred=False,
            points=0,
        )


@pytest.mark.django_db
class TestBonusJourneeStats:
    def test_7_corrects_top14_gives_150_points(self, user, round2):
        _play(user, round2, ["home"] * 7)
        stats = compute_statistics(None, season=round2.season)
        table = {r["username"]: r["value"] for r in stats.bonus_journee_table}
        assert table[user.username] == 150

    def test_6_corrects_gives_60_points(self, user, round2):
        _play(user, round2, ["home"] * 6 + ["away"])
        stats = compute_statistics(None, season=round2.season)
        table = {r["username"]: r["value"] for r in stats.bonus_journee_table}
        assert table[user.username] == 60

    def test_5_corrects_gives_20_points(self, user, round2):
        _play(user, round2, ["home"] * 5 + ["away", "away"])
        stats = compute_statistics(None, season=round2.season)
        table = {r["username"]: r["value"] for r in stats.bonus_journee_table}
        assert table[user.username] == 20

    def test_below_threshold_gives_nothing(self, user, round2):
        _play(user, round2, ["home"] * 4 + ["away", "away", "away"])
        stats = compute_statistics(None, season=round2.season)
        table = {r["username"]: r["value"] for r in stats.bonus_journee_table}
        assert user.username not in table


@pytest.mark.django_db
class TestRemarquableBonsPronos:
    def test_solo_count(self, user, round2):
        _play(user, round2, ["home"] * 2)
        stats = compute_statistics(None, season=round2.season)
        solo = {r["username"]: r["value"] for r in stats.solo_bons_table}
        assert solo[user.username] == 2

    def test_five_players_800_5(self, user, round2):
        _play(user, round2, ["home"])
        match = round2.matches.first()
        for i in range(4):
            u = User.objects.create_user(username=f"p{i}-{user.username}", password="x")
            p = Player.objects.create(user=u, name=f"P{i}")
            Prediction.objects.create(
                player=p, match=match, home_score_pred=20, away_score_pred=10,
                bonus_home_pred=False, bonus_away_pred=False, points=0,
            )
        stats = compute_statistics(None, season=round2.season)
        cinq = {r["username"]: r["value"] for r in stats.cinq_bons_table}
        assert cinq[user.username] == 1
        assert all(cinq[p.user.username] == 1 for p in Player.objects.exclude(user=user))

    def test_four_players_not_counted_as_top5(self, user, round2):
        _play(user, round2, ["home"])
        match = round2.matches.first()
        u2 = User.objects.create_user(username=f"p2-{user.username}", password="x")
        Player.objects.create(user=u2, name="P2")
        Prediction.objects.create(
            player=Player.objects.get(user=u2), match=match,
            home_score_pred=20, away_score_pred=10,
            bonus_home_pred=False, bonus_away_pred=False, points=0,
        )
        stats = compute_statistics(None, season=round2.season)
        cinq = {r["username"]: r["value"] for r in stats.cinq_bons_table}
        assert cinq == {}


def _stats_url(round_obj, **extra):
    from django.urls import reverse
    comp = round_obj.season.competition.id
    base = f"/statistiques/?competition={comp}&season={round_obj.season.id}"
    if extra:
        base += "".join(f"&{k}={v}" for k, v in extra.items())
    return base


@pytest.mark.django_db
class TestStatsPage:
    def test_page_renders_selector_and_tables(self, client, user, round2):
        _play(user, round2, ["home"] * 5)
        client.force_login(user)
        resp = client.get(_stats_url(round2), secure=True)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Bon prono tout seul (800/1)" in html
        assert "Bons pronos remarquables" in html
        assert "Bonus journées" in html
        assert "Référence" in html

    def test_page_bonus_mode_5(self, client, user, round2):
        _play(user, round2, ["home"])
        match = round2.matches.first()
        for i in range(4):
            u = User.objects.create_user(username=f"q{i}-{user.username}", password="x")
            p = Player.objects.create(user=u, name=f"Q{i}")
            Prediction.objects.create(
                player=p, match=match, home_score_pred=20, away_score_pred=10,
                bonus_home_pred=False, bonus_away_pred=False, points=0,
            )
        client.force_login(user)
        resp = client.get(_stats_url(round2, bonus="5"), secure=True)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert '<option value="5" selected' in html or 'value="5" selected' in html
        assert "<strong>5</strong> uniques bons pronostiqueurs" in html
        assert user.username in html
