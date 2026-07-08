import json
import os
import time
import logging
import unicodedata
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

from django.conf import settings
from django.db import transaction

from core.models import Match, Season, Team

logger = logging.getLogger(__name__)

SPORTSDB_LEAGUE_ID = "4430"
MAPPING_PATH = os.path.join(os.path.dirname(__file__), "team_mapping.json")
MAX_ROUNDS = 30
RETRY_DELAY = 5
MAX_RETRIES = 3


def _api_key():
    return getattr(settings, "SPORTSDB_API_KEY", "3")


def _api_base():
    return f"https://www.thesportsdb.com/api/v1/json/{_api_key()}"


def _normalize(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower().strip()


def _load_mapping():
    with open(MAPPING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_reverse_map():
    mapping = _load_mapping()
    return {_normalize(v): k for k, v in mapping.items()}


def _request(url):
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            code = getattr(e, "code", 0)
            if code == 429:
                logger.warning("Rate limited (429), waiting %ds...", RETRY_DELAY * (attempt + 1))
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            logger.warning("Request failed: %s", e)
            return None
        except json.JSONDecodeError:
            return None
    return None


def _fetch_events(sportsdb_season):
    url = f"{_api_base()}/eventsseason.php?id={SPORTSDB_LEAGUE_ID}&s={sportsdb_season}"
    data = _request(url)
    if data:
        events = data.get("events") or []
        if len(events) >= 14:
            logger.info("Season endpoint returned %d events", len(events))
            return events

    events = []
    for r in range(1, MAX_ROUNDS + 1):
        url = f"{_api_base()}/eventsround.php?id={SPORTSDB_LEAGUE_ID}&r={r}&s={sportsdb_season}"
        data = _request(url)
        if not data:
            continue
        batch = data.get("events") or []
        if not batch:
            continue
        events.extend(batch)
        logger.info("Round %d: %d events", r, len(batch))
        time.sleep(0.5)
    return events


def _team_name_to_db(sportsdb_name, reverse_map):
    clean = _normalize(sportsdb_name)
    for norm_key, db_name in reverse_map.items():
        if norm_key == clean:
            return db_name
    return None


def _match_event_to_db_match(event, db_teams_by_name, day_window=1):
    event_date_str = event.get("dateEvent", "")
    if not event_date_str:
        return None

    try:
        event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    home_sportsdb = event.get("strHomeTeam", "")
    away_sportsdb = event.get("strAwayTeam", "")

    reverse_map = _build_reverse_map()
    home_db_name = _team_name_to_db(home_sportsdb, reverse_map)
    away_db_name = _team_name_to_db(away_sportsdb, reverse_map)

    if not home_db_name or not away_db_name:
        logger.warning("Unmapped teams: %s / %s", home_sportsdb, away_sportsdb)
        return None

    home_key = "".join(c for c in unicodedata.normalize("NFD", home_db_name) if unicodedata.category(c) != "Mn").lower()
    away_key = "".join(c for c in unicodedata.normalize("NFD", away_db_name) if unicodedata.category(c) != "Mn").lower()
    home_team = db_teams_by_name.get(home_key)
    away_team = db_teams_by_name.get(away_key)

    if not home_team or not away_team:
        logger.warning("DB teams not found: %s / %s", home_db_name, away_db_name)
        return None

    start = event_date - timedelta(days=day_window)
    end = event_date + timedelta(days=day_window)

    match = Match.objects.filter(
        home_team=home_team,
        away_team=away_team,
        kickoff_at__date__range=(start, end),
    ).first()

    return match


@transaction.atomic
def import_scores(season: Season, dry_run: bool = False):
    sportsdb_season = season.year.replace("/", "-")
    events = _fetch_events_all_rounds(sportsdb_season)

    if not events:
        return {"status": "error", "message": "No events fetched from API"}

    from unicodedata import category as uc_category
    all_teams = Team.objects.all()
    db_teams_by_name = {}
    for t in all_teams:
        key = "".join(c for c in unicodedata.normalize("NFD", t.name) if unicodedata.category(c) != "Mn").lower()
        db_teams_by_name[key] = t

    updated = 0
    skipped = 0
    results = []

    for event in events:
        int_home = event.get("intHomeScore")
        int_away = event.get("intAwayScore")
        status = event.get("strStatus", "")

        if not int_home or not int_away or status != "FT":
            skipped += 1
            continue

        try:
            home_score = int(int_home)
            away_score = int(int_away)
        except (ValueError, TypeError):
            skipped += 1
            continue

        match = _match_event_to_db_match(event, db_teams_by_name)

        if not match:
            skipped += 1
            continue

        if match.home_score is not None and match.away_score is not None:
            skipped += 1
            continue

        if dry_run:
            results.append(f"[DRY-RUN] {match}: {home_score}-{away_score}")
        else:
            match.home_score = home_score
            match.away_score = away_score
            match.save()
            results.append(f"[UPDATED] {match}: {home_score}-{away_score}")
        updated += 1

    return {
        "status": "ok",
        "updated": updated,
        "skipped": skipped,
        "results": results,
    }
