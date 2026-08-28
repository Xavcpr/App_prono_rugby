from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Season, Competition, Match
from core.services.scoring import _DEFAULT_SCORING_CONFIG
from core.management.commands.backfill_player_seasons import get_season_key


class Command(BaseCommand):
    help = (
        "Applique le nouveau barème (poids match 800, tout-pile 800, bonus défensif 20) "
        "aux saisons les plus récentes uniquement (ex: 2026/2027), sans toucher aux saisons passées."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Applique réellement les changements (sinon simulation uniquement)")
        parser.add_argument("--year", type=int, default=None,
                            help="Clé d'année cible (défaut: année max détectée, ex: 2026)")

    def handle(self, *args, **options):
        seasons = list(Season.objects.all())
        valid = [s for s in seasons if get_season_key(s.year).isdigit()]

        if options["year"] is not None:
            target_key = options["year"]
        else:
            target_key = max(int(get_season_key(s.year)) for s in valid)

        target = [s for s in valid if int(get_season_key(s.year)) == target_key]

        if not target:
            self.stdout.write(self.style.WARNING("Aucune saison ciblée."))
            return

        self.stdout.write(f"Clé d'année cible : {target_key}")
        for s in target:
            n = Match.objects.filter(round__season=s).count()
            cfg_state = "gelé (à réécrire)" if s.scoring_config else "vide (à écrire)"
            self.stdout.write(f"  - {s.competition.name} {s.year} : {n} matchs, config {cfg_state}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Simulation uniquement (--apply pour appliquer)."))
            return

        with transaction.atomic():
            for s in target:
                # 1. Config gelée de la saison -> nouveau barème
                s.scoring_config = _DEFAULT_SCORING_CONFIG
                s.save(update_fields=["scoring_config"])

                # 2. Poids des matchs -> 800
                n = Match.objects.filter(round__season=s).update(weight=800)

                # 3. Poids par défaut de la compétition -> 800
                Competition.objects.filter(id=s.competition_id).update(match_weight=800)

                self.stdout.write(self.style.SUCCESS(f"  + {s.competition.name} {s.year} : {n} matchs -> 800, config à jour"))