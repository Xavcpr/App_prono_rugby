import json, os
from datetime import datetime
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

FIXTURES_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'fixtures', 'cc_2627_fixtures.json'))

ROUND_PHASE_MAP = {1: 'POOL', 2: 'POOL', 3: 'POOL', 4: 'POOL',
                    5: 'R16', 6: 'QF', 7: 'SF', 8: 'FINAL'}

# Teams that exist in the API/JSON but definitely not in the DB — auto-created
NEW_TEAMS = [
    'Exeter Chiefs', 'Cardiff', 'Connacht', 'Munster',
    'Northampton Saints', 'Lions',
]

# JSON name → alternative DB names to try (for pre-existing teams)
ALIASES = {
    'Bath Rugby': ['Bath', 'Bath Rugby'],
    'Bristol Bears': ['Bristol', 'Bristol Bears'],
    'Bulls': ['Bulls', 'Vodacom Bulls', 'Blue Bulls'],
    'Leicester Tigers': ['Leicester', 'Leicester Tigers'],
    'Sale Sharks': ['Sale', 'Sale Sharks'],
}


def resolve_team(name, teams_map):
    """Find a team by name, trying exact match then aliases."""
    if name in teams_map:
        return teams_map[name]
    aliases = ALIASES.get(name, [])
    for alias in aliases:
        if alias in teams_map:
            return teams_map[alias]
    # Case-insensitive search
    for db_name, team in teams_map.items():
        if db_name.lower() == name.lower():
            return team
    # Partial match
    for db_name, team in teams_map.items():
        if name.lower() in db_name.lower() or db_name.lower() in name.lower():
            return team
    return None


def load_fixtures():
    with open(FIXTURES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


class Command(BaseCommand):
    help = "Load Champions Cup 2026/2027 fixtures from JSON file"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        from core.models import Season, Round, Match, Team, Competition

        try:
            season = Season.objects.get(competition__name='Champions Cup', year='2026/2027')
        except Season.DoesNotExist:
            self.stderr.write("Season Champions Cup 2026/2027 not found.")
            return

        cc_comp = Competition.objects.get(name='Champions Cup')
        teams_map = {t.name: t for t in Team.objects.all()}

        # Auto-create truly new teams and link to CC season
        for name in NEW_TEAMS:
            if resolve_team(name, teams_map) is None:
                if dry_run:
                    self.stdout.write(f"  Would create team: {name}")
                else:
                    t = Team.objects.create(name=name)
                    t.competitions.add(cc_comp)
                    t.seasons.add(season)
                    teams_map[name] = t
                    self.stdout.write(f"  Created team: {name}")

        self.stdout.write("Loading CC 2026/2027 fixtures...")
        fixtures = load_fixtures()
        self.stdout.write(f"Loaded {len(fixtures)} matches")

        if not fixtures:
            self.stderr.write("No fixtures found.")
            return

        # Verify with flexible matching
        if not dry_run:
            unresolved = set()
            for m in fixtures:
                for side in ('home', 'away'):
                    if resolve_team(m[side], teams_map) is None:
                        unresolved.add(m[side])
            if unresolved:
                self.stderr.write(f"Unresolvable teams: {', '.join(sorted(unresolved))}")
                self.stderr.write("Add them to ALIASES or NEW_TEAMS and re-run.")
                return

        if dry_run:
            self.stdout.write("\n=== DRY RUN ===")

        created = updated = 0
        by_round = defaultdict(list)
        for m in fixtures:
            by_round[m['round']].append(m)

        for round_num in sorted(by_round.keys()):
            matches_data = by_round[round_num]
            phase = ROUND_PHASE_MAP.get(round_num, 'POOL')
            round_obj, _ = Round.objects.get_or_create(
                season=season, number=round_num, defaults={'phase': phase})
            if round_obj.phase != phase:
                round_obj.phase = phase
                round_obj.save()

            if dry_run:
                self.stdout.write(f"\nR{round_num} [{phase}]:")

            for m in matches_data:
                kickoff = None
                if m.get('date'):
                    try:
                        dt = datetime.strptime(m['date'], '%Y-%m-%d %H:%M')
                        kickoff = timezone.make_aware(dt)
                    except ValueError:
                        pass

                home_team = resolve_team(m['home'], teams_map)
                away_team = resolve_team(m['away'], teams_map)

                if dry_run:
                    dt_str = m.get('date', '??')
                    h_name = home_team.name if home_team else m['home']
                    a_name = away_team.name if away_team else m['away']
                    self.stdout.write(f"  {dt_str}  {h_name} vs {a_name}")
                    continue

                _, match_created = Match.objects.update_or_create(
                    round=round_obj, home_team=home_team, away_team=away_team,
                    defaults={'kickoff_at': kickoff})
                if match_created:
                    created += 1
                else:
                    updated += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Done: {created} created, {updated} updated"))
