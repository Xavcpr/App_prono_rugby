import os
import django
from datetime import datetime
import pytz

# Configuration Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Competition, Round, Match

def update_multiple_rounds(updates):
    """
    Prend une liste de dictionnaires et met à jour chaque journée.
    """
    for item in updates:
        comp_name = item['comp']
        round_num = item['num']
        date_str = item['date']
        
        try:
            # 1. Trouver le Round
            target_round = Round.objects.filter(
                season__competition__name__icontains=comp_name, 
                number=round_num
            ).first()

            if not target_round:
                print(f"❌ J{round_num} ({comp_name}) : Non trouvée.")
                continue

            # 2. Gérer la date
            naive_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            aware_dt = pytz.timezone("Europe/Paris").localize(naive_dt)

            # 3. Mise à jour des matches
            updated_count = Match.objects.filter(round=target_round).update(kickoff_at=aware_dt)
            
            # 4. Optionnel : Mettre aussi à jour la date simplifiée sur le Round lui-même
            target_round.date = naive_dt.date()
            target_round.save()

            print(f"✅ J{round_num} ({comp_name}) : {updated_count} matches mis à jour au {date_str}.")

        except Exception as e:
            print(f"❌ Erreur sur J{round_num} ({comp_name}) : {e}")

if __name__ == "__main__":
    # Tu n'as qu'à remplir cette liste avec tes 15 journées
    data_to_update = [
        # TOP 14
        {'comp': "Top 14", 'num': 1, 'date': "2025-09-06 17:00"},
        {'comp': "Top 14", 'num': 2, 'date': "2025-09-13 17:00"},
        {'comp': "Top 14", 'num': 3, 'date': "2025-09-20 17:00"},
        {'comp': "Top 14", 'num': 4, 'date': "2025-09-27 17:00"},
        {'comp': "Top 14", 'num': 5, 'date': "2025-10-04 17:00"},
        {'comp': "Top 14", 'num': 6, 'date': "2025-10-11 17:00"},
        {'comp': "Top 14", 'num': 7, 'date': "2025-10-18 17:00"},
        {'comp': "Top 14", 'num': 8, 'date': "2025-10-25 17:00"},
        {'comp': "Top 14", 'num': 9, 'date': "2025-11-01 17:00"},
        {'comp': "Top 14", 'num': 10, 'date': "2025-11-22 17:00"},
        {'comp': "Top 14", 'num': 11, 'date': "2025-11-29 17:00"},
        {'comp': "Top 14", 'num': 12, 'date': "2025-12-20 17:00"},
        {'comp': "Top 14", 'num': 13, 'date': "2025-12-27 17:00"},
        {'comp': "Top 14", 'num': 14, 'date': "2026-01-03 17:00"},
        
        # CHAMPIONS CUP
        {'comp': "Champions Cup", 'num': 1, 'date': "2025-12-06 16:00"},
        {'comp': "Champions Cup", 'num': 2, 'date': "2025-12-13 16:00"},
        {'comp': "Champions Cup", 'num': 3, 'date': "2026-01-10 16:00"},
        {'comp': "Champions Cup", 'num': 4, 'date': "2026-01-17 16:00"},
        # ... Ajoute les autres ici
    ]

    update_multiple_rounds(data_to_update)