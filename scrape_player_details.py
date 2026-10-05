"""
Récupère le détail complet des statistiques (toutes les sous-stats, comme sur
Futbin) pour chaque carte déjà présente dans la table "players" de fut27.db,
en visitant sa page individuelle sur fut.gg.

Contrairement à scrape_players.py, cette info n'existe QUE sur la page de
chaque carte (rendue côté serveur) : il faut donc une requête HTTP par carte,
comme sur Futbin - mais ici c'est automatisé et reprenable (les cartes déjà
traitées sont sautées d'un lancement a l'autre).

Usage:
    python scrape_player_details.py --db fut27.db [--delay 0.3] [--limit 500]
    python scrape_player_details.py --db fut27.db --min-overall 40 --max-overall 85
"""
import argparse
import json
import sqlite3
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.fut.gg"
HEADERS = {
    "User-Agent": "fut27-db-builder/1.0 (usage personnel, contact via github)",
    "Accept": "text/html",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_attributes (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    detail_stats_json TEXT,   -- liste JSON [[label, valeur], ...] dans l'ordre d'affichage
    scraped_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_attributes(soup: BeautifulSoup) -> list[list[str]]:
    overview = soup.find(id="overview")
    if overview is None:
        return []

    content = None
    for div in overview.find_all("div"):
        classes = div.get("class") or []
        if "p-4" in classes and "gap-4" in classes and "flex-col" in classes:
            content = div
            break
    if content is None:
        return []

    grid = content.find("div", class_=lambda c: c and "grid-cols-2" in c)
    if grid is None:
        return []

    pairs: list[list[str]] = []
    for cat_block in grid.find_all("div", recursive=False):
        classes = cat_block.get("class") or []
        if "h-full" not in classes:
            continue

        label_tag = cat_block.find("span", class_=lambda c: c and "uppercase" in c)
        label = label_tag.get_text(strip=True) if label_tag else None

        value_candidates = [
            d.get_text(strip=True)
            for d in cat_block.find_all("div")
            if d.get("style") and "color" in d.get("style")
            and d.get_text(strip=True).replace(".", "", 1).isdigit()
        ]
        value = value_candidates[-1] if value_candidates else None
        if label and value:
            pairs.append([label, value])

        for sub in cat_block.find_all("div", class_=lambda c: c and "gap-[2px]" in c):
            lbl_tag = sub.find("div", class_=lambda c: c and "overflow-hidden" in c)
            lbl = lbl_tag.get_text(strip=True) if lbl_tag else None
            val_tag = sub.find(
                "span", class_=lambda c: c and "font-bold" in c and "text-white" in c
            )
            val = val_tag.get_text(strip=True) if val_tag else None
            if lbl and val:
                pairs.append([lbl, val])

    # Le rendu fut.gg duplique parfois la valeur d'une categorie principale
    # (Diving/Handling/... sur les gardiens) comme si c'etait aussi une
    # sous-stat identique juste en dessous. On retire ces doublons stricts
    # adjacents (meme libelle ET meme valeur consecutifs).
    deduped: list[list[str]] = []
    for pair in pairs:
        if deduped and deduped[-1] == pair:
            continue
        deduped.append(pair)
    return deduped


def fetch_players_to_process(
    conn: sqlite3.Connection, min_overall: int, max_overall: int, limit: int
) -> list[tuple[int, str]]:
    query = """
        SELECT p.id, p.url FROM players p
        LEFT JOIN player_attributes pa ON pa.player_id = p.id
        WHERE pa.player_id IS NULL
          AND p.overall BETWEEN ? AND ?
          AND p.url IS NOT NULL
        ORDER BY p.overall DESC
    """
    params: list = [min_overall, max_overall]
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    return conn.execute(query, params).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--limit", type=int, default=0, help="0 = pas de limite")
    parser.add_argument("--min-overall", type=int, default=1)
    parser.add_argument("--max-overall", type=int, default=99)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)

    todo = fetch_players_to_process(conn, args.min_overall, args.max_overall, args.limit)
    print(f"{len(todo)} cartes a traiter (deja traitees ignorees)")

    session = requests.Session()
    done = 0
    errors = 0
    for player_id, url in todo:
        try:
            soup = get_soup(BASE + url, session)
            pairs = parse_attributes(soup)
            conn.execute(
                "INSERT OR REPLACE INTO player_attributes (player_id, detail_stats_json) VALUES (?, ?)",
                (player_id, json.dumps(pairs, ensure_ascii=False)),
            )
            conn.commit()
            done += 1
        except Exception as exc:  # noqa: BLE001 - on continue meme en cas d'echec ponctuel
            errors += 1
            print(f"\nEchec sur player_id={player_id} ({url}): {exc}", file=sys.stderr)

        print(f"\r{done + errors}/{len(todo)} traitees ({errors} echecs)", end="", flush=True)
        time.sleep(args.delay)

    print(f"\nTermine. {done} cartes detaillees, {errors} echecs.")
    conn.close()


if __name__ == "__main__":
    main()
