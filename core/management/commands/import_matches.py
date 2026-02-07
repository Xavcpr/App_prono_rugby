import openpyxl
from django.core.management.base import BaseCommand
from core.models import Player, Match, Prediction

class Command(BaseCommand):
    help = 'Importe les pronostics Rugby depuis le fichier Excel final'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str)

    def handle(self, *args, **kwargs):
        path = kwargs['file_path']
        try:
            wb = openpyxl.load_workbook(path)
            sheet = wb.active
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erreur fichier : {e}"))
            return

        success_count = 0
        
        # On commence à la ligne 2 pour ignorer l'entête
        for row in sheet.iter_rows(min_row=2, values_only=True):
            # Mapping exact de vos colonnes :
            # 0:Comp, 1:Saison, 2:Round, 3:Joueur, 4:Home, 5:Away, 6:HBO, 7:HPred, 8:APred, 9:ABO
            comp, season, rnd, player_name, home, away, h_bo, h_score, a_score, a_bo = row

            if not player_name: continue # Saute les lignes vides

            try:
                # 1. Récupération du joueur
                player = Player.objects.get(name__iexact=player_name.strip())

                # 2. Récupération du match (Recherche précise)
                match = Match.objects.get(
                    round__season__competition__name__iexact=comp.strip(),
                    round__season__year=str(season).strip(),
                    round__number=int(rnd),
                    home_team__name__iexact=home.strip(),
                    away_team__name__iexact=away.strip()
                )

                # 3. Création ou Mise à jour
                Prediction.objects.update_or_create(
                    player=player,
                    match=match,
                    defaults={
                        'home_score_pred': h_score,
                        'away_score_pred': a_score,
                        'bonus_home_pred': bool(h_bo), # Convertit 1/0 ou X/vide en True/False
                        'bonus_away_pred': bool(a_bo),
                    }
                )
                success_count += 1

            except Player.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Joueur non trouvé : {player_name}"))
            except Match.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Match non trouvé : {home} vs {away} (Rnd {rnd})"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erreur ligne {home}-{away} : {e}"))

        self.stdout.write(self.style.SUCCESS(f"Import terminé ! {success_count} pronostics enregistrés."))