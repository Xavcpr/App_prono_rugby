from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


def _format_date(d):
    return d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d)


def send_round_reminders():
    today = timezone.now().date()
    from core.models import Round, Match, Prediction, Player

    upcoming_rounds = Round.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(hours=26),
    ).select_related("season__competition")

    for rnd in upcoming_rounds:
        days_until = (rnd.date - today).days
        hours_until = days_until * 24
        if not (23 <= hours_until <= 25) and not (5 <= hours_until <= 7):
            continue

        label = "H-24" if hours_until > 12 else "H-6"
        players = Player.objects.filter(
            user__isnull=False, user__email__gt=""
        ).select_related("user")

        for player in players:
            has_pred = Prediction.objects.filter(
                player=player, match__round=rnd
            ).exists()
            if has_pred:
                continue

            subject = f"[Pronos] {label} - {rnd.season.competition.name} J{rnd.number}"
            message = (
                f"Salut {player.user.username},\n\n"
                f"Tu n'as pas encore fait tes pronostics pour "
                f"{rnd.season.competition.name} Journée {rnd.number} "
                f"({_format_date(rnd.date)}).\n\n"
                f"Va sur : https://xavfabiani.pythonanywhere.com/pronos/\n\n"
                f"À très vite !"
            )
            send_mail(
                subject, message, settings.DEFAULT_FROM_EMAIL, [player.user.email]
            )


def notify_new_round(round_obj):
    subject = (
        f"[Pronos] Nouvelle journée : "
        f"{round_obj.season.competition.name} J{round_obj.number}"
    )
    message = (
        f"Les pronostics pour {round_obj.season.competition.name} "
        f"Journée {round_obj.number} ({_format_date(round_obj.date)}) "
        f"sont ouverts !\n\n"
        f"Va sur : https://xavfabiani.pythonanywhere.com/pronos/\n\n"
        f"À très vite !"
    )
    users = (
        User.objects.filter(player__isnull=False, email__gt="")
        .values_list("email", flat=True)
    )
    if users:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, list(users))
