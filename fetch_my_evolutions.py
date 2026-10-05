"""
Récupère les évolutions réellement appliquées sur TON club, via le "GG Club"
de fut.gg (club synchronisé côté serveur depuis ton compte EA), et peut les
enregistrer dans used_evolutions à la place de record_evolution.py.

Prérequis (une seule fois, sur le site) : être connecté à fut.gg, avoir lié
son compte EA dans GG Club (https://www.fut.gg/gg-club/) et fait au moins une
synchro. Identifiants fut.gg dans un fichier .env (voir .env.example).

API non documentée, reconstituée depuis le front de fut.gg :
  POST /api/supabase/sign-in/        {identifier, password} -> {accessToken, refreshToken}
  GET  /api/gg-club/state/           état du compte (liaison EA, plateforme...)
  GET  /api/gg-club/sync-status/     statut de la dernière synchro
  POST /api/gg-club/sync/            déclenche une synchro du club
  GET  /api/gg-club/players/?game=27&page=N&count=M   joueurs du club
Chaque joueur évolué porte evolutionPath (ids des évolutions appliquées, dans
l'ordre) et éventuellement activeEvolution {evolutionId, level, maxLevel}.

Usage:
    python fetch_my_evolutions.py                  # affiche les évolutions trouvées (lecture seule)
    python fetch_my_evolutions.py --sync           # relance d'abord une synchro du club
    python fetch_my_evolutions.py --record         # enregistre les nouvelles dans used_evolutions
    python fetch_my_evolutions.py --dump-dir dump  # sauvegarde les réponses brutes (debug)
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

import requests

BASE = "https://www.fut.gg"
HEADERS = {
    "User-Agent": "fut27-db-builder/1.0 (usage personnel, contact via github)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
PAGE_SIZE = 100
RECORD_NOTE = "import fut.gg GG Club"


def load_env(path: Path) -> None:
    """Mini-parseur .env (KEY=VALUE), sans dépendance externe. Les variables
    déjà présentes dans l'environnement sont prioritaires."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def pick(d: dict, *keys, default=None):
    """Premier champ présent parmi plusieurs noms possibles (le format de
    l'API n'étant pas documenté, on reste tolérant)."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


class FutGG:
    def __init__(self, dump_dir: Path | None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        # Le front envoie un UUID local comme clé de cache de session.
        self.session.headers["X-Session-Cache-Key"] = str(uuid.uuid4())
        self.dump_dir = dump_dir

    def _dump(self, name: str, payload) -> None:
        if self.dump_dir:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
            (self.dump_dir / f"{name}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def request(self, method: str, path: str, dump_as: str | None = None, **kwargs):
        resp = self.session.request(method, f"{BASE}{path}", timeout=30, **kwargs)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text[:500]}
        if dump_as:
            self._dump(dump_as, payload)
        if not resp.ok:
            raise RuntimeError(f"{method} {path} -> HTTP {resp.status_code}: {json.dumps(payload)[:300]}")
        return payload

    def sign_in(self, identifier: str, password: str) -> None:
        resp = self.session.post(
            f"{BASE}/api/supabase/sign-in/",
            json={"identifier": identifier, "password": password},
            timeout=30,
        )
        payload = resp.json() if resp.content else {}
        token = payload.get("accessToken")
        if not resp.ok or payload.get("error") or not token:
            raise RuntimeError(f"Connexion fut.gg refusée : {payload.get('error') or resp.status_code}")
        self.session.headers["Authorization"] = f"Bearer {token}"

    def sync_club(self, timeout_s: int = 300) -> None:
        result = self.request("POST", "/api/gg-club/sync/", dump_as="sync")
        if pick(result.get("data") or {}, "status") == "queue_full":
            wait = pick(result["data"], "estimatedWaitSeconds", default=0)
            raise RuntimeError(f"File de synchro fut.gg pleine, réessaie dans ~{max(1, round(wait / 60))} min.")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(5)
            status = (self.request("GET", "/api/gg-club/sync-status/").get("data") or {})
            if status.get("isSyncError"):
                raise RuntimeError(f"Erreur de synchro fut.gg : {status}")
            if str(status.get("syncStatus", "")).lower() != "in_progress":
                return
        raise RuntimeError("Synchro toujours en cours après le délai, relance plus tard sans --sync.")

    def club_players(self, game: str) -> list[dict]:
        players, page = [], 1
        while True:
            payload = self.request(
                "GET", "/api/gg-club/players/",
                params={"game": game, "page": page, "count": PAGE_SIZE},
                dump_as=f"players_p{page}",
            )
            batch = payload.get("data") or []
            players.extend(batch)
            if len(batch) < PAGE_SIZE:
                return players
            page += 1
            time.sleep(0.5)


def evolved_entries(player: dict) -> list[tuple[int, str]]:
    """(evolution_id, statut) pour chaque évolution appliquée ou en cours."""
    entries = [(int(e), "terminée") for e in (player.get("evolutionPath") or []) if e is not None]
    active = player.get("activeEvolution")
    if active and active.get("evolutionId") is not None:
        active_id = int(active["evolutionId"])
        if active_id not in {e for e, _ in entries}:
            entries.append((active_id, f"en cours niv. {active.get('level')}/{active.get('maxLevel')}"))
    return entries


def player_identity(player: dict) -> tuple[int | None, str]:
    """ea_id de la carte possédée (= players.ea_id, pas basePlayerEaId qui
    désigne la carte gold de base du joueur) + nom lisible."""
    pdef = player.get("playerDef") or {}
    ea_id = pick(player, "eaId") or pick(pdef, "eaId")
    first, last = pick(pdef, "firstName", default=""), pick(pdef, "lastName", default="")
    name = pick(pdef, "commonName", "nickname") or f"{first} {last}".strip() or pick(player, "name", default="?")
    return (int(ea_id) if ea_id is not None else None), name


def fetch_players(args) -> list[dict] | None:
    """Connexion + lecture du club sur fut.gg (None si --login-only)."""
    load_env(Path(args.env))
    identifier, password = os.environ.get("FUTGG_IDENTIFIER"), os.environ.get("FUTGG_PASSWORD")
    if not identifier or not password:
        sys.exit(f"FUTGG_IDENTIFIER / FUTGG_PASSWORD manquants (copie .env.example en {args.env}).")

    api = FutGG(Path(args.dump_dir) if args.dump_dir else None)
    try:
        api.sign_in(identifier, password)
        print("Connecté à fut.gg.")
        if args.login_only:
            return None
        state = api.request("GET", "/api/gg-club/state/", dump_as="state").get("data") or {}
        if state.get("isEaRelinkRequired"):
            sys.exit("Compte EA non lié (ou à relier) : fais-le sur https://www.fut.gg/gg-club/ puis relance.")
        if args.sync:
            print("Synchro du club en cours...")
            api.sync_club()
        sync = api.request("GET", "/api/gg-club/sync-status/", dump_as="sync_status").get("data") or {}
        print(f"Dernière synchro : {pick(sync, 'lastSyncedAt', 'lastSyncAt', 'syncedAt', default='?')}")
        return api.club_players(args.game)
    except RuntimeError as exc:
        sys.exit(str(exc))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--game", default="27")
    parser.add_argument("--sync", action="store_true", help="relancer une synchro du club avant la lecture")
    parser.add_argument("--record", action="store_true", help="enregistrer les nouvelles évolutions dans used_evolutions")
    parser.add_argument("--dump-dir", default=None, help="dossier où sauvegarder les réponses JSON brutes")
    parser.add_argument("--login-only", action="store_true", help="tester uniquement la connexion puis s'arrêter")
    parser.add_argument("--from-dump", default=None,
                        help="relire les players_p*.json d'un --dump-dir précédent au lieu d'appeler fut.gg")
    args = parser.parse_args()

    if args.from_dump:
        players = [
            p for f in sorted(Path(args.from_dump).glob("players_p*.json"))
            for p in (json.loads(f.read_text(encoding="utf-8")).get("data") or [])
        ]
        if not players:
            sys.exit(f"Aucun players_p*.json exploitable dans {args.from_dump}.")
    else:
        players = fetch_players(args)
        if players is None:
            return

    conn = sqlite3.connect(args.db)
    evo_names = dict(conn.execute("SELECT id, name FROM evolutions"))
    # Compteur (évolution, joueur) -> nb d'enregistrements : une évolution
    # répétable peut légitimement apparaître plusieurs fois sur le même joueur.
    already = Counter(conn.execute("SELECT evolution_id, player_ea_id FROM used_evolutions"))

    print(f"{len(players)} joueurs dans le club.\n")
    new_rows, unknown = [], set()
    for player in players:
        entries = evolved_entries(player)
        if not entries:
            continue
        ea_id, name = player_identity(player)
        print(f"{name} (ea_id={ea_id})")
        for evo_id, status in entries:
            known = evo_id in evo_names
            is_new = already[(evo_id, ea_id)] == 0
            if not is_new:
                already[(evo_id, ea_id)] -= 1
            flag = "" if is_new else "  [déjà enregistrée]"
            print(f"   - [{evo_id}] {evo_names.get(evo_id, '??? inconnue en base')} ({status}){flag}")
            if not known:
                unknown.add(evo_id)
            elif is_new:
                new_rows.append((evo_id, ea_id, name, f"{RECORD_NOTE} ({status})"))

    print(f"\n{len(new_rows)} nouvelle(s) évolution(s) à enregistrer.")
    if unknown:
        print(f"Ids absents de la table evolutions (expirées avant ton 1er scrape ?) : {sorted(unknown)}")
    if args.record and new_rows:
        conn.executemany(
            "INSERT INTO used_evolutions (evolution_id, player_ea_id, player_name, notes) VALUES (?, ?, ?, ?)",
            new_rows,
        )
        conn.commit()
        print("Enregistrées dans used_evolutions.")
    elif new_rows:
        print("(lecture seule — relance avec --record pour les enregistrer)")
    conn.close()


if __name__ == "__main__":
    main()
