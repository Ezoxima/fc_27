# FC 27 Ultimate Team — base de cartes + outils d'évolutions

Base de données locale des cartes EA SPORTS FC 27 Ultimate Team (scrapée sur
**fut.gg**), plus un ensemble d'outils pour savoir quels joueurs sont
éligibles à quelle évolution, simuler leurs stats avant/après (y compris en
chaînant plusieurs évolutions), et suivre lesquelles tu as déjà utilisées
(la plupart sont à usage unique par compte).

## Installation

```bash
pip install requests beautifulsoup4 openpyxl
```

## Fichiers

### Base de données

- **`fut27.db`** (SQLite, ~25 Mo) — la base elle-même. Contient :
  - `players` : ~19 900 cartes (ratings, poste, rareté, club/ligue/nation,
    playstyles, stats principales PAC/SHO/PAS/DRI/DEF/PHY...)
  - `player_attributes` : le détail complet des ~34 sous-stats par carte
    (Acceleration, Finishing, Vision, etc. — comme sur Futbin)
  - `evolutions` : les évolutions actives (conditions, gains précis par
    sous-stat avec plafond, coût, playstyle(s) accordé(s), nombre d'usages
    autorisés, statut actif/expiré)
  - `used_evolutions` : historique des évolutions que tu as réellement
    appliquées (alimenté par `record_evolution.py`)

### Scripts de collecte (à relancer périodiquement)

| Script | Rôle | Fréquence |
|---|---|---|
| `scrape_players.py` | Récupère/actualise toutes les cartes | Après chaque mise à jour du jeu |
| `scrape_evolutions.py` | Récupère les évolutions actives (conditions, gains, coût, playstyle accordé, usages autorisés) et marque comme expirées celles qui ont disparu de fut.gg | Tous les 1-2 jours (les évolutions changent souvent) |
| `scrape_player_details.py` | Récupère le détail des sous-stats carte par carte (une requête par carte, donc long ~2h pour toute la base) | Une fois suffit tant que `scrape_players.py` n'ajoute pas beaucoup de nouvelles cartes |

```bash
python scrape_players.py --out fut27.db
python scrape_evolutions.py --out fut27.db
python scrape_player_details.py --db fut27.db     # long ; reprend où il s'est arrêté si interrompu
```

### Outils d'analyse

- **`evolution_report.py`** — le cœur de la logique (éligibilité, projection
  des stats avec plafonds, gestion des usages). Génère aussi le rapport
  Excel.

  ```bash
  python evolution_report.py --db fut27.db --list                 # voir les évolutions actives + usages restants
  python evolution_report.py --db fut27.db --evolution 2507 --out rapport.xlsx
  python evolution_report.py --db fut27.db --all --out rapport_evolutions.xlsx   # un onglet par évolution active
  ```

- **`simulate_evolution.py`** — simulation rapide en ligne de commande sur un
  seul joueur, sans repasser par Excel.

  ```bash
  python simulate_evolution.py --db fut27.db --evolution 2507 --player "Simon Sohm"
  ```

- **`record_evolution.py`** — enregistre une évolution que tu as **réellement
  réalisée** dans le jeu. La plupart des évolutions sont à usage unique par
  compte ; une fois enregistrées ici, elles disparaissent automatiquement des
  rapports (Excel, simulateur web, CLI).

  ```bash
  python record_evolution.py --evolution 2507 --player "Simon Sohm" --notes "optionnel"
  python record_evolution.py --history
  python record_evolution.py --undo 4      # supprime l'enregistrement n°4 (erreur de saisie)
  ```

- **`optimize.py`** — variante plus ancienne qui ne regarde que TON club
  (fourni via un CSV, voir `my_club_example.csv`), plutôt que toute la base.

  ```bash
  python optimize.py --club mon_club.csv --db fut27.db
  python optimize.py --club mon_club.csv --weights "pace=2,dribbling=1.5,shooting=1"
  ```

