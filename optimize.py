"""
Optimise le choix "quel joueur faire évoluer avec quelle évolution ?"

Entrées :
  - fut27.db          : base construite par scrape_players.py + scrape_evolutions.py
  - my_club.csv       : les cartes que tu possèdes réellement (colonnes: ea_id ou common_name)

Sortie :
  - Pour chaque évolution active, le(s) meilleur(s) joueur(s) de TON club
    qui y sont éligibles, classés par overall final projeté (ou par un score
    pondéré si tu passes --weights).

Usage:
    python optimize.py --club my_club.csv
    python optimize.py --club my_club.csv --weights "shooting=2,pace=1.5,passing=1"
    python optimize.py --club my_club.csv --evolution 2508
"""
import argparse
import csv
import json
import sqlite3
import sys

STATS = ["pace", "shooting", "passing", "dribbling", "defending", "physicality"]
STAT_ALIASES = {
    "OVR": "overall",
    "PAC": "pace", "Sprint Speed": "pace", "Acceleration": "pace",
    "SHO": "shooting", "Finishing": "shooting", "Shot Power": "shooting",
    "Long Shots": "shooting", "Penalties": "shooting", "Volleys": "shooting",
    "PAS": "passing", "Vision": "passing", "Short Pass": "passing", "Long Pass": "passing",
    "Crossing": "passing", "Curve": "passing", "Fk Accuracy": "passing",
    "DRI": "dribbling", "Ball Control": "dribbling", "Agility": "dribbling",
    "Balance": "dribbling", "Composure": "dribbling", "Reactions": "dribbling",
    "DEF": "defending", "Standing Tackle": "defending", "Sliding Tackle": "defending",
    "Interceptions": "defending", "Defensive Awareness": "defending",
    "PHY": "physicality", "Strength": "physicality", "Stamina": "physicality",
    "Aggression": "physicality", "Jumping": "physicality", "Heading Acc.": "physicality",
    "WF": "weak_foot", "SM": "skill_moves",
}


def load_club(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_player(conn: sqlite3.Connection, row: dict) -> dict | None:
    if row.get("ea_id"):
        cur = conn.execute("SELECT * FROM players WHERE ea_id = ?", (int(row["ea_id"]),))
    else:
        name = row.get("common_name", "").strip()
        cur = conn.execute(
            "SELECT * FROM players WHERE common_name LIKE ? ORDER BY overall DESC LIMIT 1",
            (f"%{name}%",),
        )
    cols = [d[0] for d in cur.description]
    r = cur.fetchone()
    return dict(zip(cols, r)) if r else None


def player_matches_requirements(player: dict, req: dict) -> bool:
    if "overall_max" in req and player["overall"] > req["overall_max"]:
        return False
    if "position_in" in req:
        if player["position"] not in req["position_in"]:
            return False
    if "position_excluded" in req and player["position"] in req["position_excluded"]:
        return False
    if "pace_max" in req and (player["pace"] or 0) > req["pace_max"]:
        return False
    if "max_playstyles" in req:
        pass  # nécessiterait le detail des playstyles du joueur, non bloquant ici
    return True


def apply_upgrades(player: dict, upgrades: list[dict]) -> dict:
    projected = dict(player)
    for u in upgrades:
        field = STAT_ALIASES.get(u["stat"])
        if field and field in projected and projected[field] is not None and field != "overall":
            projected[field] = projected[field] + u["delta"]
    for u in upgrades:
        if STAT_ALIASES.get(u["stat"]) == "overall":
            projected["overall"] = player["overall"] + u["delta"]
    return projected


def score(player: dict, weights: dict | None) -> float:
    if not weights:
        return player["overall"]
    return sum(weights.get(stat, 0) * (player.get(stat) or 0) for stat in STATS)


def parse_weights(spec: str | None) -> dict | None:
    if not spec:
        return None
    weights = {}
    for part in spec.split(","):
        k, v = part.split("=")
        weights[k.strip()] = float(v)
    return weights


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--club", required=True, help="CSV avec colonnes ea_id ou common_name")
    parser.add_argument("--weights", default=None, help='ex: "shooting=2,pace=1.5"')
    parser.add_argument("--evolution", type=int, default=None, help="ne tester qu'une evolution (id)")
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    weights = parse_weights(args.weights)
    conn = sqlite3.connect(args.db)

    club_rows = load_club(args.club)
    club_players = []
    for row in club_rows:
        p = find_player(conn, row)
        if p is None:
            print(f"Introuvable dans la base: {row}", file=sys.stderr)
            continue
        club_players.append(p)
    print(f"{len(club_players)} joueurs de ton club charges depuis {args.club}\n")

    evo_query = "SELECT * FROM evolutions"
    evo_params: tuple = ()
    if args.evolution:
        evo_query += " WHERE id = ?"
        evo_params = (args.evolution,)
    cur = conn.execute(evo_query, evo_params)
    evo_cols = [d[0] for d in cur.description]
    evolutions = [dict(zip(evo_cols, r)) for r in cur.fetchall()]

    for evo in evolutions:
        req = json.loads(evo["requirements_json"] or "{}")
        upgrades = json.loads(evo["upgrades_json"] or "[]")

        eligible = [p for p in club_players if player_matches_requirements(p, req)]
        if not eligible:
            continue

        ranked = []
        for p in eligible:
            projected = apply_upgrades(p, upgrades)
            ranked.append((score(projected, weights), p, projected))
        ranked.sort(key=lambda t: t[0], reverse=True)

        print(f"=== {evo['name']} (id={evo['id']}) ===")
        print(f"    Conditions: {evo['requirements_text'] or 'aucune'}")
        for s, before, after in ranked[: args.top]:
            gain = after["overall"] - before["overall"]
            print(
                f"    -> {before['common_name']} ({before['position']}, "
                f"{before['overall']} OVR) => {after['overall']} OVR (+{gain}), score={s:.1f}"
            )
        print()

    conn.close()


if __name__ == "__main__":
    main()
