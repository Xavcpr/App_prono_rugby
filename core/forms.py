from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from .models import Competition, Season
from django.core.exceptions import ValidationError


class SettingsForm(PasswordChangeForm):
    email = forms.EmailField(required=False, label="Adresse email (pour les rappels)")

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields['email'].initial = user.email
        self.fields['old_password'].required = False
        self.fields['new_password1'].required = False
        self.fields['new_password2'].required = False

    def clean(self):
        cleaned = super().clean()
        # Si aucun mot de passe fourni, on ne valide pas l'ancien mot de passe
        if not cleaned.get('new_password1'):
            self._errors.pop('old_password', None)
            self._errors.pop('new_password1', None)
            self._errors.pop('new_password2', None)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user

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