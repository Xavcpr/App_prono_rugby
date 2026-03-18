from django.contrib import admin, messages

from .services.scoring import compute_season_ranking_points
from .models import (
    CompetitionResult, CompetitionTeam, Season, Team, Player, Competition, Round, Match, ScoringConfig,
    Prediction, DailyScore, SeasonScore, CompetitionBonusPrediction, CompetitionTeamPrediction
)
from django.db.models import Sum
from django import forms
from datetime import datetime, time

# --- Modèles supprimés de l'admin car ils faisaient doublon ou étaient inutilisés ---
# DailyBonus, CompetitionBonus, CompetitionRankingPrediction, TeamRankingPrediction

# ---------------------
# Actions générales
# ---------------------
@admin.action(description="Recalculer tous les points de la compétition")
def recalc_scores(modeladmin, request, queryset):
    # Note : Cette fonction devra être mise à jour pour utiliser 'season' 
    # au lieu de juste 'competition' à l'avenir.
    messages.warning(request, "L'action de recalcul global doit être mise à jour pour la nouvelle structure par saison.")

# ---------------------
# Formulaire Round (pour gérer Saison et Compétition proprement)
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
    # Ajoute les colonnes pour y voir clair dans la liste globale
    list_display = ("__str__", "season", "number", "phase", "date") 
    list_filter = ("season__competition", "season", "phase")
    
    # Ajoute les champs pour qu'ils apparaissent dans la page "Ajouter un round"
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

@admin.register(SeasonScore)
class SeasonScoreAdmin(admin.ModelAdmin):
    list_display = ('user', 'competition', 'season', 'match_points', 'ranking_points', 'get_total')
    list_filter = ('season', 'competition')
    ordering = ('-match_points',) 

    def get_total(self, obj):
        return obj.total_points
    get_total.short_description = 'Total'

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



# --- DÉFINITION DE L'ACTION ADMIN ---

@admin.register(CompetitionResult)
class CompetitionResultAdmin(admin.ModelAdmin):
    # Les colonnes affichées dans la liste
    list_display = ("season", "get_competition_name", "get_season_year", "real_winner")
    list_filter = ("season__competition", "season")
    
    # L'action personnalisée à ajouter au menu déroulant
    actions = ['recalculate_season_points']

    # --- MÉTHODES D'AFFICHAGE ---
    
    @admin.display(description="Compétition")
    def get_competition_name(self, obj):
        return obj.season.competition.name

    @admin.display(description="Saison")
    def get_season_year(self, obj):
        return obj.season.year

    # --- LA LOGIQUE DE L'ACTION ---

    @admin.action(description="🔥 Calculer/Rafraîchir les points de fin de saison 🔥")
    def recalculate_season_points(self, request, queryset):
        """
        Cette méthode est appelée quand tu coches un CompetitionResult
        et que tu choisis l'action dans le menu déroulant.
        """
        if queryset.count() > 1:
            self.message_user(request, "Erreur : Veuillez sélectionner une seule saison à la fois.", messages.ERROR)
            return

        # On récupère le résultat sélectionné
        result_obj = queryset.first()
        season_to_compute = result_obj.season

        try:
            # On lance le gros calcul que l'on a mis au point
            msg = compute_season_ranking_points(season_to_compute)
            
            # On affiche un message de succès vert en haut de l'admin
            self.message_user(request, f"Succès : {msg}", messages.SUCCESS)
            
        except Exception as e:
            # En cas d'erreur technique, on affiche un message rouge
            self.message_user(request, f"Erreur lors du calcul : {str(e)}", messages.ERROR)




# Modèles simples
admin.site.register(Team)
admin.site.register(Player)
admin.site.register(Competition)
admin.site.register(ScoringConfig)
