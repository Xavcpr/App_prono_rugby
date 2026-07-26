import json, urllib.request, ssl, re
from datetime import datetime
from collections import defaultdict

import django
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

ctx = ssl.create_default_context()

# Mapping from InCrowd API team names → DB names
API_TEAM_MAP = {
    # name variants
    'Bath Rugby': 'Bath Rugby', 'Bath': 'Bath Rugby',
    'Bristol Bears': 'Bristol Bears', 'Bears': 'Bristol Bears',
    'Bulls': 'Bulls', 'Vodacom Bulls': 'Bulls',
    'Bordeaux-Begles': 'UBB', 'Bordeaux-Bègles': 'UBB',
    'Clermont Auvergne': 'Clermont',
    'DHL Stormers': 'Stormers', 'Stormers': 'Stormers',
    'Exeter Chiefs': None,  # not in DB
    'Glasgow Warriors': 'Glasgow', 'Glasgow': 'Glasgow',
    'Gloucester Rugby': 'Gloucester', 'Gloucester': 'Gloucester',
    'La Rochelle': 'La Rochelle', 'Stade Rochelais': 'La Rochelle',
    'Leicester Tigers': 'Leicester Tigers', 'Tigers': 'Leicester Tigers',
    'Leinster Rugby': 'Leinster', 'Leinster': 'Leinster',
    'Montpellier Hérault': 'Montpellier', 'Montpellier': 'Montpellier',
    'Northampton Saints': None, 'Saints': None,
    'Pau': 'Pau', 'Section Paloise': 'Pau',
    'Racing 92': 'Racing 92',
    'Sale Sharks': 'Sale Sharks',
    'Saracens': 'Saracens',
    'Sharks': 'The Sharks',
    'Stade Francais Paris': 'Stade français',
    'Stade Toulousain': 'Toulouse', 'Toulouse': 'Toulouse',
    'Cardiff Rugby': None, 'Cardiff': None,
    'Connacht Rugby': None, 'Connacht': None,
    'Munster Rugby': None, 'Munster': None,
    'Lions': None,
    'TBC': None,
}

ROUND_PHASE_MAP = {1: 'POOL', 2: 'POOL', 3: 'POOL', 4: 'POOL',
                    5: 'R16', 6: 'QF', 7: 'SF', 8: 'FINAL'}


def fetch_cc_matches():
    """Fetch all CC 2026/27 matches from InCrowd API."""
    url = 'https://rugby-union-feeds.incrowdsports.com/v1/matches?compId=1008&season=202601&provider=rugbyviz'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    matches = data if isinstance(data, list) else data.get('matches') or data.get('data') or []
    return matches


class Command(BaseCommand):
    help = "Scrape Champions Cup 2026/2027 fixtures from InCrowd Sports API"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        from core.models import Season, Round, Match, Team

        try:
            season = Season.objects.get(competition__name='Champions Cup', year='2026/2027')
        except Season.DoesNotExist:
            self.stderr.write("Season Champions Cup 2026/2027 not found.")
            return

        teams_map = {}
        for t in Team.objects.all():
            teams_map[t.name] = t

        self.stdout.write("Fetching CC 2026/27 from InCrowd API...")
        api_matches = fetch_cc_matches()
        self.stdout.write(f"Received {len(api_matches)} matches")

        if not api_matches:
            return

        # Group by round
        by_round = defaultdict(list)
        for m in api_matches:
            r = m.get('round')
            if r:
                by_round[r].append(m)

        missing_teams = set()
        parsed = []
        for round_num in sorted(by_round.keys()):
            phase = ROUND_PHASE_MAP.get(round_num, 'POOL')
            for m in by_round[round_num]:
                home = (m.get('homeTeam') or {}).get('name') or ''
                away = (m.get('awayTeam') or {}).get('name') or ''
                date_str = m.get('date') or ''
                status = m.get('status', 'fixture')

                home_db = API_TEAM_MAP.get(home)
                away_db = API_TEAM_MAP.get(away)

                if not home_db or not away_db:
                    if home and home != 'TBC':
                        missing_teams.add(home)
                    if away and away != 'TBC':
                        missing_teams.add(away)
                    continue

                if home_db not in teams_map:
                    missing_teams.add(f'{home} (→{home_db})')
                    continue
                if away_db not in teams_map:
                    missing_teams.add(f'{away} (→{away_db})')
                    continue

                kickoff = None
                if date_str:
                    try:
                        dt = datetime.strptime(date_str.replace('Z', '+0000')[:25],
                                               '%Y-%m-%dT%H:%M:%S.%f%z')
                        kickoff = dt
                    except (ValueError, IndexError):
                        try:
                            # Try without microseconds
                            cleaned = date_str.replace('Z', '+0000')
                            cleaned = cleaned[:22] + ':00' + cleaned[22:]
                            dt = datetime.strptime(cleaned, '%Y-%m-%dT%H:%M:%S%z')
                            kickoff = dt
                        except ValueError:
                            pass

                parsed.append({
                    'round_num': round_num,
                    'phase': phase,
                    'home': home_db,
                    'away': away_db,
                    'kickoff': kickoff,
                    'status': status,
                })

        if missing_teams:
            self.stderr.write(f"Missing/unmapped teams: {', '.join(sorted(missing_teams))}")
            if dry_run:
                pass
            else:
                self.stderr.write("Create a mapping entry and re-run.")
                return

        self.stdout.write(f"\nParsed {len(parsed)} matchable fixtures")

        if dry_run:
            self.stdout.write("\n=== DRY RUN ===")
            for p in parsed:
                dt = p['kickoff'].strftime('%Y-%m-%d %H:%M') if p['kickoff'] else '??'
                self.stdout.write(f"  R{p['round_num']} [{p['phase']}] {dt}  {p['home']} vs {p['away']}")
            return

        created = 0
        updated = 0
        skipped = 0

        for p in parsed:
            round_obj, _ = Round.objects.get_or_create(
                season=season, number=p['round_num'],
                defaults={'phase': p['phase']}
            )
            # Update phase if already exists
            if round_obj.phase != p['phase']:
                round_obj.phase = p['phase']
                round_obj.save()

            match, match_created = Match.objects.update_or_create(
                round=round_obj,
                home_team=teams_map[p['home']],
                away_team=teams_map[p['away']],
                defaults={'kickoff_at': p['kickoff']},
            )
            if match_created:
                created += 1
            else:
                if match.kickoff_at != p['kickoff']:
                    match.kickoff_at = p['kickoff']
                    match.save(update_fields=['kickoff_at'])
                    updated += 1
                else:
                    skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done: {created} created, {updated} updated, {skipped} skipped"
        ))
