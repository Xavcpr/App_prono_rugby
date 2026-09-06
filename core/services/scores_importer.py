import json
import os
import time
import logging
import unicodedata
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import Match, Round, Season, Team

logger = logging.getLogger(__name__)

MAPPING_PATH = os.path.join(os.path.dirname(__file__), "team_mapping.json")
MAX_ROUNDS = 30
RETRY_DELAY = 5
MAX_RETRIES = 3

COMPETITIONS = {
    "Top 14": {"league_id": "4430"},
    "Champions Cup": {"league_id": "4550"},
    "6 Nations": {"league_id": "4714"},
}


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


def _sportsdb_season(season):
    if season.competition.name == "6 Nations":
        return season.year
    return season.year.replace("/", "-")


def _fetch_events(sportsdb_season, league_id, quick=False, extra_rounds=None):
    """Récupère les événements TheSportsDB pour une saison.

    Utilise l'endpoint 'eventsseason' si disponible (rapide), puis complète
    éventuellement avec les journées fournies dans ``extra_rounds`` (endpoint
    'eventsround', plus fiable mais 1 requête par journée).
    """
    events = []
    seen = set()
    data = _request(f"{_api_base()}/eventsseason.php?id={league_id}&s={sportsdb_season}")
    if data and data.get("events"):
        events = data["events"]
        for ev in events:
            seen.add((ev.get("intRound"), ev.get("intHomeTeam"), ev.get("intAwayTeam")))
        logger.info("Season endpoint returned %d events", len(events))

    if extra_rounds:
        for r in extra_rounds:
            url = f"{_api_base()}/eventsround.php?id={league_id}&r={r}&s={sportsdb_season}"
            data = _request(url)
            if not data:
                continue
            batch = data.get("events") or []
            if not batch:
                continue
            added = 0
            for ev in batch:
                key = (ev.get("intRound"), ev.get("intHomeTeam"), ev.get("intAwayTeam"))
                if key not in seen:
                    events.append(ev)
                    seen.add(key)
                    added += 1
            logger.info("Round %d: %d events (+%d nouveaux)", r, len(batch), added)

    if events:
        return events

    if quick:
        return []

    for r in range(1, MAX_ROUNDS + 1):
        url = f"{_api_base()}/eventsround.php?id={league_id}&r={r}&s={sportsdb_season}"
        data = _request(url)
        if not data:
            continue
        batch = data.get("events") or []
        if not batch:
            continue
        for ev in batch:
            key = (ev.get("intRound"), ev.get("intHomeTeam"), ev.get("intAwayTeam"))
            if key not in seen:
                events.append(ev)
                seen.add(key)
        logger.info("Round %d: %d events", r, len(batch))
        time.sleep(0.5)
    return events


def _team_name_to_db(sportsdb_name, reverse_map):
    clean = _normalize(sportsdb_name)
    for norm_key, db_name in reverse_map.items():
        if norm_key == clean:
            return db_name
    return None


def _parse_kickoff(event_date_str, event_time_str):
    if not event_date_str:
        return None
    dt_str = event_date_str
    if event_time_str:
        dt_str += f" {event_time_str}"
        fmt = "%Y-%m-%d %H:%M:%S"
    else:
        fmt = "%Y-%m-%d"
    try:
        naive = datetime.strptime(dt_str, fmt)
        return timezone.make_aware(naive, timezone=timezone.get_current_timezone())
    except (ValueError, AttributeError):
        return None


def _resolve_teams(home_sportsdb, away_sportsdb, db_teams_by_name, auto_create=False):
    reverse_map = _build_reverse_map()
    home_db_name = _team_name_to_db(home_sportsdb, reverse_map)
    away_db_name = _team_name_to_db(away_sportsdb, reverse_map)

    # Auto-create team if missing
    def get_or_create(name, sportsdb_name):
        if name:
            key = _normalize(name)
            team = db_teams_by_name.get(key)
            if team:
                return team
        if auto_create:
            team, _ = Team.objects.get_or_create(name=sportsdb_name)
            db_teams_by_name[_normalize(team.name)] = team
            # Add to mapping for next time
            mapping = _load_mapping()
            if sportsdb_name not in mapping:
                mapping[sportsdb_name] = sportsdb_name
                with open(MAPPING_PATH, "w", encoding="utf-8") as f:
                    json.dump(mapping, f, indent=2, ensure_ascii=False)
            logger.info("Auto-created team: %s", sportsdb_name)
            return team
        return None

    home_team = get_or_create(home_db_name, home_sportsdb)
    away_team = get_or_create(away_db_name, away_sportsdb)

    if not home_team or not away_team:
        logger.warning("Unmapped teams: %s / %s", home_sportsdb, away_sportsdb)

    return home_team, away_team


