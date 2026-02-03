from django.contrib import admin, messages
from .models import (
    CompetitionTeam, Season, Team, Player, Competition, Round, Match, ScoringConfig,
    Prediction, DailyBonus, CompetitionBonus, DailyScore, SeasonScore, CompetitionRankingPrediction, TeamRankingPrediction, CompetitionBonusPrediction, CompetitionTeamPrediction
)
from core.services.scoring import calculate_match_points 
from django.db.models import Sum
from django import forms
from datetime import datetime, time

# ---------------------
# Actions générales
# ---------------------
def recalc_scores(modeladmin, request, queryset):
    for competition in queryset:
        for season in competition.seasons.all():
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

    season = forms.ModelChoiceField(
        queryset=Season.objects.all(),
        required=True,
        label="Saison"
    )

    class Meta:
        model = Round
        fields = ("competition", "season", "number", "date")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields["competition"].initial = self.instance.season.competition
            self.fields["season"].initial = self.instance.season

    def save(self, commit=True):
        round_obj = super().save(commit=False)
        round_obj.season = self.cleaned_data["season"]
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
    fields = ("competition", "season", "number", "date")
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
            # teams = list(round_obj.season.competition.teams.all())
            teams = list(round_obj.season.teams.all())

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
    search_fields = ("name",)

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

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
    filter_horizontal = ("teams",)

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
    list_filter = ("match__round", "player", "match")

class TeamRankingPredictionInline(admin.TabularInline):
    model = TeamRankingPrediction
    extra = 0
    autocomplete_fields = ["team"]
    
@admin.register(CompetitionTeam)
class CompetitionTeamAdmin(admin.ModelAdmin):
    list_display = ("competition", "season", "team", "pool")
    list_filter = ("competition", "season", "pool")
    ordering = ("competition", "season", "pool")

@admin.register(CompetitionBonusPrediction)
class CompetitionBonusPredictionAdmin(admin.ModelAdmin):
    list_display = ("player", "competition", "best_try_scorer", "best_point_scorer")
    list_filter = ("competition", "player")

@admin.register(CompetitionTeamPrediction)
class CompetitionTeamPredictionAdmin(admin.ModelAdmin):
    list_display = ("player", "competition", "team", "position", "block_key")
    list_filter = ("competition", "player", "block_key")
    ordering = ("player", "competition", "position")