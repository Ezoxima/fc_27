# Plan d'implémentation — bouton "Enregistrer" dans le simulateur

Statut : **implémenté et testé** (`record_server.py` créé, `simulateur_template.html`
modifié, `README.md` à jour). Les 6 points du plan de test en bas de ce
document ont été vérifiés sur une copie de `fut27.db` avant validation.

## Objectif

`simulateur.html` est aujourd'hui 100% statique (ouvert en double-clic, sans
backend) : impossible d'écrire dans `used_evolutions` depuis la page. On veut
un vrai bouton "Enregistrer" par étape de la chaîne, qui écrit directement en
base via un petit serveur local, et qui réaffiche l'état à jour (dropdown +
bandeau "épuisée") sans recharger la page.

## Constats tirés du code existant (à respecter dans l'implémentation)

- Schéma confirmé (`fut27.db`) :
  `used_evolutions(id, evolution_id, player_ea_id, player_name, date_applied, notes)`,
  `evolutions.repeatability_count` / `evolutions.active`.
- [evolution_report.py](evolution_report.py) fonction `load_evolutions(conn, include_inactive=False)`
  (ligne 78) est déjà la source de vérité pour `used_count` / `remaining_uses`
  (calculés à partir de `used_evolutions`). **Le serveur doit réutiliser cette
  fonction**, ne pas réimplémenter le calcul.
- [record_evolution.py](record_evolution.py) fonction `record()` (ligne 23) est déjà
  l'insertion canonique dans `used_evolutions`. **Le serveur doit l'appeler
  directement.**
- [simulateur_template.html](simulateur_template.html) ligne 280 :
  `const DATA = /*__DATA__*/;` est un objet synchrone, et tout le dropdown
  d'évolutions + le wiring des événements (lignes 559 à 631) s'exécutent
  immédiatement à la suite, en lisant `DATA.evolutions` tel quel. C'est le
  point d'accroche pour la fusion `/api/usage`.
- Ligne 707 : `applyUpgrades()` fait `Object.assign({}, p, {detail})`
  (ligne 398) — donc `current.eaId` traverse bien toute la chaîne d'étapes
  sans se perdre. Confirmé utilisable tel quel pour le POST.
- `webapp_data.json` (généré par [export_web_data.py](export_web_data.py)) est un
  **snapshot figé** injecté dans `simulateur.html` au build par
  [build_webapp.py](build_webapp.py). Le serveur ne doit **jamais** modifier ce
  fichier ni `simulateur.html` — seule l'API `/api/usage` donne l'état live.

## 1. Nouveau fichier : `record_server.py` (stdlib uniquement)

- Basé sur `http.server.ThreadingHTTPServer` + une classe dérivée de
  `SimpleHTTPRequestHandler` (héritage pour garder gratuitement le service de
  fichiers statiques du dossier courant — sert `simulateur.html` sans code de
  servage custom).
- `do_GET` : si `self.path` commence par `/api/`, router vers le handler API ;
  sinon `super().do_GET()` (fichier statique classique).
- `do_POST` : uniquement `/api/record`, 404 sinon.
- Connexion SQLite **ouverte par requête** (`sqlite3.connect(db_path, timeout=5)`,
  fermée à la fin de la requête) : évite tout verrou partagé entre threads,
  suffisant pour un outil local mono-utilisateur.
- **`GET /api/usage`** : appelle
  `evolution_report.load_evolutions(conn, include_inactive=False)` (même
  filtre `active=1` que celui utilisé pour peupler `DATA.evolutions` côté
  export, afin que la fusion soit cohérente id-à-id). Renvoie
  `[{id, usedCount, remainingUses}, ...]` en JSON.
- **`POST /api/record`** : body JSON
  `{evolutionId, playerEaId, playerName, notes}` →
  1. validation minimale (`evolutionId` et `playerName` présents) → `400`
     `{ok:false, error:...}` sinon
  2. vérifie que l'évolution existe via
     `load_evolutions(conn, include_inactive=True)` (comme le fait déjà
     `record_evolution.py` pour pouvoir enregistrer même une évo expirée)
     → `404` sinon
  3. appelle `record_evolution.record(conn, evolutionId, playerEaId, playerName, notes)`
  4. recalcule `used_count` / `remaining_uses` pour **cette seule évolution**
     et renvoie `{ok:true, evolutionId, usedCount, remainingUses}`
