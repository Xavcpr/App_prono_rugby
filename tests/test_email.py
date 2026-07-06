import os
import pytest


class TestEmailService:

    def test_parse_hours_default(self):
        from core.services.email_service import _parse_hours
        hours = _parse_hours()
        assert sorted(hours, reverse=True) == hours
        assert 24 in hours
        assert 6 in hours

    def test_parse_hours_custom(self, monkeypatch):
        monkeypatch.setenv("REMINDER_HOURS", "48,24,6")
        from core.services.email_service import _parse_hours
        hours = _parse_hours()
        assert hours == [48, 24, 6]
