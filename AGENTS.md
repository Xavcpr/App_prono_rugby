# Rugby Pronostics App — AGENTS.md

## Goal
Application de pronostics rugby hébergée sur PythonAnywhere.

## Constraints
- PythonAnywhere gratuit : quota disque limité, pas de scheduled tasks.
- Venv dans `~/.venvs/rugby_app` (hors projet).
- `DEBUG=False` par défaut, réglable via `DJANGO_DEBUG`.
- `.env` chargé via python-dotenv (import optionnel si non installé).
- Mails via Gmail + mot de passe d'application, cron externe via cron-job.org.

## Progress

### Done
- **Phase 1 — Bugs actifs (6/6)** : `real_best_best_try_scorer` → `real_best_try_scorer` ; `Team.get_or_create` M2M ; `@staff_member_required` sur `compute_round_view` ; `season=season` dans `CompetitionBonusPrediction.get_or_create` ; `matches.filter(phase='POOL').update(...)` ; `%H:%M` au lieu de `%H:%i`.
- **Phase 2 — Sécurité (4/5)** : fallback secret key → `get_random_secret_key()` ; `@login_required` sur 3 vues ; `SECURE_SSL_REDIRECT` + cookies sécurisés conditionnels ; `LANGUAGE_CODE = 'fr-fr'`.
- **Phase 3 — Ménage (5/5)** : suppression `prediction_service.py`, `ranking_service.py`, `standings.py` ; 3 templatetags fusionnés en 1 ; suppression `ScoringConfig` + migration 0013 ; retrait `rest_framework` ; `round_board.html` à jour.
- **Phase 4 — Performance (2/2)** : `db_index` sur `Match.kickoff_at` ; index composite `(match, player)` sur `Prediction`.
- **Phase 5 — Bonnes pratiques (3/4)** : suppression `print()` dans `Season.has_started` ; templates 404/500 statiques ; `reminder_hours_sent` CharField → JSONField + migration 0014 ; `email_service.py` adapté.
- **Phase 6 — Refacto scoring + tests (3/3)** : déplacement `compute_competition_points` de `views.py` → `services/scoring.py` ; ajout `@transaction.atomic` sur `compute_season_ranking_points` ; 8 nouveaux tests (T1-T8) → 17/17 OK.
- **Phase 7 — CI, health, env (3/3)** : GitHub Actions (`tests.yml`) ; endpoint `/health/` ; `.env.example` complété avec `CRON_TOKEN`.
- **Phase 8 — Import auto des scores (3 competences)** : service `scores_importer.py` avec support Top 14, Champions Cup et 6 Nations ; `team_mapping.json` mis a jour (20 equipes) ; management command `import_scores` avec `--competition` ; vue `/cron/import-scores/<token>/` ; `SPORTSDB_API_KEY` ; accent-insensitive matching.

