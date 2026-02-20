from django import forms
from .models import Competition, Season
from django.core.exceptions import ValidationError

class TeamImportForm(forms.Form):
    competition = forms.ModelChoiceField(
        queryset=Competition.objects.all(),
        label="Compétition"
    )
    # Ajout de la saison car l'import doit maintenant savoir dans quelle saison injecter
    season = forms.ModelChoiceField(
        queryset=Season.objects.all(),
        label="Saison",
        required=False
    )
    teams = forms.CharField(
        widget=forms.Textarea,
        label="Liste des équipes",
        help_text="Une équipe par ligne"
    )

# Note : Si tu as besoin de formulaires pour CompetitionTeamPrediction 
# ou CompetitionBonusPrediction à l'avenir, on les créera ici. 
# Pour l'instant, tes vues utilisent probablement des formulaires dynamiques 
# ou des dictionnaires POST directs, donc pas besoin de surcharger ce fichier.