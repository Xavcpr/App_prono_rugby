from django.contrib import admin
from .models import (
    Team, Player, Competition, Round, Match, ScoringConfig,
    Prediction, DailyBonus, CompetitionBonus, DailyScore, SeasonScore
)
from django.contrib import messages
from core.services.scoring import calculate_points
from django.db.models import Sum

# Action pour recalculer tous les points d'une compétition
def recalc_scores(modeladmin, request, queryset):
    for competition in queryset:
        # Boucle sur toutes les journées et matchs
        for round_obj in competition.round_set.all():
            for match in round_obj.match_set.all():
                for pred in match.prediction_set.all():
                    calculate_points(pred, match)

            # Mise à jour DailyScore
            for player_id, total in round_obj.match_set.filter(prediction__isnull=False).values('prediction__player').annotate(points_sum=Sum('prediction__points')).values_list('prediction__player', 'points_sum'):
                from core.models import DailyScore
                DailyScore.objects.update_or_create(
                    user_id=player_id,
                    round=round_obj,
                    defaults={'points': total}
                )

        # Mise à jour SeasonScore
        for player_id, total in competition.round_set.filter(match__prediction__isnull=False).values('match__prediction__player').annotate(points_sum=Sum('match__prediction__points')).values_list('match__prediction__player', 'points_sum'):
            from core.models import SeasonScore
            SeasonScore.objects.update_or_create(
                user_id=player_id,
                competition=competition,
                defaults={'points': total}
            )

    messages.success(request, "Recalcul des points terminé pour la compétition sélectionnée !")

recalc_scores.short_description = "Recalculer tous les points de la compétition"

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name",)

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name",)

@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ('name', 'season', 'bonus_defense_threshold', 'match_weight')
    actions = [recalc_scores]

@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("number", "competition", "date")
    list_filter = ("competition",)

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("round", "home_team", "away_team", "home_score", "away_score", "phase")
    list_filter = ("round__competition", "phase")

@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("match", "player", "home_score_pred", "away_score_pred", "points")
    list_filter = ("match__round__competition",)

@admin.register(DailyBonus)
class DailyBonusAdmin(admin.ModelAdmin):
    list_display = ("player", "round", "points")
    list_filter = ("round",)

@admin.register(CompetitionBonus)
class CompetitionBonusAdmin(admin.ModelAdmin):
    list_display = ("player", "competition", "points")
    list_filter = ("competition",)

@admin.register(DailyScore)
class DailyScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "round", "points")
    list_filter = ("round",)
    ordering = ("-points",)

@admin.register(SeasonScore)
class SeasonScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "competition", "points")
    list_filter = ("competition",)
    ordering = ("-points",)

