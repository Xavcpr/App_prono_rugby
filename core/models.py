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
    
    @property
    def has_started(self):
        first_match = Match.objects.filter(round__season=self).exclude(kickoff_at__isnull=True).order_by('kickoff_at').first()
        if first_match and first_match.kickoff_at:
            now = timezone.now()
            started = now > first_match.kickoff_at
            print(f"DEBUG: Now={now} | Kickoff={first_match.kickoff_at} | Started={started}")
            return started
        return False

# ----- Journées / Rounds -----
class Round(models.Model):
    # On définit les choix ici ou on importe ceux que tu avais
    class MatchPhase(models.TextChoices):
        POOL = "POOL", "Phase de poules"
        R16 = "R16", "Huitièmes de finale"
        QF = "QF", "Quarts de finale / Barrages"
        SF = "SF", "Demi-finales"
        FINAL = "FINAL", "Finale"

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="rounds")
    number = models.PositiveIntegerField(help_text="Ordre chronologique (1, 2, 3...)")
    
    # Nouveau champ pour le type de phase
    phase = models.CharField(
        max_length=10, 
        choices=MatchPhase.choices, 
        default=MatchPhase.POOL
    )
    
    # Nouveau champ optionnel pour un nom personnalisé (ex: "Barrages")
    name_override = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text="Nom personnalisé (ex: 'Match de barrage'). Laisse vide pour 'Journée X'"
    )
    
    date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["season", "number"], name="unique_round_per_season")
        ]
        ordering = ["season", "number"]

    def __str__(self):
        # Logique d'affichage intelligente
        if self.name_override:
            return f"{self.season} – {self.name_override}"
        if self.phase != self.MatchPhase.POOL:
            return f"{self.season} – {self.get_phase_display()}"
        return f"{self.season} – Journée {self.number}"
    
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
            s = self.round.season if self.round and self.round.season_id else None
            ctx = f" [{s.competition.name} J{self.round.number}]" if s else ""
            return f"{self.home_team} vs {self.away_team}{ctx}"
        return f"Match à définir ({self.round})"
    
    @property
    def is_locked(self):
        if self.kickoff_at:
            return timezone.now() > self.kickoff_at
        return False
    
    @property
    def display_kickoff(self):
        """Retourne l'heure du match ou, à défaut, la date de la journée"""
        if self.kickoff_at:
            return self.kickoff_at
        if self.round and self.round.date:
            return self.round.date
        return None
    
    
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
    # Ajout de la saison en null=True pour la migration
    season = models.ForeignKey(
        Season, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    
    match_points = models.IntegerField(default=0, verbose_name="Points Matchs")
    ranking_points = models.IntegerField(default=0, verbose_name="Points Classement")
    podium_points = models.IntegerField(default=0, verbose_name="Points Podium") # Nouveau champ !
    last_rank = models.IntegerField(null=True, blank=True)

    class Meta:
        # On met à jour l'unicité : un score par utilisateur par saison par compétition
        unique_together = ("user", "season", "competition")
        verbose_name = "Score saison"
        verbose_name_plural = "Scores saisons"

    def __str__(self):
        s_year = self.season.year if self.season else "???"
        return f"{self.user} - {self.competition} {s_year} : {self.total_points} pts"

    @property
    def total_points(self):
        return self.match_points + self.ranking_points + self.podium_points
    

# ----- Pronostics de bonus compétition (marqueur)-----
class CompetitionBonusPrediction(models.Model):
    player = models.ForeignKey(
        Player, 
        on_delete=models.CASCADE
    )
    # Ajout de la saison en null=True
    season = models.ForeignKey(
        Season, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    competition = models.ForeignKey(
        Competition, 
        on_delete=models.CASCADE
    )
    best_try_scorer = models.CharField(max_length=100, blank=True, default="")
    best_point_scorer = models.CharField(max_length=100, blank=True, default="")
    winner = models.ForeignKey(
        Team, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL, 
        related_name="bonus_winner"
    )

    class Meta:
        # On met à jour l'unicité pour inclure la saison
        unique_together = ("player", "season", "competition")

    def __str__(self):
        s_name = self.season.year if self.season else "Inconnue"
        return f"{self.player} – {self.competition} ({s_name})"

class CompetitionTeamPrediction(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    # On autorise null=True temporairement pour la migration
    season = models.ForeignKey(
        Season, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    block_key = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        # On garde l'unicité sur (joueur, saison, équipe)
        # Attention : si tu as déjà des données, l'unique_together 
        # peut échouer si plusieurs lignes ont season=None.
        unique_together = ("player", "season", "team")
        ordering = ["position"]

    def __str__(self):
        return f"{self.player} - {self.team} ({self.season})"
        
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


class CompetitionResult(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    # Résultats Bonus
    real_winner = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, related_name="real_winner")
    real_best_try_scorer = models.CharField(max_length=100, blank=True)
    real_best_point_scorer = models.CharField(max_length=100, blank=True)
    
    # Résultats Classement (JSON pour aller vite : { "pool1": {team_id: position}, "all": {team_id: position} })
    rankings_json = models.JSONField(default=dict) 

    def __str__(self):
        return f"Résultats réels {self.season}"
    
# Classement all-time des saisons jouées (pour affichage historique)
class SeasonHistory(models.Model):
    season_year = models.IntegerField()
    # On rend l'utilisateur optionnel (null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    # On ajoute un champ texte pour le nom "historique"
    player_name_legacy = models.CharField(max_length=100, null=True, blank=True)
    
    rank = models.IntegerField()
    total_players = models.IntegerField()

    @property
    def display_name(self):
        # Priorité au compte utilisateur s'il existe, sinon le nom texte
        if self.user:
            return self.user.username
        return self.player_name_legacy