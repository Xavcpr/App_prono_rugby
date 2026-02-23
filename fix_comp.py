import os
import django

# Configuration de l'environnement Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Competition, Season

def merge_competitions():
    try:
        # 1. On récupère les deux objets
        # Attention aux noms exacts que tu vois dans ton filtre
        wrong_comp = Competition.objects.get(name="6 nations")
        correct_comp = Competition.objects.get(name="Tournoi des 6 nations")

        print(f"Fusion de '{wrong_comp.name}' vers '{correct_comp.name}'...")

        # 2. On récupère toutes les saisons de la mauvaise compétition
        seasons_to_move = Season.objects.filter(competition=wrong_comp)

        for season in seasons_to_move:
            # On vérifie si la saison existe déjà dans la bonne comp pour éviter les doublons
            existing_season = Season.objects.filter(competition=correct_comp, year=season.year).first()
            
            if existing_season:
                # Si la saison existe déjà, on pourrait fusionner les rounds, 
                # mais si c'est juste ton import RDD, on peut supprimer la saison en trop
                print(f"La saison {season.year} existe déjà dans la cible. Suppression du doublon.")
                season.delete() 
            else:
                # Sinon on change juste le parent
                season.competition = correct_comp
                season.save()
                print(f"Saison {season.year} déplacée.")

        # 3. Une fois vide, on supprime la mauvaise compétition
        wrong_comp.delete()
        print("Nettoyage terminé avec succès !")

    except Competition.DoesNotExist:
        print("Erreur : L'une des deux compétitions n'a pas été trouvée. Vérifie l'orthographe exacte.")
    except Exception as e:
        print(f"Une erreur est survenue : {e}")

if __name__ == "__main__":
    merge_competitions()