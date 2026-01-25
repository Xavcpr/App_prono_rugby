from django import forms
from .models import Competition, CompetitionRankingPrediction, TeamRankingPrediction, Team
from django.forms import modelformset_factory, BaseModelFormSet
from django.core.exceptions import ValidationError

class TeamImportForm(forms.Form):
    competition = forms.ModelChoiceField(
        queryset=Competition.objects.all(),
        label="Compétition"
    )
    teams = forms.CharField(
        widget=forms.Textarea,
        label="Liste des équipes",
        help_text="Une équipe par ligne"
    )

class CompetitionRankingPredictionForm(forms.ModelForm):
    class Meta:
        model = CompetitionRankingPrediction
        fields = ['winner_team', 'best_try_scorer', 'best_kicker']
    
    def __init__(self, *args, **kwargs):
        competition = kwargs.pop("competition", None)
        super().__init__(*args, **kwargs)
        if competition:
            self.fields["winner_team"].queryset = competition.teams.all()
        # Désactiver si verrouillé
        if self.instance and self.instance.locked_at:
            for f in self.fields.values():
                f.disabled = True

class TeamRankingPredictionForm(forms.ModelForm):
    class Meta:
        model = TeamRankingPrediction
        fields = ['team', 'position', 'pool']
    
    def __init__(self, *args, **kwargs):
        competition = kwargs.pop("competition", None)
        super().__init__(*args, **kwargs)
        if competition:
            self.fields['team'].queryset = competition.teams.all()
        if self.instance and self.instance.ranking.locked_at:
            for f in self.fields.values():
                f.disabled = True

# # Formset pour les équipes
# TeamRankingPredictionFormSet = modelformset_factory(
#     TeamRankingPrediction,
#     form=TeamRankingPredictionForm,
#     extra=0,
#     can_delete=False
# )

class BaseTeamRankingPredictionFormSet(BaseModelFormSet):
    def clean(self):
        super().clean()
        seen_teams = set()
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                team = form.cleaned_data['team']
                if team in seen_teams:
                    raise ValidationError(f"L'équipe {team} est déjà classée !")
                seen_teams.add(team)

# Formset modifié
TeamRankingPredictionFormSet = modelformset_factory(
    TeamRankingPrediction,
    form=TeamRankingPredictionForm,
    formset=BaseTeamRankingPredictionFormSet,
    extra=0,
    can_delete=False
)