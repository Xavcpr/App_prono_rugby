import json, urllib.request, ssl, re
from datetime import datetime, date, time as dtime

import django
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

ctx = ssl.create_default_context()

MONTHS_FR = {
    'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
    'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
    'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12,
}

LNR_TO_DB = {
    'Aviron Bayonnais': 'Bayonne',
    'Castres Olympique': 'Castres',
    'ASM Clermont': 'Clermont',
    'Stade Rochelais': 'La Rochelle',
    'LOU Rugby': 'Lyon',
    'Montpellier Hérault Rugby': 'Montpellier',
    'Section Paloise': 'Pau',
    'USA Perpignan': 'Perpignan',
    'Racing 92': 'Racing 92',
    'Stade Français Paris': 'Stade français',
    'RC Toulon': 'Toulon',
    'Stade Toulousain': 'Toulouse',
    'Union Bordeaux-Bègles': 'UBB',
    'RC Vannes': 'Vannes',
}


def scrape_top14_2627():
    """Scrape all 26 journees from LNR website.
    Returns list of dicts: {journee, date_str, time_str, home, away}
    """
    all_matches = []
    for j in range(1, 27):
        url = f'https://top14.lnr.fr/calendrier-et-resultats/2026-2027/j{j}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                html = resp.read().decode('utf-8')
        except Exception as e:
            print(f"  J{j}: error fetching — {e}")
            break

        title_m = re.search(r'<title>(.*?)</title>', html)
        if not title_m or '404' in title_m.group(1):
            print(f"  J{j}: page not found, stopping")
            break

        # Extract date blocks: single day "samedi 05 septembre" or range "samedi 10 octobre – dimanche 11 octobre"
        date_blocks = list(re.finditer(
            r'calendar-results__fixture-date[^>]*>\s*(samedi|dimanche)\s+(\d+)\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)',
            html, re.IGNORECASE
        ))

        if not date_blocks:
            print(f"  J{j}: no dates found, skipping")
            continue

        # Extract all team names from club-line__name links
        all_team_names = re.findall(
            r'<a[^>]*class="club-line__name[^"]*"[^>]*>\s*([^<]+)\s*</a>', html
        )
        # Filter out rank numbers
        teams = [t.strip() for t in all_team_names
                 if not re.match(r'^\d+\s*$', t.strip()) and len(t.strip()) > 2]

        # Extract all times
        times = re.findall(r'<p class="match-line__time">(\d+)h(\d+)</p>', html)

        # Determine how many matches per day from the HTML structure
        # Split HTML by date blocks and count match-calendar-line within each section
        sections = re.split(r'calendar-results__fixture-date[^>]*>', html)
        matches_per_day = []
        for sec in sections[1:]:  # skip first section (before first date)
            cnt = len(re.findall(r'<div class="match-calendar-line', sec))
            matches_per_day.append(cnt)

        # Now assign teams+times to days
        team_idx = 0
        time_idx = 0
        for day_idx, num_matches in enumerate(matches_per_day):
            if day_idx >= len(date_blocks):
                break
            dm = date_blocks[day_idx]
            day_name = dm.group(1)
            day_num = int(dm.group(2))
            month_name = dm.group(3)
            month_num = MONTHS_FR[month_name.lower()]
            year = 2026 if month_num >= 9 else 2027
            date_str = f'{year}-{month_num:02d}-{day_num:02d}'

            for _ in range(num_matches):
                if team_idx + 1 >= len(teams):
                    break
                home_lnr = teams[team_idx]
                away_lnr = teams[team_idx + 1]
                team_idx += 2

                time_str = '00:00'
                if time_idx < len(times):
                    h, m = times[time_idx]
                    time_str = f'{h.zfill(2)}:{m.zfill(2)}'
                    time_idx += 1

                home_db = LNR_TO_DB.get(home_lnr, home_lnr)
                away_db = LNR_TO_DB.get(away_lnr, away_lnr)

                all_matches.append({
                    'journee': j,
                    'date_str': date_str,
                    'time_str': time_str,
                    'home': home_db,
                    'away': away_db,
                })

        print(f'  J{j}: {len(matches_per_day)} day(s), {sum(matches_per_day)} matches')

    return all_matches


class Command(BaseCommand):
    help = "Scrape Top 14 2026/2027 fixtures from LNR website and create/update matches"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Print matches without creating")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        from core.models import Season, Round, Match, Team

        try:
            season = Season.objects.get(competition__name='Top 14', year='2026/2027')
        except Season.DoesNotExist:
            self.stderr.write("Season Top 14 2026/2027 not found. Run create_top14_2627 first.")
            return

        # Build mapping from DB name -> Team
        teams_map = {}
        for t in Team.objects.all():
            teams_map[t.name] = t

        if 'Vannes' not in teams_map:
            self.stderr.write("Vannes team not found in DB; run migrations first.")
            return

        self.stdout.write(f"Scraping LNR website for Top 14 2026/2027...")
        scraped = scrape_top14_2627()
        self.stdout.write(f"Found {len(scraped)} matches total")

        if not scraped:
            self.stderr.write("No matches scraped. Aborting.")
            return

        # Verify all teams exist
        missing_teams = set()
        for m in scraped:
            for side in ('home', 'away'):
                if m[side] not in teams_map:
                    missing_teams.add(m[side])
        if missing_teams:
            self.stderr.write(f"Missing teams in DB: {', '.join(sorted(missing_teams))}")
            return

        if dry_run:
            self.stdout.write("\n=== DRY RUN — would create ===")
        else:
            self.stdout.write("\n=== Creating/updating ===")

        created = 0
        updated = 0
        skipped = 0
        errors = []

        # Group by journee
        from collections import defaultdict
        by_journee = defaultdict(list)
        for m in scraped:
            by_journee[m['journee']].append(m)

        for journee_num in sorted(by_journee.keys()):
            matches_data = by_journee[journee_num]

            # Get or create round
            round_obj, round_created = Round.objects.get_or_create(
                season=season, number=journee_num,
                defaults={'phase': 'POOL'}
            )

            if dry_run:
                self.stdout.write(f"\nRound {journee_num}:")

            for m in matches_data:
                kickoff_naive = datetime.strptime(f'{m["date_str"]} {m["time_str"]}', '%Y-%m-%d %H:%M')
                from datetime import timezone as dt_tz
                kickoff = timezone.make_aware(kickoff_naive, timezone=dt_tz.utc)

                home_team = teams_map[m['home']]
                away_team = teams_map[m['away']]

                if dry_run:
                    self.stdout.write(f"  {m['date_str']} {m['time_str']}  {m['home']} vs {m['away']}")
                    continue

                match, match_created = Match.objects.update_or_create(
                    round=round_obj,
                    home_team=home_team,
                    away_team=away_team,
                    defaults={'kickoff_at': kickoff},
                )
                if match_created:
                    created += 1
                else:
                    updated += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Done: {created} created, {updated} updated, {skipped} skipped"
            ))
