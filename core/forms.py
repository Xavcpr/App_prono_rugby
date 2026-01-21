from django import forms
from .models import Competition

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