- Bind sur `127.0.0.1` uniquement (pas d'exposition réseau).
- `--port` (défaut **8765**) et `--db` (défaut `fut27.db`) configurables en
  arguments CLI.
- Import direct de `evolution_report` et `record_evolution` (le serveur tourne
  depuis la racine du projet, donc l'import fonctionne tel quel sans
  packaging particulier).

## 2. Modifications de `simulateur_template.html`

- **Restructuration de l'init** : le bloc actuellement exécuté en top-level
  (build du `<select>` d'évolutions lignes 559–571, wiring des listeners
  lignes 584–641) est déplacé dans une fonction `init()` appelée après une
  tentative de fusion `/api/usage`.
- Au chargement : `fetch('/api/usage', {signal: AbortSignal.timeout(1200)})`
  dans un `try/catch` :
  - échec (page ouverte en double-clic/`file://`, ou serveur non lancé) →
    catch silencieux, on continue avec `DATA.evolutions` tel quel
    (comportement actuel inchangé, page reste utilisable en statique pur) ;
  - succès → fusion de `usedCount` / `remainingUses` dans `DATA.evolutions`
    par `id`, **avant** de construire le dropdown, pour que les statuts
    `[EPUISEE]` / `[X restants]` soient à jour dès l'affichage initial.
- Extraction de la construction du `<select>` (lignes 559–571) dans une
  fonction `rebuildEvoSelectOptions()` réutilisable — appelée à l'init puis
  après chaque enregistrement réussi, pour rafraîchir les libellés sans
  dupliquer la logique.
- **Bouton "Enregistrer cette évolution"** ajouté dans le header/summary de
  chaque étape (zone lignes 675–694 du template actuel) :
  - au clic → `POST /api/record` avec
    `{evolutionId: evo.id, playerEaId: current.eaId, playerName: current.name, notes: null}`
    (`current` = l'état du joueur *avant* cette étape dans la boucle
    `chain.forEach`, donc bien `current.eaId`, stable sur toute la chaîne) ;
  - bouton désactivé + libellé "Enregistrement…" pendant la requête ;
  - succès → met à jour l'entrée `evo.id` dans `DATA.evolutions` avec la
    réponse, appelle `rebuildEvoSelectOptions()` puis `render()` : ça
    rafraîchit automatiquement le dropdown ET le bandeau
    "épuisée"/"usages restants" de **toutes** les étapes de la chaîne
    référençant cette même évolution, sans recharger la page ;
  - échec réseau (serveur non lancé) → message inline discret
    ("Serveur local non disponible — lance `record_server.py`"), bouton
    réactivé, aucune exception non gérée ;
  - `playerEaId` peut être `null` (certains joueurs n'ont pas d'`ea_id` en
    base) — accepté tel quel par le serveur, la colonne est nullable.

## 3. Décisions retenues (ajustables à l'implémentation si besoin)

- **Pas de champ "notes"** dans l'UI pour ce premier jet — le bouton envoie
  `notes: null`. Ajoutable facilement plus tard ; `record_evolution.py
  --notes` reste disponible en CLI pour les cas où une annotation est utile.
- **Le bouton reste cliquable même si l'évolution affiche déjà "épuisée"**
  (même comportement que le CLI, `record_evolution.py` lignes 106–110, qui
  avertit mais enregistre quand même) — évite de bloquer un cas légitime
  (quota qui a changé sur fut.gg).
- **Port par défaut 8765.**

## 4. Documentation à ajouter dans `README.md`

Section expliquant :
```
python record_server.py            # options : --port, --db
```
puis ouvrir `http://localhost:8765/simulateur.html`, avec une note explicite
que `simulateur.html` ouvert en double-clic continue de fonctionner en
lecture seule (snapshot figé), et qu'il est conseillé de relancer
`export_web_data.py` + `build_webapp.py` de temps en temps pour que le
fichier statique embarqué reflète aussi les derniers usages enregistrés hors
serveur.

## 5. Plan de test réel avant de considérer la tâche terminée

1. Lancer `record_server.py`, ouvrir `http://localhost:PORT/simulateur.html`
   dans le navigateur.
2. Sélectionner un joueur + chaîner une évolution, cliquer "Enregistrer".
3. Vérifier en base
   (`SELECT * FROM used_evolutions ORDER BY id DESC LIMIT 1`) que la ligne
   est bien insérée avec le bon `player_ea_id`.
4. Vérifier que le dropdown et le bandeau de l'étape passent à
   "épuisée"/"X restants" sans reload.
5. Couper le serveur, recharger la page en statique pur → vérifier que rien
   ne casse (fallback silencieux) et que le bouton affiche l'erreur réseau
   proprement au clic.
6. Vérifier `record_evolution.py --undo <id>` pour confirmer que l'écriture
   est compatible avec les outils CLI existants.
