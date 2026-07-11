import json
import os
import unicodedata
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Season, Team

logger = logging.getLogger(__name__)

MAPPING_PATH = os.path.join(os.path.dirname(__file__), "../../services/team_mapping.json")

CC_TEAMS = [
    "Clermont",
    "Bayonne",
    "Castres",
    "La Rochelle",
    "Pau",
    "UBB",
    "Bath",
    "Bristol",
    "Blue Bulls",
    "Cardiff",
    "Connacht",
    "Edinburgh",
    "Exeter",
    "Glasgow",
    "Gloucester",
    "Harlequins",
    "Leicester",
    "Leinster",
    "Lions",
    "Lyon",
    "Munster",
    "Montpellier",
    "Montauban",
    "Northampton",
    "Perpignan",
    "Racing 92",
    "Sale",
    "Saracens",
    "Scarlets",
    "Sharks",
    "Stade français",
    "Stormers",
    "Toulon",
    "Toulouse",
    "Vannes",
]


def _normalize(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower().strip()


class Command(BaseCommand):
    help = "Ajoute les équipes de Champions Cup manquantes (DB + mapping)"

    def add_arguments(self, parser):
        parser.add_argument("--season-id", type=int, default=None)

    def handle(self, *args, **options):
        season_id = options.get("season_id")

        # Load mapping
        mapping = {}
        if os.path.exists(MAPPING_PATH):
            with open(MAPPING_PATH, "r", encoding="utf-8") as f:
                mapping = json.load(f)

        # Build reverse map (normalized sportsdb_name -> db_name)
        reverse_map = {}
        for db_name, sportsdb_name in mapping.items():
            reverse_map[_normalize(sportsdb_name)] = db_name

        # Build DB team lookup (normalized name -> Team)
        all_teams = Team.objects.all()
        db_by_norm = {}
        for t in all_teams:
            db_by_norm[_normalize(t.name)] = t

        added = 0
        existed = 0
        skipped = 0
        new_entries = {}

        for sportsdb_name in CC_TEAMS:
            norm = _normalize(sportsdb_name)

            # Already mapped to an existing DB team?
            db_name = reverse_map.get(norm)
            if db_name:
                team = db_by_norm.get(_normalize(db_name))
                if team:
                    skipped += 1
                    continue

            # Already exists directly in DB?
            team = db_by_norm.get(norm)
            if team:
                existed += 1
                if sportsdb_name not in mapping:
                    new_entries[sportsdb_name] = sportsdb_name
                continue

            # Create new team
            team = Team.objects.create(name=sportsdb_name)
            db_by_norm[_normalize(team.name)] = team
            self.stdout.write(f"  Créée : {sportsdb_name} (ID={team.id})")
            added += 1

            if sportsdb_name not in mapping:
                new_entries[sportsdb_name] = sportsdb_name

        # Save mapping
        if new_entries:
            mapping.update(new_entries)
            with open(MAPPING_PATH, "w", encoding="utf-8") as f:
                json.dump(mapping, f, indent=2, ensure_ascii=False)
            self.stdout.write(f"  Mapping mis à jour : {len(new_entries)} entrées")

        self.stdout.write(self.style.SUCCESS(
            f"{added} créées, {existed} existantes, {skipped} déjà mappées"
        ))

        # Link to season
        if season_id:
            season = Season.objects.filter(id=season_id).first()
            if season:
                linked = set(season.teams.values_list("id", flat=True))
                to_link = [t for t in all_teams if t.id not in linked and _normalize(t.name) in {_normalize(n) for n in CC_TEAMS}]
                if to_link:
                    season.teams.add(*to_link)
                    self.stdout.write(f"{len(to_link)} équipes liées à la saison {season.id}")
            else:
                self.stdout.write(self.style.WARNING(f"Saison ID={season_id} introuvable"))
