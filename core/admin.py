from django.contrib import admin, messages
from django.db.models import Sum, F
from django import forms
from datetime import datetime, time

from .services.scoring import compute_season_ranking_points, process_round_scores
from .models import (
    CompetitionResult, CompetitionTeam, Season, Team, Player, Competition, Round, Match, ScoringConfig,
    Prediction, DailyScore, SeasonScore, CompetitionBonusPrediction, CompetitionTeamPrediction
)
from .views import compute_statistics

# ---------------------
# Actions générales
# ---------------------
@admin.action(description="Recalculer tous les points de la compétition")
def recalc_scores(modeladmin, request, queryset):
    messages.warning(request, "L'action de recalcul global doit être mise à jour pour la nouvelle structure par saison.")

# ---------------------
# Formulaire Round
# ---------------------
class RoundForm(forms.ModelForm):
    competition = forms.ModelChoiceField(queryset=Competition.objects.all(), required=True, label="Compétition")
    season = forms.ModelChoiceField(queryset=Season.objects.all(), required=True, label="Saison")

    class Meta:
        model = Round
        fields = ("competition", "season", "number", "phase", "name_override", "date")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.season:
            self.fields["competition"].initial = self.instance.season.competition
            self.fields["season"].initial = self.instance.season

    def save(self, commit=True):
        round_obj = super().save(commit=False)
        round_obj.season = self.cleaned_data["season"]
        if commit:
            round_obj.save()
        return round_obj

# ---------------------
# Enregistrements Admin
# ---------------------

@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    form = RoundForm
    list_display = ("__str__", "season", "number", "phase", "date") 
    list_filter = ("season__competition", "season", "phase")
    fields = ("competition", "season", "number", "phase", "name_override", "date")

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("competition", "year")
    list_filter = ("competition",)
    filter_horizontal = ("teams",)

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("get_label", "round", "home_score", "away_score", "kickoff_at")
    list_filter = ("round__season__competition", "round__season", "round")
    search_fields = ("home_team__name", "away_team__name")
    
    def get_label(self, obj):
        return str(obj)
    get_label.short_description = "Match"

@admin.register(DailyScore)
class DailyScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "round", "points")
    list_filter = ("round__season", "round")
    ordering = ("-points",)

# --- CLASSE UNIQUE ET NETTOYÉE POUR SEASONSCORE ---
@admin.register(SeasonScore)
class SeasonScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'competition', 'season', 'match_points', 'ranking_points', 'last_rank', 'get_total')
    list_filter = ('season', 'competition')
    ordering = ('-match_points',) 
    actions = ['snapshot_ranking']

    def get_total(self, obj):
        return obj.total_points
    get_total.short_description = 'Total'

    @admin.action(description="Figer le classement pour l'évolution (Lundi)")
    def snapshot_ranking(self, request, queryset):
        stats = compute_statistics(competition=None, season=None)
        updated_count = 0
        for row in stats.detailed_ranking:
            # On cherche le SeasonScore correspondant au joueur
            ss = SeasonScore.objects.filter(user__username=row['username']).first()
            if ss:
                ss.last_rank = row['rank']
                ss.save()
                updated_count += 1
        self.message_user(request, f"Succès : Le rang de {updated_count} joueurs a été figé.")

@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("player", "match", "home_score_pred", "away_score_pred", "points")
    list_filter = ("match__round__season", "match__round", "player")

@admin.register(CompetitionTeam)
class CompetitionTeamAdmin(admin.ModelAdmin):
    list_display = ("competition", "season", "team", "pool")
    list_filter = ("competition", "season", "pool")

@admin.register(CompetitionBonusPrediction)
class CompetitionBonusPredictionAdmin(admin.ModelAdmin):
    list_display = ("player", "competition", "season", "winner")
    list_filter = ("season", "competition", "player")

@admin.register(CompetitionTeamPrediction)
class CompetitionTeamPredictionAdmin(admin.ModelAdmin):
    list_display = ("player", "competition", "season", "team", "position")
    list_filter = ("season", "competition", "player")
    ordering = ("player", "season", "competition", "position")

@admin.register(CompetitionResult)
class CompetitionResultAdmin(admin.ModelAdmin):
    list_display = ("season", "get_competition_name", "get_season_year", "real_winner")
    list_filter = ("season__competition", "season")
    actions = ['recalculate_season_points', 'recalculate_season_points_full']

    @admin.display(description="Compétition")
    def get_competition_name(self, obj):
        return obj.season.competition.name

    @admin.display(description="Saison")
    def get_season_year(self, obj):
        return obj.season.year

    @admin.action(description="🔥 Recalculer TOUT (journées + points classement) 🔥")
    def recalculate_season_points(self, request, queryset):
        if queryset.count() > 1:
            self.message_user(request, "Erreur : Sélectionnez une seule saison.", messages.ERROR)
            return
        result_obj = queryset.first()
        season = result_obj.season
        try:
            # 1. Recalculer toutes les journées de la saison
            rounds = season.rounds.all().order_by('number')
            recalc_count = 0
            for r in rounds:
                process_round_scores(r)
                recalc_count += 1
            # 2. Calculer les points de classement
            msg = compute_season_ranking_points(season, compute_podium=False)
            self.message_user(request, f"Succès : {recalc_count} journées recalculées. {msg}", messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f"Erreur : {str(e)}", messages.ERROR)

    @admin.action(description="🏆 Recalculer TOUT (journées + classement + PODIUM + vainqueur) 🏆")
    def recalculate_season_points_full(self, request, queryset):
        if queryset.count() > 1:
            self.message_user(request, "Erreur : Sélectionnez une seule saison.", messages.ERROR)
            return
        result_obj = queryset.first()
        season = result_obj.season
        try:
            rounds = season.rounds.all().order_by('number')
            recalc_count = 0
            for r in rounds:
                process_round_scores(r)
                recalc_count += 1
            msg = compute_season_ranking_points(season, compute_podium=True)
            self.message_user(request, f"Succès : {recalc_count} journées recalculées. {msg}", messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f"Erreur : {str(e)}", messages.ERROR)

# Modèles simples
admin.site.register(Team)
admin.site.register(Player)
admin.site.register(Competition)
admin.site.register(ScoringConfig)