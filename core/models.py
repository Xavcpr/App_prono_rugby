from django.db import models
from django.conf import settings
from math import floor
from django.contrib.auth.models import User

# ----- Phases de match -----
class MatchPhase(models.TextChoices):
    POOL = "POOL", "Phase de poules"
    R16 = "R16", "Huitièmes de finale"
    QF = "QF", "Quarts de finale"
    SF = "SF", "Demi-finales"
    FINAL = "FINAL", "Finale"

# ----- Équipes -----
class Team(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

# ----- Joueurs -----
class Player(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

# ----- Compétitions -----
class Competition(models.Model):
    name = models.CharField(max_length=100)
    season = models.CharField(max_length=20)
    bonus_defense_threshold = models.IntegerField(default=7)
    match_weight = models.IntegerField(default=680)

    def __str__(self):
        return f"{self.name} {self.season}"

# ----- Journées / Rounds -----
class Round(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    number = models.IntegerField()
    date = models.DateField()

    def __str__(self):
        return f"Journée {self.number} - {self.competition.name}"

# ----- Matchs -----
class Match(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, null=True)
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_matches', null=True)
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_matches', null=True)
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(default=680)
    phase = models.CharField(max_length=10, choices=MatchPhase.choices, default=MatchPhase.POOL)

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

# ----- Configuration de scoring -----
class ScoringConfig(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    category = models.CharField(max_length=50)
    delta = models.IntegerField(default=0)  # pour différence / somme
    points = models.IntegerField(default=0)
    phase_multipliers = models.JSONField(default=dict)

# ----- Pronostics -----
class Prediction(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="predictions")
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    home_score_pred = models.IntegerField()
    away_score_pred = models.IntegerField()
    bonus_offense_pred = models.BooleanField(default=False)
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