### Done
- **Phase 9 — Points F/P dans les graphiques** : ajout `flair_series` et `podium_series` dans `StatsResult` ; injection des valeurs SeasonScore dans les séries ; graphique Évolution des scores affiche désormais M+F+P (trait plein) + M seul (tirets).
- **Phase 10 — Création 6 Nations 2027** : commande `create_6nations_2027` ; création saison 2027, liaison des 6 équipes, 5 rounds, 15 matchs avec dates/heures TZ-aware depuis TheSportsDB.
- **Phase 11 — Joueurs par saison** : ajout M2M `Player.seasons` (migration 0015) ; filtre des vues (`home_view`, `pronos_view`, `debug_scores`, `recap_pronos`, `compute_competition_points`) ; admin avec `filter_horizontal` ; commandes `backfill_player_seasons` (backfill) et `create_6nations_2027` (attribution auto).
- **Phase 12 — Versionnage + graphiques + import** : `core/version.py` (PEP 440, v1.1.1), endpoint `/version/`, footer ; stats limitées aux journées passées + fenêtre par défaut « 5 dernières » ; `/stats-scores/` en barres sur scores observés ; cron import → auto-recalcul des journées jouées (`recompute_played_rounds`) ; saisie des scores sur la page Bonus.
- **Phase 13 — Ménage audit** : `db_backup.sqlite3` + artefacts dev untrackés (json/csv/xlsx/notebooks/htm/`views_svg`) ; doublon `compute_competition_points` supprimé (une seule version, filtrée par saison, dans `views.py`) ; `djangorestframework` retiré de requirements ; `print()` → `logger` dans scoring.py.
- **Phase 14 — Règle tout-pile** : un tout-pile n'ajoute plus les demi-tout-pile (800 pts au lieu de 800+2×40) ; aligné entre `calculate_match_points` (services/scoring.py), le round board (views.py) et les stats (statistics.py déjà en `elif`) ; mermaid de `bareme.html` mis à jour ; 2 tests dédiés (101 au total).
- **Phase 15 — UX bonus + rappels** : bouton « Voir les scores & pronos de cette journée » sur la page Bonus ; rappels H-24/H-6 ancrés sur le premier kickoff du round (le H-6 ne se déclenchait jamais avec l'ancrage jour) — repli jour pour les rounds sans match ; test du récap H-6 (102 au total).
- **Phase 16 — Import manuel admin** : action admin « ⟳ Importer les scores depuis TheSportsDB (maintenant) » sur `SeasonAdmin` (même mode que le cron : `quick=True`, dernière journée), avec auto-recalcul des journées jouées si changement ; 2 tests dédiés (104 au total).
- **Phase 17 — Bouton import sur la page Bonus** : bouton staff « ⟳ Importer les scores depuis TheSportsDB » directement sur `/resultats/<round>/bonus/` (réservé `is_staff`, formulaire dédié) ; déclenche l'import de la saison du round + recalcul si changement ; 2 tests (106 au total).
- **Phase 18 — Commande show_match_prono** : `manage.py show_match_prono <id|texte>` affiche tous les pronos (joueur + score prédit + BO/BD + points) d'un match ; `--list` liste les matches avec leurs IDs (filtres `--competition`, `--season`, `--round`) ; recherche par nom d'équipe ; gère les matchs historiques sans équipes (`?`) ; 3 tests (109 au total).
- **Phase 18b — Tri par écart** : `show_match_prono --sort diff` trie les pronos par écart Domicile-Extérieur décroissant (du plus optimiste pour l'équipe à domicile au plus pessimiste) et affiche l'écart `[+N]`/`[-N]` ; option `--sort`, signe ASCII (console Windows) ; égalité d'écart → départage par points marqués à domicile (le plus grand d'abord) ; 2 tests (111 au total).
- **Phase 19 — Sync SeasonScore.match_points** : bug « classement global non incrémenté » (les journées étaient calculées via DailyScore mais la somme saison `SeasonScore.match_points` jamais resynchronisée → classement/stats/HOF à 0). Ajout de `sync_season_match_points()` dans `scoring.py`, appelée après `process_round_scores` sur la page Bonus, le bouton « Recalculer » et via `recompute_played_rounds` ; commande `manage.py sync_match_points` pour réparer les saisons 2025+ existantes ; 2 tests (113 au total).
- **Phase 20 — HOF archivage + saison en cours** : corrigé après retour utilisateur. Convention `SeasonHistory.season_year` = **année de FIN** de saison (2024-2025 stocké 2025). Le HOF affiche désormais : (1) les saisons archivées labellisées `2024-2025`, `2018-2019`, etc. (plus de décalage d'un an), et (2) la saison en cours `2026-2027` re-calculée en direct depuis `SeasonScore` (M+F+P des compétitions `2026`/`2026/2027`), labellisée `2026-2027` (jamais `2026`). `_season_label()` et `_compute_hof_entry(display_year=...)`. 2 tests HOF (114 au total).
- **Phase 21 — README** : création `backend/README.md` (installation, toutes les commandes management dont `show_match_prono` — lire les pronos d'un match, retrouver l'ID, `--list`, filtres, `--sort diff` —, `import_scores`, `sync_match_points`, `send_reminders`, exports Excel) + règle HOF d'archivage.
- **Phase 22 — Commande archive_season** : `manage.py archive_season <annee_fin>` archive le classement final d'une saison terminée dans `SeasonHistory` depuis les `SeasonScore` (M+F+P, regroupement `year__startswith=<annee_fin-1>` ; ex. `archive_season 2026` → saisons « 2025 » et « 2025/2026 » = 6N 2025 + Top14/CC 2025-2026), avec `--dry-run` ; idempotent (écrase les lignes existantes de la même `season_year`) ; 4 tests (118 au total). Réponse à l'utilisateur : `sync_match_points` déjà exécuté = pas besoin de le relancer ; archiver la 2025-2026 via `archive_season 2026` sur PA.
- **Phase 23 — Anti-entrées fantômes** : le HOF calculait avec des joueurs à 0 pt qui n'avaient jamais joué la saison (créés par `sync_season_match_points` pour tous les comptes). Désormais la participation = **au moins un pronostic** (`Prediction`) dans la saison. `sync_season_match_points` supprime les lignes fantômes des non-participants ; `archive_season` n'inclut que les participants (les comptes ayant rejoint le concours les années suivantes sont exclus). 3 tests sync + 1 test archive « excludes non-participants » + fixture `_participate` prédictive (122 au total).
- **Phase 24 — Regroupement des saisons corrigé (HOF + archive)** : après retour utilisateur (« bons noms mais pas les bons scores », Augustin 19740 / Xav 16793, Luc 1er et non 3e). Le bug : `archive_season` et le bloc HOF « saison en cours » groupaient avec `year__startswith(...)`, ce qui **déplaçait le 6N 2026** (année `"2026"` → appartient à la 2025-2026) et **écartait le 6N 2027**. Ajout de `Season.group_key()` / `Season.by_season_year()` (même logique que le sélecteur de la page d'accueil) ; `archive_season` l'utilise (+ repli `DailyScore` comme `home_view`, M+F+P) ; le bloc HOF live aussi ; tri des saisons du modal par libellé décroissant (le tri par `year` mettait 2026-2027 après 2025-2026 à année égale). `home_view` réutilise `Season.group_key`. 4 nouveaux tests (126 au total), version **1.4.4**.

### In Progress
- *(none)*

## Key Decisions
- `load_dotenv()` optionnelle.
- Token uniquement pour le cron endpoint.
- Heures de rappel : `REMINDER_HOURS=24,6`.
- Per-season `scoring_config` JSONField.
- Flèche évolution basée sur `rank_series` enrichi à J-7.
- Cron externe : cron-job.org.
- Secret key : fallback via `get_random_secret_key()`.
- `reminder_hours_sent` : JSONField avec data migration.
- **Versionnage : chaque modification déployée doit incrémenter `__version__` dans `core/version.py`** (PEP 440, MAJEUR.MINEUR.PATCH, ex. 1.0.0 → 1.0.1 → 1.1.0 → 2.0.0). Vérifiable via le footer (toutes pages) et `/version/`.

## Next Steps
1. ~~Configurer cron-job.org pour appeler `/health/`~~ ✅
2. ~~Récupération auto des scores~~ ✅
3. ~~Obtenir une clé API TheSportsDB gratuite~~ (la clé `3` suffit pour commencer).
4. ~~Ajouter `SPORTSDB_API_KEY` dans le `.env` sur PythonAnywhere~~ (valeur par défaut `3`).
5. ~~Créer le cron-job.org pour l'import auto~~ ✅ (URL `/cron/import-scores/CRON_TOKEN/`, toutes les 60 min, fonctionne — scores MAJ de nuit. Depuis la v1.1.1, le cron recalcule aussi les journées jouées.)
6. Tester les mails H-24/H-6 en semaine réelle.
7. Inscriptions.

## Critical Context
- Projet : `App_prono_rugby` sur PA, dépôt git dans `backend/`.
- Site : `xavfabiani.pythonanywhere.com` — `main` (commit `d2baafc`).
- Version courante : `1.4.3` (`core/version.py`).
- `.env` sur PA : `CRON_TOKEN=xx`, `EMAIL_HOST_USER=pronorugby83@gmail.com`, `REMINDER_HOURS=24,6`.
- Tests : `python -m pytest tests/ -q` → 122 OK.
- CI : GitHub Actions (`.github/workflows/tests.yml`) — pytest sur push/PR branch `main`.
- Migrations 0013, 0014 appliquées.

## Relevant Files
- `core/views.py`
- `core/models.py` : `Match.kickoff_at` (db_index), `Prediction` (index composite), `Round.reminder_hours_sent` (JSONField).
- `core/services/scoring.py` : `@transaction.atomic`, `compute_competition_points`.
- `core/services/email_service.py` : parsing JSON `reminder_hours_sent`.
- `core/templates/404.html`, `500.html` : statiques.
- `core/templatetags/custom_filters.py` : fichier unique.
- `tests/conftest.py` : fixtures.
- `.env.example`
- `.github/workflows/tests.yml`
- `core/services/scores_importer.py`
- `core/services/team_mapping.json`
- `core/services/statistics.py` : `StatsResult` avec `flair_series`, `podium_series`
- `core/management/commands/import_scores.py`
- `core/management/commands/create_6nations_2027.py` : création 6 Nations 2027 depuis TheSportsDB
- `core/management/commands/show_match_prono.py` : affiche les pronos d'un match, liste les matches avec IDs, recherche par équipe
- `core/templates/statistiques.html` : graphique avec M+F+P + M (tirets)
- `core/admin.py` : `PlayerAdmin` avec `filter_horizontal` sur `seasons`
- `core/version.py` : `__version__` (PEP 440) — à incrémenter à chaque modif déployée
- `core/context_processors.py` : `APP_VERSION` injecté dans toutes les templates
- `README.md` : commandes management (show_match_prono, import_scores, sync_match_points, send_reminders, exports) + règle d'archivage HOF
