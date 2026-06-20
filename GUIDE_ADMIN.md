# Guide Administrateur — Pronos Rugby

## Connexion

Se connecter sur `/admin/` avec un compte **staff**.

---

## 1. Créer une nouvelle saison

1. Aller dans **Admin > Competitions** → vérifier que la compétition existe (Top 14, Champions Cup, 6 Nations)
2. Aller dans **Admin > Seasons** → cliquer "Ajouter une saison"
   - `Competition` : choisir la compétition
   - `Year` : ex. `"2026/2027"` pour Top 14, `"2027"` pour 6 Nations
   - `Teams` : sélectionner les équipes participantes
3. Aller dans **Admin > Competition teams** → ajouter les équipes avec leur numéro de poule (Champions Cup) ou sans (Top 14 / 6 Nations)

---

## 2. Créer une journée (round) et ses matchs

**Méthode A — Via l'admin Django :**

1. **Admin > Rounds** → Ajouter un round
   - `Competition` / `Saison` / `Numéro` / `Phase` (POOL par défaut)
   - `Date` : date de la journée
2. **Admin > Matchs** → Ajouter chaque match
   - Sélectionner le round, les équipes, le `kickoff_at`
   - Laisser les scores à vide

**Méthode B — Via la commande (recommandé pour les séries de matchs) :**

```bash
python manage.py generer_matchs "Top 14" "2025/2026" 14 "2026-01-15" \
    StadeToulousain Racing92 LaRochelle Bordeaux UBB Toulon Clermont \
    Castres Pau SectionPaloise Lyon Perpignan Montpellier Vannes
```

Les 7 premières équipes = domicile, les 7 suivantes = extérieur.

---

## 3. Saisir les résultats des matchs (chaque semaine)

1. **Admin > Matchs** → filtrer par round
2. Pour chaque match de la journée :
   - Remplir `home_score` et `away_score`
   - Cocher `bonus_offense_home` / `bonus_offense_away` si une équipe a marqué 3 essais de plus que l'adversaire
   - Le bonus défensif est automatique (calculé via `get_defense_bonus`)
3. Les points de la journée sont automatiquement calculés **la première fois que quelqu'un visite la page des résultats** (`/resultats/<round_id>/`).
   - Tu peux aussi tout recalculer en une fois via l'action admin (voir section 4).

---

## 4. Fin de phase régulière — Points de classement (Flair)

Après la dernière journée de la saison régulière (avant les phases finales) :

### Étape 1 : Saisir le classement réel

Aller sur `/admin/saisie-resultats/` (ou Admin > `admin_saisie_resultats`) :

