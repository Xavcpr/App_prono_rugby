from django.utils import timezone
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User

# ----- Phases de match -----
class MatchPhase(models.TextChoices):
    POOL = "POOL", "Phase de poules"
    R16 = "R16", "Huitièmes de finale"
    QF = "QF", "Quarts de finale / Barrages"
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
    bonus_defense_threshold = models.IntegerField(default=7)
    match_weight = models.IntegerField(default=680)

    def __str__(self):
        return self.name

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
    teams = models.ManyToManyField('Team', related_name="seasons", blank=True)

    class Meta:
        unique_together = ("competition", "year")
        ordering = ["competition", "year"]

    def __str__(self):
        return f"{self.competition.name} {self.year}"

# ----- Journées / Rounds -----
class Round(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="rounds")
    number = models.PositiveIntegerField()
    date = models.DateField(
        null=True,
        blank=True,
        help_text="Date indicative de la journée"
    )

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
        # On déduit la compétition directement depuis la saison
        return self.season.competition

# ----- Matchs -----
class Match(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, null=True, related_name="matches")
    home_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="home_matches"
    )
    away_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="away_matches"
    )
    kickoff_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date et heure du match"
    )
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(default=680)
    phase = models.CharField(max_length=10, choices=MatchPhase.choices, default=MatchPhase.POOL)
    bonus_offense_home = models.BooleanField(default=False)
    bonus_offense_away = models.BooleanField(default=False)

    def total_score(self):
        if self.home_score is not None and self.away_score is not None:
            return self.home_score + self.away_score
        return 0

    def get_defense_bonus(self):
        """Retourne 'HOME', 'AWAY' ou None si un bonus défensif est mérité"""
        if self.home_score is None or self.away_score is None:
            return None
        
        diff = abs(self.home_score - self.away_score)
        # On récupère le seuil de la compétition (ex: 7 points)
        threshold = self.round.season.competition.bonus_defense_threshold
        
        if 0 < diff <= threshold:
            # L'équipe perdante prend le bonus
            return "HOME" if self.home_score < self.away_score else "AWAY"
        return None
    
    def winner(self):
        if self.home_score is None or self.away_score is None:
            return None
        if self.home_score > self.away_score:
            return self.home_team
        elif self.home_score < self.away_score:
            return self.away_team
        return None  # match nul

    def __str__(self):
        if self.home_team and self.away_team:
            return f"{self.home_team} vs {self.away_team}"
        return f"Match à définir ({self.round})"
    
    @property
    def is_locked(self):
        if self.kickoff_at:
            return timezone.now() > self.kickoff_at
        return False

# ----- Configuration de scoring -----
class ScoringConfig(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    category = models.CharField(max_length=50)
    delta = models.IntegerField(default=0)
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
    
    
# ----- Classement par compétition -----
class CompetitionRankingPrediction(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)

    winner_team = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="winner_predictions"
    )

    best_try_scorer = models.CharField(max_length=100, blank=True)
    best_kicker = models.CharField(max_length=100, blank=True)

    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("player", "season", "competition")

# ----- Classement d'équipe -----
class TeamRankingPrediction(models.Model):
    ranking = models.ForeignKey(
        CompetitionRankingPrediction,
        related_name="team_rankings",
        on_delete=models.CASCADE
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()

    pool = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Utilisé uniquement pour la Champions Cup"
    )

    class Meta:
        unique_together = ("ranking", "team")
        ordering = ["pool", "position"]

# ----- Pronostics de bonus compétition (marqueur)-----
class CompetitionBonusPrediction(models.Model):
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE
    )
    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE
    )
    best_try_scorer = models.CharField(max_length=100, blank=True, default="")
    best_point_scorer = models.CharField(max_length=100, blank=True, default="")
    winner = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="bonus_winner")

    class Meta:
        unique_together = ("player", "competition")

    def __str__(self):
        return f"{self.player} – {self.competition}"

class CompetitionTeamPrediction(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    block_key = models.CharField(max_length=50, blank=True, null=True)  # Champ ajouté

    class Meta:
        unique_together = ("player", "competition", "team")
        ordering = ["position"]
        
class CompetitionTeam(models.Model):
    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name="competition_teams"
    )
    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name="competition_teams"
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE
    )

    pool = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Poule (Champions Cup)"
    )

    class Meta:
        unique_together = ("competition", "season", "team")
        ordering = ["pool", "team__name"]

    def __str__(self):
        return f"{self.team} – {self.competition} ({self.season}) poule {self.pool}"

