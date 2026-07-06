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

## Next Steps
1. Configurer cron-job.org pour appeler `https://xavfabiani.pythonanywhere.com/health/` (vérification uptime).
2. Tester les mails H-24/H-6 en semaine réelle.
3. Vérifier que la CI passe sur GitHub (premier push déclenche le workflow).
4. Récupération auto des scores (API).
5. Points F/P dans graphiques.
6. Inscriptions.

## Critical Context
- Projet : `App_prono_rugby` sur PA, dépôt git dans `backend/`.
- Site : `xavfabiani.pythonanywhere.com` — `main` (commit `e4cf87f`).
- `.env` sur PA : `CRON_TOKEN=xx`, `EMAIL_HOST_USER=pronorugby83@gmail.com`, `REMINDER_HOURS=24,6`.
- Tests : `python -m pytest tests/ -v` → 17/17 OK.
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
