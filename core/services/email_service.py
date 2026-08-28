import os
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


def _format_date(d):
    return d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d)


def _parse_hours():
    raw = os.environ.get("REMINDER_HOURS", "24,6")
    return sorted([int(h) for h in raw.split(",") if h.strip().isdigit()], reverse=True)


def send_round_reminders():
    today = timezone.now().date()
    trigger_hours = _parse_hours()
    from core.models import Round, Prediction, Player

    max_hours = max(trigger_hours)
    upcoming_rounds = Round.objects.filter(
        date__gte=today,
        date__lte=today + timedelta(hours=max_hours + 2),
    ).select_related("season__competition")

    for rnd in upcoming_rounds:
        hours_until = (rnd.date - today).total_seconds() / 3600
        matched_hour = None
        for h in trigger_hours:
            if abs(hours_until - h) <= 2:
                matched_hour = h
                break
        if matched_hour is None:
            continue

        hour_str = str(int(matched_hour))
        already_sent = hour_str in rnd.reminder_hours_sent
        if already_sent:
            continue

        label = f"H-{hour_str}"
        players = Player.objects.filter(user__isnull=False).select_related("user")

        missing_players = []
        sent_count = 0
        for player in players:
            recipient = (player.alert_email or player.user.email).strip()
            if not recipient:
                continue
            has_pred = Prediction.objects.filter(
                player=player, match__round=rnd
            ).exists()
            if has_pred:
                continue
            missing_players.append(player)
            subject = f"[Pronos] {label} - {rnd.season.competition.name} J{rnd.number}"
            message = (
                f"Salut {player.user.username},\n\n"
                f"Tu n'as pas encore fait tes pronostics pour "
                f"{rnd.season.competition.name} Journée {rnd.number} "
                f"({_format_date(rnd.date)}).\n\n"
                f"Va sur : https://xavfabiani.pythonanywhere.com/pronos/\n\n"
                f"À très vite !"
            )
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [recipient])
            sent_count += 1

        # À H-6, envoyer un récap au GO
        if matched_hour == 6 and missing_players and settings.EMAIL_HOST_USER:
            recap_message = (
                f"Récap H-6 pour {rnd.season.competition.name} J{rnd.number} "
                f"({_format_date(rnd.date)}) :\n\n"
                f"{len(missing_players)} joueur(s) n'ont pas encore pronostiqué :\n"
            )
            for mp in missing_players:
                recap_message += f"  - {mp.user.username}\n"
            recap_message += (
                f"\nVa sur : https://xavfabiani.pythonanywhere.com/tous-les-pronos/"
            )
            send_mail(
                f"[GO] {len(missing_players)} relance(s) - {rnd.season.competition.name} J{rnd.number}",
                recap_message,
                settings.DEFAULT_FROM_EMAIL,
                [settings.EMAIL_HOST_USER],
            )

        if sent_count > 0:
            previous = list(rnd.reminder_hours_sent) if rnd.reminder_hours_sent else []
            if hour_str not in previous:
                previous.append(hour_str)
            Round.objects.filter(id=rnd.id).update(reminder_hours_sent=previous)


def notify_new_round(round_obj):
    from core.models import Player

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
    recipients = []
    players = Player.objects.filter(user__isnull=False).select_related("user")
    for p in players:
        email = (p.alert_email or p.user.email).strip()
        if email and email not in recipients:
            recipients.append(email)
    if recipients:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients)
