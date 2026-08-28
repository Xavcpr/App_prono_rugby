import pytest
from django.urls import reverse

from core.models import (
    Season,
    Competition,
    CompetitionResult,
    CompetitionBonusPrediction,
    CompetitionTeamPrediction,
    Team,
)
from core.services import scoring


@pytest.fixture
def new_season():
    """Saison 2027 (cycle 2026/2027) -> déclenche le nouveau barème dégressif."""
    comp = Competition.objects.create(name="6 nations")
    return Season.objects.create(competition=comp, year="2027")


@pytest.mark.django_db
class TestParseRankedNames:
    def test_single_names(self):
        out = scoring._parse_ranked_names(
            {
                "real_best_try_scorer_1": "Dréan",
                "real_best_try_scorer_2": "Penaud",
                "real_best_try_scorer_3": "Ramos",
            },
            "real_best_try_scorer",
        )
        assert out == {"1": ["Dréan"], "2": ["Penaud"], "3": ["Ramos"]}

    def test_ex_aequo_coma(self):
        out = scoring._parse_ranked_names(
            {
                "real_best_try_scorer_1": "Dréan, Penaud",
                "real_best_try_scorer_2": "   ",
                "real_best_try_scorer_3": "Ramos",
            },
            "real_best_try_scorer",
        )
        assert out == {"1": ["Dréan", "Penaud"], "2": [], "3": ["Ramos"]}

    def test_missing_fields(self):
        out = scoring._parse_ranked_names({}, "real_best_try_scorer")
        assert out == {"1": [], "2": [], "3": []}


@pytest.mark.django_db
class TestRealTop3:
    def test_new_json(self, new_season):
        result = CompetitionResult.objects.create(
            season=new_season,
            real_best_try_scorers={"1": ["Dréan", "Penaud"], "2": ["Capuozzo"], "3": []},
        )
        top3 = scoring._real_top3(result, "real_best_try_scorers", "real_best_try_scorer")
        assert top3 == {"1": ["Dréan", "Penaud"], "2": ["Capuozzo"], "3": []}

    def test_fallback_old_single_field(self, new_season):
        result = CompetitionResult.objects.create(
            season=new_season,
            real_best_try_scorer="Dréan",
        )
        top3 = scoring._real_top3(result, "real_best_try_scorers", "real_best_try_scorer")
        assert top3 == {"1": ["Dréan"], "2": [], "3": []}


@pytest.mark.django_db
class TestScorerRanks:
    def test_new_cycle_6nations(self, new_season):
        assert scoring.scorer_rank_points(new_season, "1") == 50
        assert scoring.scorer_rank_points(new_season, "2") == 25
        assert scoring.scorer_rank_points(new_season, "3") == 0

    def test_new_cycle_top14(self):
        comp = Competition.objects.create(name="Top 14")
        s = Season.objects.create(competition=comp, year="2026/2027")
        assert scoring.scorer_rank_points(s, "1") == 300
        assert scoring.scorer_rank_points(s, "2") == 150
        assert scoring.scorer_rank_points(s, "3") == 50

    def test_new_cycle_champions_cup(self):
        comp = Competition.objects.create(name="Champions Cup")
        s = Season.objects.create(competition=comp, year="2026/2027")
        assert scoring.scorer_rank_points(s, "1") == 200
        assert scoring.scorer_rank_points(s, "2") == 75
        assert scoring.scorer_rank_points(s, "3") == 25

    def test_old_cycle_keeps_flat_bonus(self, season, new_season):
        """Saisons passées : bonus plat Top 14 = 200, CC/6N = 0 (ini).
        new_season force la clé max = 2026 pour que season devienne 'ancienne'."""
        assert scoring.scorer_rank_points(season, "1") == 200
        assert scoring.scorer_rank_points(season, "2") == 0
        assert scoring.scorer_rank_points(season, "3") == 0
        cc = Competition.objects.create(name="Champions Cup")
        old_cc = Season.objects.create(competition=cc, year="2026")  # clé 2025
        assert scoring.scorer_rank_points(old_cc, "1") == 0


@pytest.mark.django_db
class TestBonusMarqueurRealisateur:
    def test_degressif_ex_aequo(self, new_season, player):
        bonus = CompetitionBonusPrediction.objects.create(
            player=player,
            competition=new_season.competition,
            season=new_season,
            best_try_scorer="Dréan",
            best_point_scorer="Ramos",
        )
        result = CompetitionResult.objects.create(
            season=new_season,
            real_best_try_scorers={"1": ["Dréan", "Penaud"], "2": ["Capuozzo"], "3": ["Villière"]},
            real_best_point_scorers={"1": ["Ramos"], "2": [], "3": []},
        )
        pts = scoring.bonus_marqueur_realisateur_points(new_season, bonus, result)
        assert pts == 100  # 50 (marqueur rang 1) + 50 (réalisateur rang 1)

    def test_second_rank_only(self, new_season, player):
        bonus = CompetitionBonusPrediction.objects.create(
            player=player,
            competition=new_season.competition,
            season=new_season,
            best_try_scorer="Capuozzo",
        )
        result = CompetitionResult.objects.create(
            season=new_season,
            real_best_try_scorers={"1": ["Dréan"], "2": ["Capuozzo"], "3": []},
        )
        pts = scoring.bonus_marqueur_realisateur_points(new_season, bonus, result)
        assert pts == 25  # rang 2 -> 25

    def test_no_match_gets_zero(self, new_season, player):
        bonus = CompetitionBonusPrediction.objects.create(
            player=player,
            competition=new_season.competition,
            season=new_season,
            best_try_scorer="Inconnu",
        )
        result = CompetitionResult.objects.create(
            season=new_season,
            real_best_try_scorers={"1": ["Dréan"], "2": [], "3": []},
        )
        assert scoring.bonus_marqueur_realisateur_points(new_season, bonus, result) == 0

    def test_old_cycle_flat_200(self, season, new_season, player):
        bonus = CompetitionBonusPrediction.objects.create(
            player=player,
            competition=season.competition,
            season=season,
            best_try_scorer="Dréan",
        )
        result = CompetitionResult.objects.create(
            season=season,
            real_best_try_scorer="Dréan",
        )
        pts = scoring.bonus_marqueur_realisateur_points(season, bonus, result)
        assert pts == 200  # ancien barème : bonus plat Top 14


