from .models import Match, Round, Season
from .version import __version__
from django.utils import timezone

def global_params(request):
    now = timezone.now()
    # On récupère la saison active
    latest_season = Season.objects.order_by('-id').first()

    # Journée la plus récente : celle du match déjà lancé ayant le kickoff le plus avancé
    last_match = Match.objects.filter(kickoff_at__lte=now).order_by('-kickoff_at').first()
    last_round = last_match.round if last_match else None

    if not last_round and latest_season:
        last_round = Round.objects.filter(season=latest_season).order_by('number').first()

    return {
        'GLOBAL_LAST_ROUND_ID': last_round.id if last_round else None,
        'CURRENT_SEASON': latest_season,
        'APP_VERSION': __version__,
    }