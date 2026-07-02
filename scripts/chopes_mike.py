"""
Script one-off : affiche les chopes de Mike par journée sur la saison en cours.
Usage : python manage.py runscript scripts.chopes_mike  (si django-extensions)
   ou : python scripts/chopes_mike.py  (direct, avec DJANGO_SETTINGS_MODULE)

Lance-le depuis le venv du projet.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.utils import timezone
from core.models import Player, DailyScore, Round

now = timezone.now()
current_year = now.year
if now.month < 8:
    start = timezone.datetime(current_year - 1, 8, 1)
    end = timezone.datetime(current_year, 8, 1)
else:
    start = timezone.datetime(current_year, 8, 1)
    end = timezone.datetime(current_year + 1, 8, 1)

mike = Player.objects.filter(name__icontains="mike").first()
if not mike:
    print("Mike introuvable")
    sys.exit(1)

dailyscores = DailyScore.objects.filter(
    user=mike.user,
    round__date__range=(start.date(), end.date()),
).select_related("round__season__competition").order_by("round__date", "round__number")

print(f"Chopes de {mike.name} ({mike.user.username}) — saison {current_year-1}/{current_year}")
print(f"{'Date':<14} {'Compétition':<16} {'Journée':<10} {'Points':>6} {'Rang':>5} {'Chopes':>6}")
print("-" * 65)

for ds in dailyscores:
    # Calcul du rang de Mike dans ce round
    day_scores = list(DailyScore.objects.filter(round=ds.round).order_by("-points"))
    rank = 1
    prev_pts = None
    for idx, s in enumerate(day_scores):
        if s.points != prev_pts:
            rank = idx + 1
            prev_pts = s.points
        if s.id == ds.id:
            break

    if ds.points > 0 and rank == 1:
        chopes = 3
    elif ds.points > 0 and rank == 2:
        chopes = 2
    elif ds.points > 0 and rank == 3:
        chopes = 1
    else:
        chopes = 0

    label = str(ds.round)
    print(f"{ds.round.date or '':<14} {ds.round.season.competition.name:<16} {label:<10} {ds.points:>6} {rank:>5} {chopes:>6}")

total_chopes = sum(
    3 if ds.points > 0 and rank == 1
    else 2 if ds.points > 0 and rank == 2
    else 1 if ds.points > 0 and rank == 3
    else 0
    for ds in dailyscores
    for rank in [
        next(
            idx + 1
            for idx, s in enumerate(
                sorted(
                    DailyScore.objects.filter(round=ds.round).values_list("points", flat=True),
                    reverse=True,
                )
            )
            if s == ds.points
        )
    ]
)
print("-" * 65)
# Re-calcul propre
total = 0
for ds in dailyscores:
    all_pts = sorted(
        DailyScore.objects.filter(round=ds.round).values_list("points", flat=True),
        reverse=True,
    )
    r = 1
    prev = None
    for idx, p in enumerate(all_pts):
        if p != prev:
            r = idx + 1
            prev = p
        if p == ds.points:
            break
    if ds.points > 0 and r == 1:
        total += 3
    elif ds.points > 0 and r == 2:
        total += 2
    elif ds.points > 0 and r == 3:
        total += 1

print(f"{'TOTAL':>14} {'':<16} {'':<10} {'':>6} {'':>5} {total:>6}")