@pytest.mark.django_db
class TestClassementSeasonBug:
    def test_saved_predictions_have_season(self, client, user, player):
        comp = Competition.objects.create(name="Top 14")
        s = Season.objects.create(competition=comp, year="2026/2027")
        t1 = Team.objects.create(name="Toulouse")
        t2 = Team.objects.create(name="Paris")
        s.teams.add(t1, t2)
        client.force_login(user)

        resp = client.post(
            reverse("classement_prediction"),
            {
                "competition_id": comp.id,
                "season_id": s.id,
                "best_try_scorer": "Dréan",
                "best_point_scorer": "Ramos",
                "team_all_1": t1.id,
                "team_all_2": t2.id,
            },
            secure=True,
        )
        assert resp.status_code == 302

        saved = CompetitionTeamPrediction.objects.filter(competition=comp, player=player)
        assert saved.count() == 2
        assert all(p.season_id == s.id for p in saved)

        bonus = CompetitionBonusPrediction.objects.get(competition=comp, player=player)
        assert bonus.season_id == s.id


@pytest.mark.django_db
class TestAdminSaisieResultats:
    def test_post_saves_top3(self, client, user):
        comp = Competition.objects.create(name="6 nations")
        s = Season.objects.create(competition=comp, year="2027")
        user.is_staff = True
        user.save()
        client.force_login(user)

        url = reverse("admin_saisie_resultats")
        resp = client.post(
            f"{url}?competition={comp.id}",
            {
                "real_best_try_scorer_1": "Dupont, Ntamack",
                "real_best_try_scorer_2": "Penaud",
                "real_best_try_scorer_3": "",
                "real_best_point_scorer_1": "Ramos",
                "real_best_point_scorer_2": "",
                "real_best_point_scorer_3": "",
            },
            secure=True,
        )
        assert resp.status_code == 302

        res = CompetitionResult.objects.get(season=s)
        assert res.real_best_try_scorers == {"1": ["Dupont", "Ntamack"], "2": ["Penaud"], "3": []}
        assert res.real_best_point_scorers == {"1": ["Ramos"], "2": [], "3": []}
        assert res.real_best_try_scorer == "Dupont"  # rétro-compat

    def test_get_prefills_top3(self, client, user):
        comp = Competition.objects.create(name="6 nations")
        s = Season.objects.create(competition=comp, year="2027")
        CompetitionResult.objects.create(
            season=s,
            real_best_try_scorers={"1": ["Dupont", "Ntamack"], "2": ["Penaud"], "3": []},
        )
        user.is_staff = True
        user.save()
        client.force_login(user)
        resp = client.get(
            f"{reverse('admin_saisie_resultats')}?competition={comp.id}",
            secure=True,
        )
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Dupont, Ntamack" in html
        assert "Penaud" in html


@pytest.mark.django_db
class TestRenderPages:
    def test_classement_page_6nations(self, client, user, player):
        comp = Competition.objects.create(name="6 nations")
        s = Season.objects.create(competition=comp, year="2027")
        client.force_login(user)
        resp = client.get(
            f"{reverse('classement_prediction')}?competition={comp.id}&season={s.id}",
            secure=True,
        )
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "MEILLEUR MARQUEUR D'ESSAIS" in html
        assert "MEILLEUR SCOREUR (PTS)" in html

    def test_recap_page_6nations(self, client, user, player):
        comp = Competition.objects.create(name="6 nations")
        s = Season.objects.create(competition=comp, year="2027")
        user.is_staff = True
        user.save()
        client.force_login(user)
        resp = client.get(
            f"{reverse('recap_classement')}?competition={comp.id}&season={s.id}",
            secure=True,
        )
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Pronostics Bonus" in html

    def test_bareme_new_and_old(self, client):
        resp = client.get(reverse("bareme"), secure=True)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "800" in html
        assert "300" in html  # Top 14 1er marqueur

        resp_old = client.get(f"{reverse('bareme')}?ancien=1", secure=True)
        assert resp_old.status_code == 200
        html_old = resp_old.content.decode()
        assert "680" in html_old
        assert "200" in html_old  # ancien bonus plat Top 14