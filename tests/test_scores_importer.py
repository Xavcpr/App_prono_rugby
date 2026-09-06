import pytest

from core.models import Match, Round, Season, Team
from core.services import scores_importer
from core.services.scores_importer import _fetch_events, import_scores


@pytest.mark.django_db
class TestFetchEvents:
    def test_merges_extra_rounds_with_dedup(self, monkeypatch):
        def fake_request(url, *a, **k):
            if "eventsseason" in url:
                return {"events": [
                    {"intRound": 1, "intHomeTeam": "A", "intAwayTeam": "B"},
                    {"intRound": 1, "intHomeTeam": "C", "intAwayTeam": "D"},
                ]}
            if "eventsround" in url:
                return {"events": [
                    {"intRound": 1, "intHomeTeam": "A", "intAwayTeam": "B"},
                    {"intRound": 1, "intHomeTeam": "E", "intAwayTeam": "F"},
                ]}
            return {}
        monkeypatch.setattr(scores_importer, "_request", fake_request)
        events = _fetch_events("2026-2027", "4430", quick=True, extra_rounds=[1])
        keys = {(e["intHomeTeam"], e["intAwayTeam"]) for e in events}
        assert len(events) == 3
        assert ("E", "F") in keys

    def test_empty_season_quick_uses_extra_rounds(self, monkeypatch):
        def fake_request(url, *a, **k):
            if "eventsseason" in url:
                return {"events": []}
            if "eventsround" in url:
                return {"events": [{"intRound": 1, "intHomeTeam": "A", "intAwayTeam": "B"}]}
            return {}
        monkeypatch.setattr(scores_importer, "_request", fake_request)
        events = _fetch_events("2026-2027", "4430", quick=True, extra_rounds=[1])
        assert len(events) == 1

    def test_quick_without_rounds_returns_empty(self, monkeypatch):
        monkeypatch.setattr(scores_importer, "_request", lambda *a, **k: {"events": []})
        assert _fetch_events("s", "4430", quick=True) == []


@pytest.mark.django_db
class TestImportScores:
    def _make_season(self, competition):
        return Season.objects.create(competition=competition, year="2026/2027")

    def _make_round(self, season):
        rnd = Round.objects.create(season=season, number=1, date="2026-09-05", phase="POOL")
        home = Team.objects.create(name="Bayonne")
        away = Team.objects.create(name="Toulon")
        Match.objects.create(round=rnd, home_team=home, away_team=away, phase="POOL")
        return rnd

    def test_updates_score_from_ft_event(self, competition, monkeypatch):
        season = self._make_season(competition)
        rnd = self._make_round(season)
        event = [{
            "intRound": 1,
            "strHomeTeam": "Aviron Bayonnais",
            "strAwayTeam": "RC Toulonnais",
            "intHomeScore": "27", "intAwayScore": "26",
            "strStatus": "FT",
            "dateEvent": "2026-09-05", "strTime": "17:00:00",
        }]
        monkeypatch.setattr(scores_importer, "_fetch_events", lambda *a, **k: event)
        res = import_scores(season, quick=True)
        m = Match.objects.get(round=rnd)
        assert m.home_score == 27
        assert m.away_score == 26
        assert res["updated"] >= 1

    def test_not_finished_match_not_updated(self, competition, monkeypatch):
        season = self._make_season(competition)
        rnd = self._make_round(season)
        event = [{
            "intRound": 1,
            "strHomeTeam": "Aviron Bayonnais",
            "strAwayTeam": "RC Toulonnais",
            "intHomeScore": None, "intAwayScore": None,
            "strStatus": "NS",
            "dateEvent": "2026-09-05", "strTime": "17:00:00",
        }]
        monkeypatch.setattr(scores_importer, "_fetch_events", lambda *a, **k: event)
        import_scores(season, quick=True)
        m = Match.objects.get(round=rnd)
        assert m.home_score is None
        assert m.away_score is None

    def test_aborted_rounds_targets_last_round(self, competition, monkeypatch):
        season = self._make_season(competition)
        Round.objects.create(season=season, number=1, date="2026-09-05", phase="POOL")
        Round.objects.create(season=season, number=2, date="2026-09-12", phase="POOL")
        captured = {}
        monkeypatch.setattr(
            scores_importer, "_fetch_events",
            lambda sportsdb_season, league, quick=False, extra_rounds=None: (
                captured.update(sportsdb_season=sportsdb_season, extra_rounds=extra_rounds) or []
            ),
        )
        import_scores(season, quick=True, aborted_rounds=1)
        assert captured["sportsdb_season"] == "2026-2027"
        assert captured["extra_rounds"] == [2]

    def test_aborted_rounds_zero_skips_rounds(self, competition, monkeypatch):
        season = self._make_season(competition)
        captured = {}
        monkeypatch.setattr(
            scores_importer, "_fetch_events",
            lambda sportsdb_season, league, quick=False, extra_rounds=None: (
                captured.update(extra_rounds=extra_rounds) or []
            ),
        )
        import_scores(season, quick=True, aborted_rounds=0)
        assert captured["extra_rounds"] is None