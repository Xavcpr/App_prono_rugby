from django.contrib import admin, messages
from .models import (
    Season, Team, Player, Competition, Round, Match, ScoringConfig,
    Prediction, DailyBonus, CompetitionBonus, DailyScore, SeasonScore, CompetitionRankingPrediction, TeamRankingPrediction
)
from core.services.scoring import calculate_points
from django.db.models import Sum
from django import forms
from datetime import datetime, time

# ---------------------
# Actions générales
# ---------------------
def recalc_scores(modeladmin, request, queryset):
    for competition in queryset:
        for round_obj in competition.round_set.all():
            for match in round_obj.match_set.all():
                for pred in match.prediction_set.all():
                    calculate_points(pred, match)

            for player_id, total in round_obj.match_set.filter(prediction__isnull=False)\
                    .values('prediction__player').annotate(points_sum=Sum('prediction__points'))\
                    .values_list('prediction__player', 'points_sum'):
                DailyScore.objects.update_or_create(
                    user_id=player_id,
                    round=round_obj,
                    defaults={'points': total}
                )

        for player_id, total in competition.round_set.filter(match__prediction__isnull=False)\
                .values('match__prediction__player').annotate(points_sum=Sum('match__prediction__points'))\
                .values_list('match__prediction__player', 'points_sum'):
            SeasonScore.objects.update_or_create(
                user_id=player_id,
                competition=competition,
                defaults={'points': total}
            )

    messages.success(request, "Recalcul des points terminé pour la compétition sélectionnée !")

recalc_scores.short_description = "Recalculer tous les points de la compétition"

# ---------------------
# Round Form
# ---------------------
class RoundForm(forms.ModelForm):
    competition = forms.ModelChoiceField(
        queryset=Competition.objects.all(),
        required=True,
        label="Compétition"
    )

    class Meta:
        model = Round
        fields = ("competition", "number", "date")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["competition"].initial = self.instance.season.competition

    def save(self, commit=True):
        round_obj = super().save(commit=False)
        competition = self.cleaned_data["competition"]
        season, _ = Season.objects.get_or_create(
            competition=competition,
            year=competition.season
        )
        round_obj.season = season
        if commit:
            round_obj.save()
        return round_obj

# ---------------------
# Round Admin
# ---------------------
@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    form = RoundForm
    list_display = ("__str__", "number", "date", "competition")
    list_filter = ("season__competition",)
    fields = ("competition", "number", "date")
    actions = ["generate_matches"]

    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None
        super().save_model(request, obj, form, change)

        if is_new:
            # Création des matchs vierges avec kickoff_at = date du round 00:00
            nb_matches = obj.competition.matches_per_round
            kickoff_datetime = datetime.combine(obj.date, time(hour=0, minute=0))
            Match.objects.bulk_create([
                Match(round=obj, kickoff_at=kickoff_datetime)
                for _ in range(nb_matches)
            ])
            self.message_user(
                request,
                f"{nb_matches} matchs vierges créés pour {obj}",
                level=messages.SUCCESS
            )

    @admin.action(description="Générer les matchs automatiquement si équipes disponibles")
    def generate_matches(self, request, queryset):
        for round_obj in queryset:
            teams = list(round_obj.season.competition.teams.all())

            if len(teams) % 2 != 0:
                self.message_user(
                    request,
                    f"Nombre d'équipes impair pour {round_obj.competition}",
                    level=messages.ERROR
                )
                continue

            if round_obj.match_set.exists():
                self.message_user(
                    request,
                    f"Les matchs existent déjà pour {round_obj}",
                    level=messages.WARNING
                )
                continue

            kickoff_datetime = datetime.combine(round_obj.date, time(hour=0, minute=0))
            for i in range(0, len(teams), 2):
                Match.objects.create(
                    round=round_obj,
                    home_team=teams[i],
                    away_team=teams[i + 1],
                    kickoff_at=kickoff_datetime
                )

            self.message_user(
                request,
                f"Matchs créés pour {round_obj}",
                level=messages.SUCCESS
            )

# ---------------------
# Admins classiques
# ---------------------
@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name",)

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name",)

@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ('name', 
                    # 'season', 
                    'bonus_defense_threshold', 'match_weight')
    actions = [recalc_scores]

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("competition", "year")
    list_filter = ("competition",)

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("round", "home_team", "away_team", "home_score", "away_score", "kickoff_at", "phase")
    list_filter = ("round__season__competition", "round", "phase")
    ordering = ("kickoff_at",)
    search_fields = ("home_team__name", "away_team__name")

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


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "match",
        "home_score_pred",
        "away_score_pred",
        "bonus_home_pred",
        "bonus_away_pred",
        "points",
    )
    list_filter = ("match", "player")

class TeamRankingPredictionInline(admin.TabularInline):
    model = TeamRankingPrediction
    extra = 0
    autocomplete_fields = ["team"]
    
@admin.register(CompetitionRankingPrediction)
class CompetitionRankingPredictionAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "competition",
        "season",
        "winner_team",
        "locked_at",
    )
    list_filter = ("competition", "season")
    search_fields = ("player__name",)
    autocomplete_fields = ("player", "winner_team")
    inlines = [TeamRankingPredictionInline]

@admin.register(TeamRankingPrediction)
class TeamRankingPredictionAdmin(admin.ModelAdmin):
    list_display = ("ranking", "team", "position", "pool")
    list_filter = ("ranking__competition", "pool")
    autocomplete_fields = ("team",)