- **`export_xlsx.py`** — export complet de la base (toutes les cartes, toutes
  les colonnes) façon Futbin, sans lien avec les évolutions.

  ```bash
  python export_xlsx.py --db fut27.db --out export_complet.xlsx
  python export_xlsx.py --db fut27.db --out export_st.xlsx --position ST --min-overall 80
  ```

### Simulateur interactif (page web)

`simulateur.html` peut s'ouvrir de deux façons :

- **En double-clic** (aucun serveur requis) : la page s'ouvre en lecture
  seule sur le snapshot figé embarqué au dernier `build_webapp.py`. Tout
  fonctionne sauf le bouton "Enregistrer" (voir ci-dessous).
- **Via `record_server.py`** (recommandé si tu veux enregistrer tes
  évolutions directement depuis la page) :

  ```bash
  python record_server.py            # options : --port (défaut 8765), --db (défaut fut27.db)
  ```

  puis ouvre `http://localhost:8765/simulateur.html`. Le serveur ne sert que
  les fichiers du dossier courant et une petite API (`/api/usage`,
  `/api/record`), bindée sur `127.0.0.1` uniquement (pas d'exposition
  réseau).

Le simulateur permet de :

- chercher un joueur par nom (recherche + Entrée pour prendre le premier résultat)
- construire une **chaîne** de plusieurs évolutions (ajoutées dans l'ordre,
  chacune calculée à partir du résultat de la précédente)
- voir l'éligibilité (bandeau vert/rouge avec le détail des raisons si refusé)
- voir les cartes de stats avant/après façon fut.gg (nation/ligue/club/qualité,
  skills/pied faible en étoiles, playstyles, 6 catégories de stats avec
  sous-détail)
- voir si une évolution est payante ou déjà épuisée (nombre d'usages restants)
- **si le serveur tourne** : cliquer "Enregistrer cette évolution" sur une
  étape de la chaîne écrit directement dans `used_evolutions` (même insertion
  que `record_evolution.py`) et rafraîchit aussitôt le dropdown et le bandeau
  "épuisée"/"usages restants" de toutes les étapes concernées, sans recharger
  la page. Si le serveur n'est pas lancé, le clic affiche un message d'erreur
  discret et n'empêche pas le reste de la page de fonctionner.

Pour le régénérer après une mise à jour de la base (recommandé de temps en
temps même en utilisant le serveur, pour que le fichier statique embarqué
reflète aussi les derniers usages enregistrés) :

```bash
python export_web_data.py --db fut27.db --out webapp_data.json
python build_webapp.py
```

(`simulateur_template.html` est le code source ; `simulateur.html` est le
fichier final avec les données embarquées — c'est celui-là qu'on ouvre. Ni
l'un ni l'autre n'est modifié par `record_server.py` : seule l'API
`/api/usage` reflète l'état live.)

## Limites connues

- Les évolutions de type "Pathway" (embranchements, ex: certaines évolutions
  proposent un choix final entre deux orientations) n'ont ici que le tronc
  commun des gains ; le choix final entre les deux branches n'est pas
  modélisé automatiquement.
- Le calcul des stats principales (Pace, Shooting...) est une moyenne des
  deltas plafonnés de toutes leurs sous-stats fixes — cohérent avec le jeu
  pour Pace (documenté : moyenne d'Acceleration/Sprint Speed), approximatif
  pour les 5 autres catégories dont la pondération exacte n'est pas publique.
- Les données viennent d'un site communautaire (fut.gg), pas d'EA
  directement : fiables en pratique mais pas garanties à 100 %, et peuvent
  changer de format sans préavis.
- `repeatability_count` (nombre d'usages autorisés par évolution) vient d'un
  champ interne du site (`repeatabilityCount`), pas d'une API documentée —
  fiable à ce jour mais pourrait changer.
- Scripts prévus pour un usage personnel raisonnable (délai entre requêtes,
  User-Agent identifiable) — évite de les lancer en boucle serrée.
