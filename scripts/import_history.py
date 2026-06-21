import csv
import os
import django

# Configuration de l'environnement Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings') # <--- REMPLACE PAR LE NOM DE TON DOSSIER SETTINGS
django.setup()

from core.models import SeasonHistory, User # <--- REMPLACE PAR TON NOM D'APP

def run_import():
    file_path = 'all_time.csv'
    if not os.path.exists(file_path):
        print(f"Erreur : {file_path} introuvable.")
        return

    # utf-8-sig permet de nettoyer le "BOM" (caractère invisible au début des fichiers Excel)
    with open(file_path, newline='', encoding='utf-8-sig') as csvfile:
        # On spécifie le délimiteur point-virgule
        reader = csv.DictReader(csvfile, delimiter=';')
        count = 0
        for row in reader:
            # On utilise .get() pour éviter le KeyError si une colonne manque
            nom_joueur = row.get('Joueur', '').strip()
            annee = row.get('Année') or row.get('Annee') # Gère les deux cas
            
            if not nom_joueur or not annee:
                continue

            user = User.objects.filter(username__iexact=nom_joueur).first()
            
            SeasonHistory.objects.update_or_create(
                season_year=int(annee),
                player_name_legacy=nom_joueur if not user else None,
                user=user, # On met à jour le lien si l'user existe
                defaults={
                    'rank': int(row['Rang']),
                    'total_players': int(row['Nb_joueurs']),
                }
            )
            count += 1
    print(f"✅ Import terminé : {count} lignes traitées.")

if __name__ == "__main__":
    run_import()