@transaction.atomic
def import_scores(season: Season, dry_run: bool = False, quick: bool = False, create_matches: bool = True, auto_create_teams: bool = False, aborted_rounds: int = 0):
    league_id = COMPETITIONS.get(season.competition.name, {}).get("league_id")
    if not league_id:
        return {"status": "error", "message": f"Unknown competition: {season.competition.name}"}

    sportsdb_season = _sportsdb_season(season)
    if aborted_rounds > 0:
        latest = (Round.objects.filter(season=season).order_by("-number")
                  .values_list("number", flat=True).first()) or 0
        extra_rounds = list(range(max(latest - aborted_rounds + 1, 1), latest + 1))
    else:
        extra_rounds = None
    events = _fetch_events(sportsdb_season, league_id, quick=quick, extra_rounds=extra_rounds)

    if not events:
        return {"status": "error", "message": "No events fetched from API"}

    all_teams = Team.objects.all()
    db_teams_by_name = {}
    for t in all_teams:
        key = _normalize(t.name)
        db_teams_by_name[key] = t

    # Preload all rounds for this season
    rounds_by_num = {r.number: r for r in Round.objects.filter(season=season)}

    created = 0
    updated = 0
    skipped = 0
    results = []

    for event in events:
        round_num = event.get("intRound")
        if not round_num:
            skipped += 1
            continue
        round_num = int(round_num)

        round_obj = rounds_by_num.get(round_num)
        if not round_obj:
            logger.warning("Round %d not found for season %s", round_num, season)
            skipped += 1
            continue

        home_sportsdb = event.get("strHomeTeam", "")
        away_sportsdb = event.get("strAwayTeam", "")
        home_team, away_team = _resolve_teams(home_sportsdb, away_sportsdb, db_teams_by_name, auto_create=auto_create_teams)
        if not home_team or not away_team:
            skipped += 1
            continue

        kickoff = _parse_kickoff(event.get("dateEvent", ""), event.get("strTime", ""))

        # Find existing match
        match = Match.objects.filter(
            round=round_obj, home_team=home_team, away_team=away_team
        ).first()

        if match:
            # Update kickoff_at if changed
            changed = False
            if kickoff and match.kickoff_at != kickoff:
                if dry_run:
                    results.append(f"[DRY-RUN] MÀJ horaire {match}: {match.kickoff_at} → {kickoff}")
                else:
                    match.kickoff_at = kickoff
                    changed = True
                updated += 1
        else:
            # Create new match
            if dry_run:
                results.append(f"[DRY-RUN] Création match : {home_team} vs {away_team} @ {kickoff} (R{round_num})")
                created += 1
                continue
            match = Match.objects.create(
                round=round_obj,
                home_team=home_team,
                away_team=away_team,
                kickoff_at=kickoff,
                phase=round_obj.phase,
            )
            results.append(f"[CREATED] {match} @ {kickoff}")
            created += 1
            changed = False

        # Scores
        int_home = event.get("intHomeScore")
        int_away = event.get("intAwayScore")
        status = event.get("strStatus", "")

        if int_home and int_away and status == "FT":
            try:
                home_score = int(int_home)
                away_score = int(int_away)
            except (ValueError, TypeError):
                skipped += 1
                continue

            if match.home_score != home_score or match.away_score != away_score:
                if dry_run:
                    results.append(f"[DRY-RUN] Score {match}: {match.home_score or '-'}-{match.away_score or '-'} → {home_score}-{away_score}")
                else:
                    match.home_score = home_score
                    match.away_score = away_score
                    changed = True
                    results.append(f"[SCORE] {match}: {home_score}-{away_score}")
                updated += 1
            else:
                skipped += 1
        else:
            skipped += 1

        if changed and not dry_run:
            match.save()

    return {
        "status": "ok",
        "updated": updated,
        "skipped": skipped,
        "created": created,
        "results": results,
        "competition": season.competition.name,
    }
