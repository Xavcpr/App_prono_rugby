# App Prono Rugby

Application Django de pronostics rugby (Top 14, Champions Cup, 6 Nations) hébergée sur
PythonAnywhere : **`xavfabiani.pythonanywhere.com`**.

- **Version** : `core/version.py` (`1.4.1`) — visible sur toutes les pages (footer) et via `/version/`.
- **Tests** : `python -m pytest tests/ -q` → 114 OK.
- **CI** : GitHub Actions (`.github/workflows/tests.yml`).

## Installer / lancer en local

```bash
python -m venv ~/.venvs/rugby_app
# Windows (PowerShell) :
venv\Scripts\activate
# Linux / macOS :
source ~/.venvs/rugby_app/bin/activate

pip install -r requirements.txt
cp .env.example .env        # compléter les clés si besoin
python manage.py migrate
python manage.py runserver
```

## Commandes utiles (management commands)

Toutes les commandes se lancent depuis le dossier `backend/` avec le venv activé.
Exemple : `python manage.py show_match_prono 123`.

### Pronostics d'un match (créée récemment)

`show_match_prono` permet d'afficher **tous les pronos d'un match** (joueur, score
prédit, bonus BO/BD cochés, points obtenus) ainsi que de **retrouver l'ID d'un
match**.

| Commande | Description |
|---|---|
| `python manage.py show_match_prono <id>` | Pronos du match dont l'ID est `<id>`. |
| `python manage.py show_match_prono "Toulouse"` | Recherche par texte (nom d'équipe) puis affiche les pronos du match trouvé. |
| `python manage.py show_match_prono --list` | Liste tous les matchs avec leur ID. |
| `python manage.py show_match_prono --list --competition "Top 14"` | Filtre la liste par compétition. |
| `python manage.py show_match_prono --list --season 2026/2027` | Filtre la liste par année de saison. |
| `python manage.py show_match_prono --list --round 5` | Filtre la liste par numéro de journée. |
| `python manage.py show_match_prono 123 --sort diff` | Trie les pronos par écart Domicile-Extérieur décroissant (le plus optimiste pour l'équipe à domicile d'abord) et affiche l'écart `[+N]` / `[-N]`. |
| `python manage.py show_match_prono 123 --sort name` | Trie les pronos par nom de joueur (défaut). |

**Comment connaître l'ID d'un match ?**
1. `python manage.py show_match_prono --list` (et filtrer avec `--competition`,
   `--season`, `--round` pour réduire la liste),
2. relever le numéro en première colonne,
3. `python manage.py show_match_prono <ce_numero>`.

### Import des scores depuis TheSportsDB

```bash
# Import de la dernière journée de la saison la plus récente (mode cron, rapide) :
python manage.py import_scores --quick

# Import complet d'une compétition / saison précise :
python manage.py import_scores --competition "Top 14" --season 2026/2027

# Options utiles :
#   --dry-run            affiche ce qui serait modifié sans écrire en base
#   --no-create          ne crée pas les matchs manquants (met à jour les scores)
#   --auto-create-teams  crée automatiquement les équipes inconnues
#   --all-seasons        traite aussi les saisons archivées
```

Depuis la v1.1.1, successivement à l'import, les journées jouées sont recalculées
(`recompute_played_rounds`).

### Réparer le classement global (suit les saisies de scores)

Les saisies de scores (page Bonus, bouton « Recalculer », import TheSportsDB)
mettent à jour les `DailyScore` **et** la somme de saison `SeasonScore.match_points`
qui alimente le classement global / les statistiques / le Hall of Fame.

Si un décalage s'est produit (anciennes journées saisies avant la v1.4.0), lancer :

```bash
python manage.py sync_match_points          # toutes les saisons 2025+
python manage.py sync_match_points --season 2026/2027   # une seule saison
```

### Rappels de pronos par email

```bash
python manage.py send_reminders
```

Envoie les emails H-24 / H-6 avant le premier kickoff de chaque journée (`REMINDER_HOURS=24,6` dans le `.env`).

### Autres commandes

| Commande | Rôle |
|---|---|
| `python manage.py generer_matchs "2026/2027"` | Génère les matchs d'une saison (dates/heures). |
| `python manage.py export_classement -c <id_comp> -s <id_saison> -o classement.xlsx` | Export Excel du classement d'une saison. |
| `python manage.py export_pronos_excel -s 2026/2027 -c "Top 14" -o pronos.xlsx` | Export Excel des pronos. |
| `python manage.py backfill_player_seasons` | Lie chaque joueur à ses saisons passées (M2M `Player.seasons`). |
| `python manage.py create_6nations_2027` | Crée la saison 6 Nations 2027 (matchs depuis TheSportsDB). |
| `python manage.py send_reminders` | Rappels email H-24/H-6. |

Commandes de maintenance / scraping (usage ponctuel) : `scrape_top14_lnr`,
`scrape_cc_epcr`, `import_matches`, `add_cc_teams`, `init_champions_cup_scoring`,
`setup_cc_pools`, `create_top14_2627`, `create_cc_2627`, `update_bareme_2027`.

## Vues et fonctionnalités principales

- `/` — classement général (scores Domicile/Extérieur, bonus Flair + Podium).
- `/pronos/` — saisie des pronos de la journée.
- `/resultats/<round>/` — board de la journée + saisie des scores (staff).
- `/resultats/<round>/bonus/` — saisie des bonus + bouton staff d'import TheSportsDB.
- `/statistiques/` — stats et graphiques (M+F+P).
- `/hall-of-fame/` — panthéon : saisons archivées **+ saison en cours** (libellée
  `2026-2027`), pondération 0.9^n (n = âge de la saison en années).
- `/health/`, `/version/`, `/cron/import-scores/<token>/` — ops.

## Hall of Fame — règle d'archivage

- `SeasonHistory.season_year` stocke **l'année de fin** de saison : la saison
  `2024-2025` est archivée avec `season_year = 2025` (affichée « 2024-2025 »).
- Pour archiver la saison `2025-2026` (rang de chaque joueur), créer les lignes
  `SeasonHistory` avec `season_year = 2026` via `/admin` (champ `season_year`).
- La saison en cours (`2026-2027`) est ajoutée automatiquement depuis
  `SeasonScore` (totaux matchs + flair + podium).