"""
Récupère la base complète des cartes EA SPORTS FC 27 Ultimate Team
depuis l'API publique de fut.gg et la stocke dans une base SQLite locale.

Usage:
    python scrape_players.py [--out fut27.db] [--delay 0.3] [--only-new]

Source : https://www.fut.gg/api/fut/players/v2/27/  (pagination 30/page)
Cette API est utilisée par le site public fut.gg pour afficher ses pages
joueurs. Le script reste raisonnable (délai entre requêtes, User-Agent
identifiable) pour ne pas surcharger le service.
"""
import argparse
import json
import sqlite3
import sys
import time

import requests

from playstyles import resolve_playstyles

API_URL = "https://www.fut.gg/api/fut/players/v2/27/"
HEADERS = {
    "User-Agent": "fut27-db-builder/1.0 (usage personnel, contact via github)",
    "Accept": "application/json",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,        -- id interne fut.gg (unique par version de carte)
    ea_id INTEGER,                 -- id de la carte cote EA (utilise par les evolutions)
    base_player_ea_id INTEGER,     -- id du joueur "de base" (toutes versions confondues)
    common_name TEXT,
    first_name TEXT,
    last_name TEXT,
    overall INTEGER,
    position TEXT,
    alternative_positions TEXT,    -- liste JSON
    rarity_name TEXT,
    quality TEXT,                  -- BRONZE / SILVER / GOLD
    club TEXT,
    league TEXT,
    nation TEXT,
    pace INTEGER,
    shooting INTEGER,
    passing INTEGER,
    dribbling INTEGER,
    defending INTEGER,
    physicality INTEGER,
    weak_foot INTEGER,
    skill_moves INTEGER,
    foot TEXT,
    height INTEGER,
    age INTEGER,
    playstyles_plus TEXT,          -- liste JSON des PlayStyles+ (noms)
    playstyles_normal TEXT,        -- liste JSON des PlayStyles normaux (noms)
    is_evolution_item INTEGER,
    is_icon INTEGER,
    is_hero INTEGER,
    price INTEGER,
    slug TEXT,
    url TEXT,
    raw_json TEXT                  -- objet complet, au cas où on ait besoin d'un champ non mappe
);
CREATE INDEX IF NOT EXISTS idx_players_overall ON players(overall);
CREATE INDEX IF NOT EXISTS idx_players_position ON players(position);
CREATE INDEX IF NOT EXISTS idx_players_ea_id ON players(ea_id);
"""


def fetch_page(page: int, session: requests.Session, extra_params: dict | None = None) -> dict:
    params = {"page": page, **(extra_params or {})}
    resp = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def upsert_player(conn: sqlite3.Connection, p: dict) -> None:
    face = p.get("faceStatsV2") or {}
    ps_plus = resolve_playstyles(p.get("playStylePlusEaIds") or [])
    ps_normal = resolve_playstyles(p.get("playStyleEaIds") or [])
    conn.execute(
        """
        INSERT INTO players (
            id, ea_id, base_player_ea_id, common_name, first_name, last_name,
            overall, position, alternative_positions, rarity_name, quality,
            club, league, nation,
            pace, shooting, passing, dribbling, defending, physicality,
            weak_foot, skill_moves, foot, height, age,
            playstyles_plus, playstyles_normal,
            is_evolution_item, is_icon, is_hero, price, slug, url, raw_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            overall=excluded.overall, position=excluded.position,
            alternative_positions=excluded.alternative_positions,
            rarity_name=excluded.rarity_name, quality=excluded.quality,
            club=excluded.club, league=excluded.league, nation=excluded.nation,
            pace=excluded.pace, shooting=excluded.shooting, passing=excluded.passing,
            dribbling=excluded.dribbling, defending=excluded.defending,
            physicality=excluded.physicality,
            weak_foot=excluded.weak_foot, skill_moves=excluded.skill_moves,
            foot=excluded.foot, height=excluded.height, age=excluded.age,
            is_evolution_item=excluded.is_evolution_item,
            is_icon=excluded.is_icon, is_hero=excluded.is_hero,
            price=excluded.price,
            playstyles_plus=excluded.playstyles_plus,
            playstyles_normal=excluded.playstyles_normal
        """,
        (
            p.get("id"),
            p.get("eaId"),
            p.get("basePlayerEaId"),
            p.get("commonName"),
            p.get("firstName"),
            p.get("lastName"),
            p.get("overall"),
            p.get("position"),
            json.dumps(p.get("alternativePositions")),
            p.get("rarityName"),
            p.get("quality"),
            (p.get("club") or {}).get("name") if p.get("club") else None,
            (p.get("league") or {}).get("name") if p.get("league") else None,
            (p.get("nation") or {}).get("name") if p.get("nation") else None,
            face.get("facePace"),
            face.get("faceShooting"),
            face.get("facePassing"),
            face.get("faceDribbling"),
            face.get("faceDefending"),
            face.get("facePhysicality"),
            p.get("weakFoot"),
            p.get("skillMoves"),
            p.get("foot"),
            p.get("height"),
            p.get("age"),
            json.dumps(ps_plus, ensure_ascii=False),
            json.dumps(ps_normal, ensure_ascii=False),
            int(bool(p.get("isEvolutionPlayerItem"))),
            int(bool(p.get("isIcon"))),
            int(bool(p.get("isHero"))),
            p.get("price"),
            p.get("slug"),
            p.get("url"),
            None,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="fut27.db")
    parser.add_argument("--delay", type=float, default=0.3, help="delai (s) entre requetes")
    parser.add_argument("--max-pages", type=int, default=0, help="0 = toutes les pages")
    parser.add_argument(
        "--only-new", action="store_true",
        help="ne re-scrape que les paliers d'overall dont le total API differe de la base",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.out)
    conn.executescript(SCHEMA)

    session = requests.Session()

    # L'API plafonne le champ "total" (et la pagination) a 10000 resultats sur
    # une requete non filtree (limite classique type Elasticsearch
    # max_result_window). La base FC 27 contient en realite ~20000 cartes en
    # comptant les speciales. On contourne la limite en segmentant la
    # recuperation par tranche de note (overall__gte/overall__lte), chaque
    # tranche restant tres en dessous du plafond.
    seen = 0
    for ovr in range(1, 100):
        band_first = fetch_page(1, session, {"overall__gte": ovr, "overall__lte": ovr})
        band_total = band_first.get("total", 0)
        if band_total == 0:
            continue
        if args.only_new:
            db_count = conn.execute(
                "SELECT COUNT(*) FROM players WHERE overall = ?", (ovr,)
            ).fetchone()[0]
            if db_count == band_total:
                time.sleep(args.delay)
                continue
            print(f"\nOverall {ovr}: API={band_total} DB={db_count} -> re-scrape")
        per_page = len(band_first.get("data", [])) or 30
        band_pages = -(-band_total // per_page)
        if args.max_pages:
            band_pages = min(band_pages, args.max_pages)

        for page in range(1, band_pages + 1):
            data = band_first if page == 1 else fetch_page(
                page, session, {"overall__gte": ovr, "overall__lte": ovr}
            )
            for p in data.get("data", []):
                upsert_player(conn, p)
                seen += 1
            conn.commit()
            print(
                f"\rOverall {ovr} - page {page}/{band_pages} "
                f"({band_total} cartes a ce niveau) - {seen} cartes au total",
                end="",
                flush=True,
            )
            time.sleep(args.delay)

    print(f"\nTermine. {seen} cartes enregistrees dans {args.out}")
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"Erreur HTTP: {e}", file=sys.stderr)
        sys.exit(1)
