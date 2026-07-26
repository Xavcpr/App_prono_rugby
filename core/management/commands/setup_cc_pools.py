from django.core.management.base import BaseCommand
from django.db import transaction


# Pools based on EPCR July 1 draw: https://www.epcrugby.com/champions-cup/content/official-investec-champions-cup-and-epcr-challenge-pools-confirmed-for-202627-season
POOLS_CC_2627 = {
    1: ['Leinster', 'Glasgow', 'Pau', 'Sale Sharks', 'Leicester Tigers', 'Clermont'],
    2: ['Toulouse', 'Lions', 'Saracens', 'La Rochelle', 'Exeter Chiefs', 'Connacht'],
    3: ['UBB', 'Stormers', 'Racing 92', 'Munster', 'Bristol Bears', 'Gloucester'],
    4: ['Northampton Saints', 'Bath Rugby', 'Cardiff', 'Montpellier', 'Stade français', 'Bulls'],
}


class Command(BaseCommand):
    help = "Assign CC 2026/2027 teams to pools for CompetitionTeam"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        from core.models import Season, Competition, CompetitionTeam, Team

        try:
            season = Season.objects.get(competition__name='Champions Cup', year='2026/2027')
        except Season.DoesNotExist:
            self.stderr.write("Season Champions Cup 2026/2027 not found.")
            return

        cc_comp = Competition.objects.get(name='Champions Cup')
        teams_map = {t.name: t for t in Team.objects.all()}

        created_count = 0
        missing = []

        for pool_num, team_names in POOLS_CC_2627.items():
            for name in team_names:
                team = teams_map.get(name)
                if not team:
                    for db_name, t in teams_map.items():
                        if name.lower() in db_name.lower() or db_name.lower() in name.lower():
                            team = t
                            break
                if not team:
                    if dry_run:
                        missing.append(f'{name} (pool {pool_num})')
                        continue
                    else:
                        # Auto-create missing teams
                        team = Team.objects.create(name=name)
                        teams_map[name] = team
                        self.stdout.write(f"  Created team: {name}")

                if dry_run:
                    self.stdout.write(f"  Pool {pool_num}: {team.name}")
                else:
                    with transaction.atomic():
                        _, ct_created = CompetitionTeam.objects.get_or_create(
                            competition=cc_comp,
                            season=season,
                            team=team,
                            defaults={'pool': pool_num},
                        )
                        if ct_created:
                            created_count += 1
                            if season not in team.seasons.all():
                                team.seasons.add(season)

        if missing:
            self.stderr.write(f"Dry-run missing teams: {', '.join(missing)}")

        if dry_run:
            self.stdout.write(f"\nWould create {sum(len(v) for v in POOLS_CC_2627.values())} CompetitionTeam entries")
        else:
            self.stdout.write(self.style.SUCCESS(f"Done: {created_count} CompetitionTeam entries created"))
