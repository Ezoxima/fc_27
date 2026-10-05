# Plan de reprise — fc_27

> Rédigé le **05/10/2026** après une pause depuis le 30/09.
> Sources : relecture des 15 sessions de travail précédentes (28/09 → 30/09),
> audit complet du code (lecture seule) et inspection de `fut27.db`.
> Aucun fichier n'a été modifié pour établir ce document.
>
> Ce fichier remplace `PLAN_record_server.md` comme document de suivi
> (ce dernier est terminé — voir Phase 6).

---

## Sommaire

1. [État actuel](#1-état-actuel)
2. [Décisions à prendre avant de coder](#2-décisions-à-prendre-avant-de-coder)
3. [Plan de reprise par phases](#3-plan-de-reprise-par-phases)
   - [Phase 1 — Sécurité & hygiène](#phase-1--sécurité--hygiène-local-sans-réseau)
   - [Phase 2 — Rafraîchir les données](#phase-2--rafraîchir-les-données-réseau-futgg)
   - [Phase 3 — Bugs du simulateur](#phase-3--bugs-du-simulateur)
   - [Phase 4 — Justesse des simulations](#phase-4--justesse-des-simulations)
   - [Phase 5 — Robustesse des scrapers](#phase-5--robustesse-des-scrapers)
   - [Phase 6 — Ménage](#phase-6--ménage)
   - [Phase 7 — Documentation](#phase-7--documentation)
   - [Backlog (idées non engagées)](#backlog-idées-non-engagées)
4. [Plan de test global](#4-plan-de-test-global)
5. [Annexes](#5-annexes)

---

## 1. État actuel

### 1.1 Ce qui existe et fonctionne

| Composant | Rôle | État |
|---|---|---|
| `fut27.db` | SQLite : `players` (19 911), `player_attributes` (19 861), `evolutions` (18, dont 11 actives), `used_evolutions` (11 lignes, ids 13-23) | ✅ cohérente avec le club GG Club du 30/09 |
| `scrape_players.py` | Cartes depuis fut.gg | ✅ (limite : voir 5.1) |
| `scrape_evolutions.py` | Évolutions + découverte via objectifs (`--skip-objectives`) ; marque les disparues comme expirées | ✅ (risque : voir 5.2) |
| `scrape_player_details.py` | Sous-stats carte par carte (reprend où il s'est arrêté) | ✅ — 50 cartes non traitées |
| `evolution_report.py` | Cœur métier : éligibilité, `apply_upgrades` avec plafonds et poids EA (`CATEGORY_WEIGHTS`), rapport Excel, `--list [--include-inactive]` | ✅ |
| `simulate_evolution.py` | Simulation CLI d'un joueur | ✅ |
| `record_evolution.py` | Enregistrer / historique / `--undo` en CLI | ✅ |
| `record_server.py` | Serveur local 127.0.0.1:8765 — `GET /api/usage`, `POST /api/record`, `GET /api/history`, `DELETE /api/history/<id>` + fichiers statiques | ⚠️ sécurité (Phase 1) |
| `fetch_my_evolutions.py` | Import des évolutions réellement appliquées via GG Club fut.gg (`--sync`, `--record`, `--dump-dir`, `--from-dump`, `--login-only`, `--game`) | ✅ connexion OK ; 0 écart avec la base |
| `export_web_data.py` + `build_webapp.py` | JSON embarqué → `simulateur.html` | ✅ build à jour du template, ⚠️ données périmées |
| `simulateur_template.html` | Chaîne d'évolutions, rejeu de l'historique, onglet « Mes évolutions » (modal joueur, Annuler), filtre « déjà évolués », toggle « Afficher épuisées/expirées (N) » | ✅ toggle terminé ; ⚠️ bugs (Phase 3) |
| `export_xlsx.py`, `optimize.py`, `playstyles.py` | Export complet façon Futbin ; ancien optimiseur sur CSV de club | ✅ / ⚠️ `optimize.py` divergent |

Qualité : les 13 `.py` compilent ; `ruff` ne remonte que 2 remarques de style
(`optimize.py:64` SIM102, `scrape_players.py:13` I001).

### 1.2 Évolutions en base au 30/09

| id | Nom | Active | Usages (utilisés/autorisés) | Joueur(s) |
|---|---|---|---|---|
| 2488 | Intro to Pathway Evolutions | oui | 1/1 | Geovany Quenda |
| 2489 | Repeat Delivery | oui | 1/2 | Daniel Yáñez — **en cours niv. 0/4** |
| 2490 | Intro to Training Camp EVOs | oui | 1/1 | Lucas Vázquez |
| 2491 | Intro to Evolutions | oui | 1/1 | Lucas Vázquez |
| 2492 | Intro to Repeatable Evolutions | oui | 2/2 | Carlos Espí ×2 |
| 2507 | Midfield Glow Up | oui | 1/1 | Xavi Espart — *peut-être partielle* |
| 2508 | Frontline Paradox | oui | 1/1 | Gabriel Jesus (branche « Option C Target Forward ») |
| 2524 | Pivot Shift | oui | 1/1 | Xavi Espart — **en cours niv. 0/3** |
| **2525** | **Flank Identity** | oui | **0/1** | — |
| **2527** | **Gallery Excellence** | oui | **0/1** | — |
| **2531** | **Trust the Keeper** | oui | **0/1** | — |
| 2500 | Believe | non | 1/1 | Gabriel Jesus |
| 2502 | Fullback Fork | non | 1/1 | Lucas Vázquez |
| 2501, 2503-2506 | Pinged Pass, OTW Retro 18/19/20, Creative Crossroads | non | 0/1 | — |

Encore disponibles : **2525, 2527, 2531** + 1 usage sur **2489**.

### 1.3 Fraîcheur des données (au 05/10)

| Donnée | Dernière mise à jour | Recommandé |
|---|---|---|
| Évolutions | entre le 28/09 soir et le 30/09 (≥ 5 jours) | tous les 1-2 jours |
| Cartes (`players`) | 30/09 (rescrape partiel, +41 cartes) | après chaque MAJ du jeu |
| Sous-stats (`player_attributes`) | 25-26/09 (~10 jours) ; **50 cartes manquantes** | quand de nouvelles cartes arrivent |
| Synchro GG Club | 30/09 18:45 UTC | après chaque évolution faite en jeu |
| `webapp_data.json` / `simulateur.html` | 30/09 20:34 — **avant** l'import club de 20:50 | après toute écriture en base |
| `rapport_evolutions.xlsx`, `export_complet.xlsx` | 28/09 20:25 | à la demande |

### 1.4 Historique des sessions (résumé)

| Date | Session | Livré |
|---|---|---|
| 28/09 | Création initiale | Scrapers, base, rapports Excel, simulateur avec chaîne, `used_evolutions`, `record_evolution.py` |
| 28/09 | Serveur d'enregistrement | `record_server.py`, bouton « Enregistrer » (`PLAN_record_server.md`) |
| 28/09 | Onglet évolutions perso | `/api/history`, `DELETE /api/history/<id>`, onglet « Mes évolutions », `showToast` |
| 28/09 | Stats et évolutions du joueur | Modal de détail joueur |
| 28/09 | Sélection joueurs en évolutions | Case « Joueurs déjà évolués uniquement » |
| 28/09 | Évolutions appliquées oubliées | Découverte des évolutions via objectifs (`discover_objective_evolutions`) |
| 28/09 | Calcul des stats | Poids EA par sous-stat (Python + JS) |
| 30/09 | Double évolution | Rejeu de l'historique dans `render()` ; export des évolutions inactives avec flag `active` |
| 30/09 | Mise à jour nouveaux joueurs | Rescrape partiel (+41 cartes) via `scrape_new_only.py` **resté hors projet** |
| 30/09 | Joueur lié à l'évolution | Clic « Mes évolutions » → carte évoluée cumulée (`evolvedPlayerAt`) |
| 30/09 | Import manuel GG Club | 9 lignes `used_evolutions` (13-21) |
| 30/09 | MAJ évolutions | Scrape complet, +2527, 7 évolutions passées expirées |
| 30/09 | FUT.GG API | `fetch_my_evolutions.py`, `.env`, `club_dump/`, lignes 22-23 |
| 30/09 | Épuisées/expirées | Toggle dans le sélecteur |

---

## 2. Décisions à prendre avant de coder

Ces points bloquent certaines tâches. Cocher la réponse retenue.

- **D1 — Évolutions « en cours » (lignes 22 et 23).** Le slot est bien consommé
  côté quota, mais le simulateur applique 100 % des gains alors que les joueurs
  sont au niveau 0.
  - [ ] **A (recommandé)** : garder la ligne (quota juste) et ajouter une colonne
    `level` / `max_level` dans `used_evolutions` ; le rejeu n'applique que les
    paliers atteints ; `fetch_my_evolutions.py` met à jour le niveau à chaque import.
  - [ ] B : ne compter que pour le quota, ne jamais rejouer une évolution non terminée.
  - [ ] C : statu quo (cartes surévaluées tant que l'évo n'est pas finie).
- **D2 — Ligne n°19 (Xavi Espart / Midfield Glow Up 2507).** Le dump portait un
  `partialEvolutionId` : terminée ou non ? → [ ] terminée [ ] partielle (traiter comme D1)
- **D3 — Cartes variantes (ex. Gabriel Jesus `ea_id` 50562314, base 230666).**
  Si la carte en base porte déjà les stats évoluées, le rejeu double les gains.
  - [ ] Vérifier sur 2-3 cas réels en comparant fut.gg et le simulateur, puis décider
    (rejouer depuis la carte de base `base_player_ea_id`, ou ne pas rejouer si la
    carte est déjà un item évolué `is_evolution_item`).
- **D4 — Supprimer le dossier `fut27/` (147 Mo, copie obsolète du 28/09) ?** [ ] oui [ ] archiver en zip
- **D5 — Versionner le projet avec git ?** [ ] oui (impose `.gitignore` en Phase 1) [ ] non
- **D6 — Feu vert pour les appels réseau fut.gg de la Phase 2 ?** [ ] oui

---

## 3. Plan de reprise par phases

Légende priorité : 🔴 bloquant / 🟠 important / 🟡 amélioration.

### Phase 1 — Sécurité & hygiène (local, sans réseau)

**But : plus aucune fuite possible du `.env` ; projet reproductible.**

> **Décisions du 05/10** : D6 oui · D5 git oui · D4 zip puis suppression (zip fait : `../fut27_archive_20261005.zip`, suppression de `fut27/` refusée par le garde-fou, à faire à la main) · D1 option A · D2 tranchée (Midfield Glow Up **terminée**) · D3 à vérifier.
>
> **Avancement 05/10 : Phase 3 terminée** — `/api/usage` renvoie aussi les expirées (+`active`), enregistrement/annulation rafraîchissent historique, usages et sélecteur, échappement HTML, libellé/style du toggle, tri stable. Testé dans le navigateur : T3, T4, T7 OK. Ménage 6.1-6.4 fait (zip + suppression `fut27/`, git initialisé).
>
> **Avancement 05/10 : Phase 2 terminée** — sauvegarde `fut27.backup-20261005.db` ; évolutions (+Goal Guardian 2538, Regista Realm 2537, Wing Specialization 2534, + 3 via objectifs ; expirées : Repeat Delivery, Frontline Paradox, Gallery Excellence) ; cartes via `scrape_players.py --only-new` (+1 208 traitées, 6.1 fait, 5.1 ON CONFLICT corrigé) ; 89 sous-stats ; club : Regista Realm (Xavi Espart, 0/3) enregistrée ; `simulateur.html` régénéré. Id 2494 (Carlos Espí) inconnue en base. 2.6 (Excel) non fait.
>
> **Avancement 05/10 : Phase 1 terminée et testée** (curl : `.env`/`fut27.db` → 404, `text/plain` → 415, Origin/Host étrangers → 403, simulateur → 200). `.gitignore` créé avec `fut27.db` inclus (à retirer si D5 = oui).

- [x] 🔴 **1.1 Restreindre les fichiers servis par `record_server.py`** (`record_server.py:67`, `super().do_GET()` sert tout le dossier : `.env` avec le mot de passe fut.gg en clair, `fut27.db`, `club_dump/state.json`).
  - N'autoriser que `/` et `/simulateur.html` ; 404 pour tout le reste.
- [x] 🔴 **1.2 Contrôler l'origine des requêtes.**
  - Refuser si l'en-tête `Host` n'est pas `127.0.0.1:<port>` ou `localhost:<port>` (protection DNS rebinding).
  - Sur `POST` / `DELETE` : refuser si `Origin` est présent et différent de l'hôte local (CSRF).
  - Exiger `Content-Type: application/json` sur `POST /api/record` (`record_server.py:125-128`) : un `text/plain` cross-site passe aujourd'hui sans preflight.
- [x] 🟡 **1.3 Robustesse serveur** : gérer `Content-Length` invalide et les erreurs SQLite (réponse JSON 400/500 au lieu d'une exception).
- [x] 🟠 **1.4 `.gitignore`** : `.env`, `club_dump/`, `__pycache__/`, `.ruff_cache/`, `*.xlsx`, `~$*`, `webapp_data.json`, `simulateur.html` (régénérables), `fut27.db` (à trancher si D5 = oui).
- [x] 🟠 **1.5 `requirements.txt`** : `requests`, `beautifulsoup4`, `openpyxl`.
- [x] 🟠 **1.6 Remplacer les `eval()`** (`export_web_data.py:37`, `evolution_report.py:308`, `export_xlsx.py:57`).
  - Cause : `scrape_players.py:108` stocke `str(list)` dans `alternative_positions` alors que le schéma annonce du JSON.
  - Correctif : écrire `json.dumps(...)` au scrape ; lire avec un helper tolérant (`json.loads`, repli `ast.literal_eval` pour les lignes existantes) ; optionnel : migration one-shot des lignes en base.

**Vérification** : `curl http://127.0.0.1:8765/.env` → 404 ; `curl http://127.0.0.1:8765/simulateur.html` → 200 ; un POST `text/plain` → 415 ; le bouton « Enregistrer » de la page fonctionne toujours.

### Phase 2 — Rafraîchir les données (réseau fut.gg)

**But : base et simulateur à jour au 05/10.** Nécessite D6. Respecter les délais entre requêtes ; `robots.txt` de fut.gg interdit `/api/*` → ne jamais lancer en boucle.

- [ ] 🔴 **2.1 Évolutions** : `python scrape_evolutions.py --out fut27.db`
  - Contrôler le résumé : nouvelles évolutions, passées expirées. Si **toutes** passent expirées → probable changement de mise en page fut.gg (voir 5.2), restaurer la sauvegarde.
- [ ] 🟠 **2.2 Cartes** : récupérer d'abord `scrape_new_only.py` (voir 6.1), sinon `python scrape_players.py --out fut27.db`.
- [ ] 🟠 **2.3 Sous-stats manquantes** : `python scrape_player_details.py --db fut27.db` (reprend les 50 cartes sans `player_attributes` + les nouvelles).
- [ ] 🟠 **2.4 Club** : `python fetch_my_evolutions.py --sync` (lecture seule) → relire → `--record` si de nouvelles évolutions apparaissent.
- [ ] 🔴 **2.5 Régénérer le simulateur** :
  ```bash
  python export_web_data.py --db fut27.db --out webapp_data.json
  python build_webapp.py
  ```
- [ ] 🟡 **2.6 Rapports Excel** (si utilisés) : `python evolution_report.py --db fut27.db --all --out rapport_evolutions.xlsx` et `python export_xlsx.py --db fut27.db --out export_complet.xlsx`.

**Avant de commencer** : copier `fut27.db` en `fut27.backup-AAAAMMJJ.db`.

**Vérification** : `python evolution_report.py --db fut27.db --list` ; en double-clic sur `simulateur.html`, Pivot Shift apparaît bien `[EPUISEE]`.

### Phase 3 — Bugs du simulateur

**But : l'affichage reste juste après chaque action, sans recharger la page.**

- [x] 🟠 **3.1 `/api/usage` ignore les évolutions expirées** (`record_server.py:119`, `include_inactive=False`, et le champ `active` n'est pas renvoyé).
  - Conséquence : la fusion par id (`simulateur_template.html:1107-1124`) ne met jamais à jour l'usage des évolutions expirées, et une évolution expirée **après** le build reste proposée.
  - Correctif : `include_inactive=True`, renvoyer `active`, fusionner `active` côté page.
- [x] 🟠 **3.2 Double comptage après enregistrement** (`recordEvolutionUsage`, `simulateur_template.html:949-976`).
  - Elle ne recharge pas `historyEntries`. Après un passage par « Mes évolutions », le `render()` suivant rejoue l'évolution depuis l'historique (`:1008-1020`) **et** la garde dans la chaîne → appliquée deux fois. Le filtre « déjà évolués » est aussi en retard.
  - Correctif : après succès, recharger l'historique et retirer l'étape enregistrée de la chaîne (ou l'exclure du rejeu).
- [x] 🟠 **3.3 « Annuler » ne rafraîchit pas les usages** (`undoHistoryEntry`, `:1262-1277`).
  - Correctif : rappeler `/api/usage`, puis reconstruire le sélecteur avec `rebuildEvoSelectOptions()`, puis `render()`.
- [x] 🟡 **3.4 Petits défauts UI**
  - Bouton toggle sans libellé avant la fin de `init()` → texte par défaut dans le HTML.
  - Pas de style `:disabled` sur le toggle.
  - Tri du modal sans départage par id (`:1184`) → ordre instable pour des dates identiques.
  - Noms et notes injectés via `innerHTML` → passer par `textContent` (risque faible, local).
- [x] 🟡 **3.5 Mettre à jour `PLAN_record_server.md:52-56`** ou l'archiver (il décrit l'ancien contrat de `/api/usage`).

**Vérification** : scénarios T3 à T6 du plan de test (section 4).

### Phase 4 — Justesse des simulations

Dépend de D1, D2, D3.

- [ ] 🟠 **4.1 Évolutions en cours** (selon D1).
  - Pour l'option A :
    - migration : `ALTER TABLE used_evolutions ADD COLUMN level INTEGER` et `max_level INTEGER` ;
    - `fetch_my_evolutions.py:139-147` écrit le niveau ; à chaque import, mise à jour du niveau d'une ligne existante au lieu de l'ignorer ;
    - rejeu partiel dans `apply_upgrades` (Python) et `applyUpgrades` (JS).
  - Prérequis : vérifier dans `upgrades_json` que les gains sont bien découpés par palier.
- [ ] 🟠 **4.2 Cartes variantes** (selon D3) : corriger le point de départ du rejeu.
- [ ] 🟠 **4.3 Branches Pathway.**
  - Le dump GG Club fournit `evolutionPathChoices` (ex. Gabriel Jesus `[[1,1,3],[]]`, Lucas Vázquez `[[],[],[1,1,2]]`).
  - Aujourd'hui `upgrades_text` ne stocke qu'**une** branche (« Upgrades A/B… »), pas un tronc commun. « Intro to Pathway » (2488) et « Intro to Training Camp » (2490) ont 0 upgrade en base.
  - Étapes :
    - (a) scraper toutes les branches dans `scrape_evolutions.py` (structure `branches: [...]`) ;
    - (b) stocker le choix dans `used_evolutions` (colonne `path_choices` JSON) depuis `fetch_my_evolutions.py` ;
    - (c) rejouer la bonne branche ;
    - (d) dans le simulateur, proposer un sélecteur de branche pour une nouvelle évolution Pathway.
- [ ] 🟠 **4.4 Gardiens** : Trust the Keeper (2531, active) donne `+9 POS`, une stat non mappée.
  - Diving, Handling, Kicking, Reflexes et Positioning (GK) n'ont pas de catégorie, et Reactions ajoute 9 au champ `dri` d'un gardien.
  - Ajouter le mapping des catégories GK (DIV/HAN/KIC/REF/SPD/POS) en Python et en JS, et retirer le commentaire obsolète (`simulateur_template.html:483`, « pas de vraies évolutions GK »).
- [ ] 🟡 **4.5 Poids du Dribbling** : Carlos Espí affiche 72 au lieu de 73 (72,45 avec les poids actuels).
  - Relever 2-3 cartes évoluées réelles (fut.gg), ajuster `CATEGORY_WEIGHTS` côté Python **et** JS.
- [ ] 🟡 **4.6 Une seule source de vérité pour les constantes**.
  - Aujourd'hui, alias, poids et listes de sous-stats sont dupliqués entre Python et JS.
  - Correctif : les exporter dans `webapp_data.json` (`meta.weights`, …) et les lire côté JS.

**Vérification** : comparer 5 joueurs du club (Xavi Espart, Carlos Espí, Gabriel Jesus, Lucas Vázquez, Daniel Yáñez) avec leurs cartes réelles sur fut.gg / GG Club — écart toléré : 0.

### Phase 5 — Robustesse des scrapers

- [ ] 🟠 **5.1 `scrape_players.py:93-97`** : l'`ON CONFLICT` ne met à jour ni stats, ni postes, ni club.
  - Conséquence : les cartes dynamiques restent périmées, et `scrape_player_details.py` ne re-scrape jamais une carte déjà traitée.
  - Correctif : mettre à jour toutes les colonnes variables. Ajouter `players.scraped_at` et une option `--refresh-details` (re-scrape des sous-stats si la carte a changé).
- [ ] 🟠 **5.2 `scrape_evolutions.py:442`** passe tout à `active=0` avant de réactiver ce qui est trouvé.
  - Correctif : si 0 évolution trouvée (ou chute anormale), annuler la transaction et afficher une erreur.
  - Ajouter `evolutions.last_seen_at` pour dater la fraîcheur.
- [ ] 🟡 **5.3 `fetch_my_evolutions.py:217`** : la déduplication par `(evolution_id, ea_id)` crée des doublons si une ligne manuelle n'a pas d'`ea_id`. Ajouter un repli sur le nom du joueur.
- [ ] 🟡 **5.4 `optimize.py`** : logique divergente (inclut les expirées, ignore `used_evolutions`, ni postes alternatifs ni plafonds).
  - [ ] Soit le réécrire sur `evolution_report` (charger le club depuis GG Club via `fetch_my_evolutions` plutôt qu'un CSV).
  - [ ] Soit le retirer.
- [ ] 🟡 **5.5 Connexion par jeton** (`FUTGG_REFRESH_TOKEN`) pour les comptes fut.gg liés à Google — proposé le 30/09, non codé. Optionnel tant que la connexion par mot de passe fonctionne.

### Phase 6 — Ménage

- [x] 🟠 **6.1 Récupérer `scrape_new_only.py`** (rescrape limité aux paliers d'overall modifiés).
  - Il n'existe que dans le scratchpad temporaire de la session du 30/09 « Mise à jour nouveaux joueurs ».
  - Si introuvable : le réintégrer comme option `--only-new` de `scrape_players.py`.
- [x] 🟠 **6.2 Dossier `fut27/`** (147 Mo) : supprimer ou zipper (D4).
  - Il ne contient rien d'unique : scripts identiques ou plus anciens, base du 28/09 sans usages, 6 `rapport_evolutions_v*.xlsx`, logs, 3 verrous `~$*.xlsx`.
- [x] 🟡 **6.3 Racine** : supprimer `__pycache__/` et `.ruff_cache/` (régénérés automatiquement).
- [x] 🟡 **6.4 `PLAN_record_server.md`** → déplacer dans `docs/archive/` (terminé ; numéros de ligne périmés).
- [ ] 🟡 **6.5 `my_club_example.csv`** : à garder seulement si `optimize.py` est conservé.
- [ ] 🟡 **6.6 Style** : `ruff check --fix .` (2 remarques).

### Phase 7 — Documentation

Mettre à jour `README.md` (inchangé depuis le 28/09) :

- [ ] **7.1 Nouvelles sections**
  - `fetch_my_evolutions.py` : prérequis GG Club, `.env` / `.env.example`, toutes les options, `club_dump/`.
  - **Workflow quotidien recommandé** (voir annexe 5.1).
  - Interface du simulateur : onglet « Mes évolutions », modal joueur, bouton Annuler, filtre « Joueurs déjà évolués », toggle épuisées/expirées, rejeu automatique de l'historique.
  - API du serveur : `GET /api/usage`, `POST /api/record`, `GET /api/history`, `DELETE /api/history/<id>`, et les restrictions ajoutées en Phase 1.
  - Options : `evolution_report --include-inactive`, `scrape_evolutions --skip-objectives` (découverte via les objectifs).
- [ ] **7.2 Corrections**
  - `used_evolutions` est aussi alimentée par le serveur et par `fetch_my_evolutions.py`, pas seulement `record_evolution.py`.
  - La table `evolutions` conserve les expirées (`active = 0`).
  - « Limites connues » :
    - les poids EA (`CATEGORY_WEIGHTS`) sont appliqués, ce n'est plus une moyenne ;
    - Pathway : une seule branche est stockée, pas un tronc commun (à réécrire après 4.3) ;
    - les évolutions en cours (après 4.1).
- [ ] **7.3 Installation** : `pip install -r requirements.txt`.
- [ ] **7.4** Tenir ce fichier à jour (cocher, dater) jusqu'à la fin de la reprise, puis l'archiver.

---

### Backlog (idées non engagées)

- Afficher le **Rôle+** gagné par une évolution dans le simulateur (proposé le 28/09).
- Classement « meilleur joueur de mon club pour chaque évolution active », à partir du club GG Club : remplacerait `optimize.py`.
- Planifier `scrape_evolutions.py` + `fetch_my_evolutions.py` une fois par jour (tâche planifiée Windows), avec des délais respectueux.
- Tests automatisés minimaux (`pytest`) sur `apply_upgrades` avec les 5 joueurs de référence de la Phase 4.

---

## 4. Plan de test global

À dérouler après les Phases 1 + 3 (et à rejouer après la 4). Toujours tester sur une **copie** de `fut27.db` (`python record_server.py --db copie.db`).

| # | Scénario | Attendu |
|---|---|---|
| T1 | `curl -i http://127.0.0.1:8765/.env` et `/fut27.db` | 404 |
| T2 | POST `/api/record` en `text/plain` ou avec `Origin: https://exemple.com` | refusé (4xx), rien en base |
| T3 | Enregistrer une évo depuis la chaîne, puis aller dans « Mes évolutions » et revenir | stats comptées une seule fois |
| T4 | Annuler une ligne dans « Mes évolutions » | l'évo redevient disponible dans le sélecteur sans recharger |
| T5 | Marquer une évo `active=0` en base, serveur lancé, recharger | l'évo passe `[EXPIREE]` et se masque |
| T6 | Ouvrir `simulateur.html` en double-clic | aucun appel bloquant, données cohérentes avec la base au dernier build |
| T7 | Sélectionner un joueur déjà évolué + ajouter une évo | stats « avant » de l'étape 1 incluent l'historique (rejeu) |
| T8 | Clic sur un joueur dans « Mes évolutions » | ouvre la carte évoluée cumulée |
| T9 | `python record_evolution.py --history` / `--undo <id>` | compatible avec les lignes écrites par le serveur et par fetch |
| T10 | `python fetch_my_evolutions.py --from-dump club_dump --db copie.db` | 0 nouvelle évolution, 0 id inconnu |
| T11 | Trust the Keeper sur un gardien | stats GK modifiées, pas le `dri` |

T7 et T8 n'avaient jamais été vérifiés dans le navigateur.

---

## 5. Annexes

### 5.1 Workflow quotidien cible (après reprise)

```bash
python scrape_evolutions.py --out fut27.db           # nouvelles évos / expirées
python fetch_my_evolutions.py --sync --record        # ce que j'ai fait en jeu
python export_web_data.py --db fut27.db --out webapp_data.json
python build_webapp.py
python record_server.py                              # puis http://localhost:8765/simulateur.html
```

À l'arrivée de nouvelles cartes (TOTW, promos) : `scrape_players.py` (ou `--only-new`), puis `scrape_player_details.py`.

### 5.2 Schéma actuel de la base

```
players(id PK, ea_id, base_player_ea_id, common_name, first_name, last_name, overall,
        position, alternative_positions, rarity_name, quality, club, league, nation,
        pace, shooting, passing, dribbling, defending, physicality, weak_foot,
        skill_moves, foot, height, age, is_evolution_item, is_icon, is_hero, price,
        slug, url, raw_json, playstyles_plus, playstyles_normal)
player_attributes(player_id PK→players, detail_stats_json, scraped_at)
evolutions(id PK, slug, name, description, requirements_text, requirements_json,
           upgrades_text, upgrades_json, url, coin_cost, point_cost,
           granted_playstyles, repeatability_count, active)
used_evolutions(id PK AUTOINCREMENT, evolution_id→evolutions, player_ea_id,
                player_name, date_applied, notes)
```

Évolutions de schéma envisagées par ce plan :

- `used_evolutions` : `level`, `max_level` (4.1) et `path_choices` (4.3) ;
- `players` : `scraped_at` (5.1) ;
- `evolutions` : `last_seen_at` (5.2), et branches Pathway (4.3).

### 5.3 Fichiers sensibles

- `.env` : identifiants fut.gg en clair. Ne jamais le partager ni le servir (Phase 1).
- `club_dump/` : contient `ggClubId`, `userId` et le username EA. Privé.

### 5.4 Ordre de réalisation conseillé

```
D1-D6 (décisions) ─┐
Phase 1 ───────────┼─► Phase 2 ─► Phase 3 ─► Phase 4 ─► Phase 5 ─► Phase 6 ─► Phase 7
(sécurité, 30 min) │   (données)   (bugs)     (calculs)   (scrapers)  (ménage)   (doc)
```

Les Phases 1 et 6.1 peuvent démarrer tout de suite, sans aucune décision.
