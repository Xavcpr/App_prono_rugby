import pytest
from django.core.management import call_command

from core.models import Season


@pytest.mark.django_db
class TestImportScoresCommand:
    def _setup(self, competition):
        archive_top14 = Season.objects.create(competition=competition, year="2005-2006")
        archive_top14_2 = Season.objects.create(competition=competition, year="2024-2025")
        prono_season = Season.objects.create(competition=competition, year="2025/2026")
        current_season = Season.objects.create(competition=competition, year="2026/2027")
        return [archive_top14, archive_top14_2, prono_season, current_season]

    def _fake(self, captured):
        def fake(season, **kw):
            captured.append(season.year)
            return {"status": "ok", "results": [], "created": 0, "updated": 0, "skipped": 0}
        return fake

    def test_default_only_prono_era(self, competition, monkeypatch):
        self._setup(competition)
        captured = []
        monkeypatch.setattr(
            "core.management.commands.import_scores.import_scores",
            self._fake(captured),
        )
        call_command("import_scores", competition="Top 14")
        assert sorted(captured) == ["2025/2026", "2026/2027"]

    def test_explicit_archive_season_allowed(self, competition, monkeypatch):
        s1, *_ = self._setup(competition)
        captured = []
        monkeypatch.setattr(
            "core.management.commands.import_scores.import_scores",
            self._fake(captured),
        )
        call_command("import_scores", season="2005-2006")
        assert captured == [s1.year]

    def test_all_seasons_flag(self, competition, monkeypatch):
        self._setup(competition)
        captured = []
        monkeypatch.setattr(
            "core.management.commands.import_scores.import_scores",
            self._fake(captured),
        )
        call_command("import_scores", competition="Top 14", all_seasons=True)
        assert sorted(captured) == ["2005-2006", "2024-2025", "2025/2026", "2026/2027"]