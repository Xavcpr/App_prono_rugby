from .models import Round, Season
from django.utils import timezone

def global_params(request):
    now = timezone.now()
    # On récupère la saison active
    latest_season = Season.objects.order_by('-id').first()
    
    if latest_season:
        last_round = Round.objects.filter(
            season=latest_season,
            matches__kickoff_at__lt=now
        ).distinct().order_by('-number').first()
        
        if not last_round:
            last_round = Round.objects.filter(season=latest_season).order_by('number').first()
            
        return {
            'GLOBAL_LAST_ROUND_ID': last_round.id if last_round else None,
            'CURRENT_SEASON': latest_season
        }
    return {}