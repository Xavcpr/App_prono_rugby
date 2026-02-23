import csv
import os
import django

# Configuration de l'environnement Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Competition, Season, Round, Match, MatchPhase
def import_rdd(file_path):
    if not os.path.exists(file_path):
        print(f"Erreur : Le fichier {file_path} est introuvable.")
        return

    with open(file_path, mode='r', encoding='utf-8-sig') as f:
        # ON AJOUTE LE DELIMITER ICI
        reader = csv.DictReader(f, delimiter=';') 
        count = 0
        for row in reader:
            try:
                # Nettoyage du nom de la compétition (enlever espaces et points-virgules traînants)
                comp_name = row['competition'].strip()
                comp, _ = Competition.objects.get_or_create(name=comp_name)
                
                season_year = row['season'].strip()
                season, _ = Season.objects.get_or_create(competition=comp, year=season_year)
                
                # Gestion du Round : si ton CSV contient "J1", on extrait le chiffre 1
                raw_round = row['round'].strip()
                # On garde seulement les chiffres (ex: "J1" -> "1")
                round_num = int(''.join(filter(str.isdigit, raw_round)))
                
                round_obj, _ = Round.objects.get_or_create(season=season, number=round_num)
                
                Match.objects.create(
                    round=round_obj,
                    home_score=int(row['home_score']),
                    away_score=int(row['away_score']),
                    phase=MatchPhase.POOL,
                    weight=0
                )
                count += 1
                if count % 100 == 0:
                    print(f"{count} matchs importés...")
                    
            except Exception as e:
                # Affiche l'erreur pour aider au debug si besoin
                print(f"Erreur sur la ligne {count + 1}: {e} (Données: {row})")
                
        print(f"Succès : {count} matchs importés dans la base de données.")
        
if __name__ == "__main__":
    import_rdd('RDD_scores.csv')