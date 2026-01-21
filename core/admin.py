from django.contrib import admin, messages
from .models import (
    Season, Team, Player, Competition, Round, Match, ScoringConfig,
    Prediction, DailyBonus, CompetitionBonus, DailyScore, SeasonScore, RoundForm
)
from core.services.scoring import calculate_points
from django.db.models import Sum
from .admin_views import import_teams_view
from django.contrib.admin import AdminSite
from django.shortcuts import render, redirect
from django.urls import path
from django import forms

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

@admin.action(description="Créer les matchs de la journée")
def generate_matches(modeladmin, request, queryset):
    for round in queryset:
        teams = list(round.competition.teams.all())

        # Sécurité : nombre pair d'équipes
        if len(teams) % 2 != 0:
            modeladmin.message_user(
                request,
                f"Nombre d'équipes impair pour {round.competition}",
                level="error"
            )
            continue

        # Évite de recréer des matchs
        if round.matches.exists():
            modeladmin.message_user(
                request,
                f"Les matchs existent déjà pour {round}",
                level="warning"
            )
            continue

        for i in range(0, len(teams), 2):
            Match.objects.create(
                round=round,
                home_team=teams[i],
                away_team=teams[i + 1]
            )

        modeladmin.message_user(
            request,
            f"Matchs créés pour {round}"
        )




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

# @admin.register(Round)
# class RoundAdmin(admin.ModelAdmin):
#     list_display = ("number", "competition", "date")
#     actions = [generate_matches]
#     list_filter = ("competition",)

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("round", "home_team", "away_team", "home_score", "away_score", "phase")
    list_filter = ("round__season__competition", "phase")

@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("match", "player", "home_score_pred", "away_score_pred", "points")
    list_filter = ("match__round__season__competition",)

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
    


class CustomAdminSite(admin.AdminSite):
    pass

class RugbyAdminSite(AdminSite):
    site_header = "Admin Pronostics Rugby"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "create-round/",
                self.admin_view(self.create_round_view),
                name="create-round",
            ),
        ]
        return custom_urls + urls

    def create_round_view(self, request):
        competitions = Competition.objects.all()

        if request.method == "POST":
            competition_id = request.POST["competition"]
            round_number = request.POST["round_number"]
            date = request.POST["date"]
            team_ids = request.POST.getlist("teams")

            competition = Competition.objects.get(id=competition_id)

            round_obj = Round.objects.create(
                competition=competition,
                number=round_number,
                date=date,
            )

            teams = list(Team.objects.filter(id__in=team_ids))

            if len(teams) % 2 != 0:
                messages.error(request, "Nombre d'équipes impair")
                return redirect(request.path)

            for i in range(0, len(teams), 2):
                Match.objects.create(
                    round=round_obj,
                    home_team=teams[i],
                    away_team=teams[i + 1],
                )

            messages.success(request, "Journée et matchs créés avec succès")
            return redirect("/admin/")

        return render(
            request,
            "admin/create_round.html",
            {"competitions": competitions},
        )



rugby_admin_site = RugbyAdminSite(name="rugby_admin")

rugby_admin_site.register(Competition)
rugby_admin_site.register(Team)
# rugby_admin_site.register(Round)
rugby_admin_site.register(Match)

class CreateRoundForm(forms.Form):
    competition = forms.ModelChoiceField(queryset=Competition.objects.all())
    round_number = forms.IntegerField()
    match_date = forms.DateField()
    teams = forms.ModelMultipleChoiceField(
        queryset=Team.objects.all(),
        widget=admin.widgets.FilteredSelectMultiple("Teams", is_stacked=False)
    )

class RoundForm(forms.ModelForm):
    competition = forms.ModelChoiceField(
        queryset=Competition.objects.all(),
        required=True,
        label="Compétition"
    )

    class Meta:
        model = Round
        fields = ("competition", "number", "date")  # plus de 'season'

    def save(self, commit=True):
        round_obj = super().save(commit=False)
        # On assigne automatiquement la saison depuis la compétition
        round_obj.season = round_obj.competition.season
        if commit:
            round_obj.save()
        return round_obj

    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)

    #     # Si on édite un Round existant
    #     if self.instance.pk:
    #         self.fields['competition'].initial = self.instance.season.competition
            
    #     # Si le formulaire POST contient déjà une compétition sélectionnée
    #     elif 'competition' in self.data:
    #         try:
    #             competition_id = int(self.data.get('competition'))
    #             self.fields['season'].queryset = Season.objects.filter(competition_id=competition_id)
    #         except (ValueError, TypeError):
    #             self.fields['season'].queryset = Season.objects.none()
    #     else:
    #         self.fields['season'].queryset = Season.objects.none()

# =========================
# Admin custom pour Round
# =========================
@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    form = RoundForm
    list_display = ("__str__", "number", "date", "competition")
    list_filter = ("season__competition",)  # filtrage toujours possible
    fields = ("competition", "number", "date")  # plus de 'season'
    actions = ["create_empty_matches"]

    @admin.action(description="Créer les matchs vides de la journée")
    def create_empty_matches(self, request, queryset):
        for round_obj in queryset:
            if round_obj.match_set.exists():
                self.message_user(
                    request,
                    f"{round_obj} a déjà des matchs",
                    level=messages.WARNING
                )
                continue

            nb_matches = round_obj.competition.matches_per_round

            Match.objects.bulk_create([
                Match(round=round_obj)
                for _ in range(nb_matches)
            ])

            self.message_user(
                request,
                f"{nb_matches} matchs créés pour {round_obj}",
                level=messages.SUCCESS
            )
# @admin.register(Round)
# class RoundAdmin(admin.ModelAdmin):
#     form = RoundForm
#     list_display = ("competition", "number", "date")
#     list_filter = ("season__competition", "season")
#     fields = ("season", "number", "date")
#     actions = ["generate_matches", "create_empty_matches"]

#     @admin.action(description="Créer les matchs vides de la journée")
#     def create_empty_matches(self, request, queryset):
#         for round_obj in queryset:
#             if round_obj.match_set.exists():
#                 self.message_user(
#                     request,
#                     f"{round_obj} a déjà des matchs",
#                     level=messages.WARNING
#                 )
#                 continue

#             nb_matches = round_obj.competition.matches_per_round

#             Match.objects.bulk_create([
#                 Match(round=round_obj)
#                 for _ in range(nb_matches)
#             ])

#             self.message_user(
#                 request,
#                 f"{nb_matches} matchs créés pour {round_obj}",
#                 level=messages.SUCCESS
#             )

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

            for i in range(0, len(teams), 2):
                Match.objects.create(
                    round=round_obj,
                    home_team=teams[i],
                    away_team=teams[i + 1]
                )

            self.message_user(
                request,
                f"Matchs créés pour {round_obj}",
                level=messages.SUCCESS
            )