1. Sélectionner la compétition
2. Pour chaque position (1 à 14 pour Top 14, 1 à 6 par poule pour Champions Cup) : sélectionner l'équipe réelle
3. **Ne pas remplir** le vainqueur, meilleur marqueur, meilleur scoreur (c'est pour la phase finale)
4. Cliquer "Enregistrer les résultats officiels"

### Étape 2 : Lancer le calcul automatique

Aller sur **Admin > Competition results** :
1. Sélectionner la ligne de la saison concernée
2. Dans le menu déroulant "Actions", choisir **"🔥 Recalculer TOUT (journées + points classement) 🔥"**
3. Cliquer "Go"

Cette action va **automatiquement** :
- ✅ Recalculer les points de **toutes les journées** de la saison
- ✅ Synchroniser les points dans `SeasonScore.match_points`
- ✅ Calculer les **points de Flair** (prédictions de classement : exact rank, gap-1, gap-2)
- ❌ **Ne pas** calculer le podium (réservé à la phase finale)

### Étape 3 : Vérifier

- Aller sur `/statistiques/` → sélectionner **Top 14** + **2025-2026**
- Vérifier que la colonne **F** (Flair / points de classement) affiche des points pour chaque joueur
- Si les points F sont à 0, c'est que les joueurs n'ont pas soumis leurs prédictions de classement (`CompetitionTeamPrediction`)

---

## 5. Fin de phase finale — Podium, vainqueur, bonus

Après la finale de la compétition :

### Étape 1 : Saisir les résultats réels

Aller sur `/admin/saisie-resultats/` (ou Admin > `admin_saisie_resultats`) :

1. Sélectionner la compétition
2. Renseigner :
   - **Vainqueur final** (équipe championne)
   - **Meilleur marqueur** (essais) — Top 14 uniquement
   - **Meilleur scoreur** (points) — Top 14 uniquement
3. Vérifier que le classement des équipes est toujours correct (inchangé depuis la phase régulière)
4. Cliquer "Enregistrer les résultats officiels"

### Étape 2 : Lancer le calcul complet

Aller sur **Admin > Competition results** :
1. Sélectionner la ligne de la saison concernée
2. Dans le menu déroulant "Actions", choisir **"🏆 Recalculer TOUT (journées + classement + PODIUM + vainqueur) 🏆"**
3. Cliquer "Go"

Cette action va :
- ✅ Recalculer toutes les journées
- ✅ Recalculer les points de Flair
- ✅ **Bonus vainqueur** (si un joueur a prédit le bon champion)
- ✅ **Podium** (points 1er/2e/3e au classement général) → colonne verte **P**
- ✅ Bonus meilleur marqueur / meilleur scoreur (si saisi)

### Étape 3 : Vérifier

- Aller sur `/statistiques/` → sélectionner **Top 14** + **2025-2026**
- Vérifier que la colonne **P** (podium) affiche des points pour les 3 premiers
- Vérifier que la colonne **F** inclut le bonus vainqueur

---

## 6. Figer le classement pour l'évolution (optionnel, après chaque clôture)

Sur **Admin > Season scores** :
1. Filtrer par saison
2. Tout sélectionner
3. Action : **"Figer le classement pour l'évolution"**
   - Cela sauvegarde le `last_rank` de chaque joueur pour calculer l'évolution (+/▲) sur le dashboard

---

## 7. Importer l'historique Hall of Fame

Pour ajouter des saisons passées (avant que l'app n'existe), utiliser les scripts :

```bash
python import_history.py   # À partir de all_time.csv
```

Ou modifier directement la table `SeasonHistory` dans l'admin.

---

## 8. Gérer les utilisateurs

- **Admin > Users** : créer un user avec un mot de passe
- **Admin > Players** : créer un Player lié à ce user (même nom)
- Les joueurs se connectent sur `/accounts/login/`
- Ils peuvent changer leur mot de passe sur `/settings/`

---

## 9. Tâches récurrentes — Checklist hebdomadaire

- [ ] Créer la nouvelle journée (Round) si pas déjà fait
- [ ] Vérifier que les matchs sont créés avec les bonnes équipes
- [ ] Saisir les **horaires** (`kickoff_at`) pour le verrouillage automatique
- [ ] **Après les matchs** : saisir les scores + bonus offensifs
- [ ] Les points sont automatiquement calculés au premier affichage des résultats. Sinon, utiliser l'action admin **"🔥 Recalculer TOUT"** (section 4)

## 10. Checklist fin de saison

### Phase régulière
- [ ] Tous les matchs de la saison régulière ont leurs scores
- [ ] Aller sur `/admin/saisie-resultats/` → saisir le classement réel (sans vainqueur)
- [ ] Admin > Competition results → **"🔥 Recalculer TOUT (journées + points classement) 🔥"**
- [ ] Vérifier sur `/statistiques/` que la colonne **F** est remplie

### Phase finale
- [ ] Saisir les résultats des matchs de phase finale
- [ ] Aller sur `/admin/saisie-resultats/` → saisir vainqueur, meilleur marqueur, meilleur scoreur
- [ ] Admin > Competition results → **"🏆 Recalculer TOUT (journées + classement + PODIUM + vainqueur) 🏆"**
- [ ] Vérifier sur `/statistiques/` que la colonne **P** (podium) est remplie
- [ ] Admin > Season scores → figer le classement (optionnel)
- [ ] Ajouter une entrée dans `SeasonHistory` pour l'Historique (optionnel)

---

## 11. Architecture technique (pour mémoire)

| Route / Action | Ce qu'elle fait |
|---|---|
| `/admin/saisie-resultats/` | Saisir le classement réel, vainqueur, meilleur marqueur/scoreur |
| Admin → **"🔥 Recalculer TOUT (journées + points classement) 🔥"** | Recalcule toutes les journées + Flair. **Sans** podium/winner |
| Admin → **"🏆 Recalculer TOUT (journées + classement + PODIUM + vainqueur) 🏆"** | Recalcule toutes les journées + Flair + Podium + bonus vainqueur |
| Admin `SeasonScore` → **"Figer le classement"** | Sauvegarde le rang pour l'évolution sur le dashboard |
| `python manage.py generer_matchs` | Génère les matchs d'un round en CLI |

Les points de chaque match sont calculés dans `core/services/scoring.py` (fonction `calculate_match_points`). Les points de fin de saison sont calculés dans `compute_season_ranking_points` (même fichier).
