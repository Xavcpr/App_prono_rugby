import json
import logging
from datetime import datetime
from urllib.request import Request, urlopen
from django.utils import timezone
try:
    import pytz
    TZ = pytz.timezone("Europe/Paris")
except ImportError:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Paris")
from urllib.error import URLError

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Competition, Season, Round, Match, Team, MatchPhase

logger = logging.getLogger(__name__)

LEAGUE_ID = "4714"
SPORTSDB_SEASON = "2027"

TEAM_MAPPING = {
    "France Rugby": "France",
    "England Rugby": "Angleterre",
    "Italy Rugby": "Italie",
    "Ireland Rugby": "Irlande",
    "Scotland Rugby": "Ecosse",
    "Wales Rugby": "Pays de Galles",
}


def _api_key():
    return getattr(settings, "SPORTSDB_API_KEY", "3")


def _fetch_events():
    all_events = []
    for r in range(1, 8):
        url = f"https://www.thesportsdb.com/api/v1/json/{_api_key()}/eventsround.php?id={LEAGUE_ID}&r={r}&s={SPORTSDB_SEASON}"
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            events = data.get("events") or []
            if events:
                all_events.extend(events)
        except (URLError, json.JSONDecodeError) as e:
            logger.warning("Round %d: %s", r, e)
    return all_events


class Command(BaseCommand):
    help = "Crée la saison 6 Nations 2027 avec rounds et matchs depuis TheSportsDB"

    def handle(self, *args, **options):
        self.stdout.write("Récupération des événements TheSportsDB...")
        events = _fetch_events()
        if not events:
            self.stdout.write(self.style.ERROR("Aucun événement récupéré depuis l'API"))
            return

        self.stdout.write(f"{len(events)} événements trouvés")

        competition = Competition.objects.filter(name__iexact="6 nations").first()
        if not competition:
            self.stdout.write(self.style.ERROR("Compétition '6 Nations' introuvable"))
            return

        season, created = Season.objects.get_or_create(
            competition=competition,
            year="2027",
        )
        if created:
            self.stdout.write(f"Saison créée (ID={season.id})")
        else:
            self.stdout.write(f"Saison existante (ID={season.id})")

        six_nations_teams = Team.objects.filter(id__in=[15, 16, 17, 18, 19, 20])
        season.teams.set(six_nations_teams)
        self.stdout.write(f"Équipes liées : {[t.name for t in six_nations_teams]}")

        events_by_round = {}
        for e in events:
            r = int(e.get("intRound", 0))
            if r not in events_by_round:
                events_by_round[r] = []
            events_by_round[r].append(e)

        with transaction.atomic():
            for round_num in sorted(events_by_round.keys()):
                round_events = events_by_round[round_num]
                date_str = round_events[0].get("dateEvent", "")
                round_date = None
                if date_str:
                    try:
                        round_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except ValueError:
                        pass

                round_obj, created = Round.objects.get_or_create(
                    season=season,
                    number=round_num,
                    defaults={"date": round_date, "phase": MatchPhase.POOL},
                )
                if created:
                    self.stdout.write(f"  Round {round_num} créé (date={round_date})")

                for event in round_events:
                    home_api = event.get("strHomeTeam", "")
                    away_api = event.get("strAwayTeam", "")
                    home_name = TEAM_MAPPING.get(home_api)
                    away_name = TEAM_MAPPING.get(away_api)

                    if not home_name or not away_name:
                        self.stdout.write(self.style.WARNING(
                            f"    Équipes non mappées : {home_api} vs {away_api}"
                        ))
                        continue

                    home_team = Team.objects.filter(name=home_name).first()
                    away_team = Team.objects.filter(name=away_name).first()

                    if not home_team or not away_team:
                        self.stdout.write(self.style.WARNING(
                            f"    Équipes introuvables en DB : {home_name} vs {away_name}"
                        ))
                        continue

                    event_date = event.get("dateEvent", "")
                    event_time = event.get("strTime", "")
                    kickoff = None
                    if event_date and event_time:
                        try:
                            naive = datetime.strptime(
                                f"{event_date} {event_time}", "%Y-%m-%d %H:%M:%S"
                            )
                            kickoff = timezone.make_aware(naive, timezone=TZ)
                        except (ValueError, AttributeError):
                            try:
                                kickoff = timezone.make_aware(naive)
                            except Exception:
                                pass

                    match, created = Match.objects.get_or_create(
                        round=round_obj,
                        home_team=home_team,
                        away_team=away_team,
                        defaults={
                            "kickoff_at": kickoff,
                            "phase": MatchPhase.POOL,
                        },
                    )
                    if created:
                        self.stdout.write(
                            f"    Match créé : {home_name} vs {away_name} @ {kickoff}"
                        )
                    else:
                        if match.kickoff_at != kickoff:
                            match.kickoff_at = kickoff
                            match.save(update_fields=["kickoff_at"])

        self.stdout.write(self.style.SUCCESS("Terminé !"))
