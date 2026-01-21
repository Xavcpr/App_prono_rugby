from django.db import models
from django.conf import settings
from math import floor
from django.contrib.auth.models import User
from django

# ----- Phases de match -----
class MatchPhase(models.TextChoices):
    POOL = "POOL", "Phase de poules"
    R16 = "R16", "Huitièmes de finale"
    QF = "QF", "Quarts de finale"
    SF = "SF", "Demi-finales"
    FINAL = "FINAL", "Finale"

# ----- Joueurs -----
class Player(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

# ----- Compétitions -----
class Competition(models.Model):
    name = models.CharField(max_length=100)
    matches_per_round = models.PositiveIntegerField(default=0)
    season = models.CharField(max_length=20)
    bonus_defense_threshold = models.IntegerField(default=7)
    match_weight = models.IntegerField(default=680)

    def __str__(self):
        return f"{self.name} {self.season}"
    
# ----- Équipes -----
class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    competitions = models.ManyToManyField(
        Competition,
        related_name="teams",
        blank=True
    )

    def __str__(self):
        return self.name

# ----- Saison ----- 
class Season(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="seasons")
    year = models.CharField(max_length=20, default="2025/2026")  # ex: "2025/2026"

    def __str__(self):
        return f"{self.competition.name} {self.year}"
# class Season(models.Model):
#     competition = models.ForeignKey(
#         Competition,
#         on_delete=models.CASCADE,
#         related_name="seasons"
#     )
#     name = models.CharField(max_length=50)  # ex: "2024-2025"
#     start_date = models.DateField()
#     end_date = models.DateField()

#     class Meta:
#         constraints = [
#             models.UniqueConstraint(
#                 fields=["competition", "name"],
#                 name="unique_season_per_competition"
#             )
#         ]

#     def __str__(self):
#         return f"{self.competition.name} {self.name}"

# ----- Journées / Rounds -----
class Round(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="rounds")
    number = models.PositiveIntegerField()
    date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["season", "number"],
                name="unique_round_per_season"
            )
        ]
        ordering = ["season", "number"]

    def __str__(self):
        return f"{self.season} – Journée {self.number}"

    @property
    def competition(self):
        return self.season.competition
   

# ----- Matchs -----
class Match(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, null=True, related_name="matches")
    home_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="home_matches")
    away_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="away_matches")    
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(default=680)
    phase = models.CharField(max_length=10, choices=MatchPhase.choices, default=MatchPhase.POOL)
    bonus_offense_home = models.BooleanField(default=False)
    bonus_offense_away = models.BooleanField(default=False)

    bonus_defense_home = models.BooleanField(default=False)
    bonus_defense_away = models.BooleanField(default=False)
    

    def total_score(self):
        if self.home_score is not None and self.away_score is not None:
            return self.home_score + self.away_score
        return 0

    def winner(self):
        if self.home_score is None or self.away_score is None:
            return None
        if self.home_score > self.away_score:
            return self.home_team
        elif self.home_score < self.away_score:
            return self.away_team
        else:
            return None  # match nul
    
    def __str__(self):
        if self.home_team and self.away_team:
            return f"{self.home_team} vs {self.away_team}"
        return f"Match à définir ({self.round})"

# ----- Configuration de scoring -----
class ScoringConfig(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    category = models.CharField(max_length=50)
    delta = models.IntegerField(default=0)  # pour différence / somme
    points = models.IntegerField(default=0)
    phase_multipliers = models.JSONField(default=dict)

# ----- Pronostics -----
class Prediction(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    match = models.ForeignKey(Match, on_delete=models.CASCADE)

    home_score_pred = models.IntegerField()
    away_score_pred = models.IntegerField()

    bonus_home_pred = models.BooleanField(default=False)
    bonus_away_pred = models.BooleanField(default=False)

    points = models.IntegerField(default=0)

# ----- Bonus journée -----
class DailyBonus(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)

# ----- Bonus compétition -----
class CompetitionBonus(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)

# ----- Scores journaliers -----
class DailyScore(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "round")
        verbose_name = "Score journée"
        verbose_name_plural = "Scores journées"

    def __str__(self):
        return f"{self.user} - {self.round} : {self.points} pts"

# ----- Scores saison -----
class SeasonScore(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "competition")
        verbose_name = "Score saison"
        verbose_name_plural = "Scores saisons"

    def __str__(self):
        return f"{self.user} - {self.competition} : {self.points} pts"


class RoundForm(forms.ModelForm):
    class Meta:
        model = Round
        fields = ("competition", "season", "number", "date")

    competition = forms.ModelChoiceField(queryset=Competition.objects.all())
    season = forms.ModelChoiceField(queryset=Season.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'competition' in self.data:
            try:
                competition_id = int(self.data.get('competition'))
                self.fields['season'].queryset = Season.objects.filter(competition_id=competition_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields['season'].queryset = Season.objects.filter(competition=self.instance.season.competition)