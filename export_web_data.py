"""
Exporte fut27.db vers un JSON compact utilisé par simulateur.html (outil
interactif : choisir un joueur + une évolution, voir l'éligibilité et les
stats avant/après en un coup d'œil).

Usage:
    python export_web_data.py --db fut27.db --out webapp_data.json
"""
import argparse
import json
import sqlite3

from evolution_report import load_evolutions, parse_alt_positions

MAIN_STAT_FIELDS = ["pace", "shooting", "passing", "dribbling", "defending", "physicality"]
MAIN_LABELS = {"Pace", "Shooting", "Passing", "Dribbling", "Defending", "Physical"}


def export_players(conn: sqlite3.Connection) -> list[dict]:
    query = """
        SELECT p.id, p.ea_id, p.common_name, p.overall, p.position, p.alternative_positions,
               p.club, p.league, p.nation, p.rarity_name, p.quality,
               p.pace, p.shooting, p.passing, p.dribbling, p.defending, p.physicality,
               p.weak_foot, p.skill_moves, p.playstyles_plus, p.playstyles_normal,
               p.foot, p.height, p.age,
               pa.detail_stats_json
        FROM players p
        LEFT JOIN player_attributes pa ON pa.player_id = p.id
    """
    out = []
    for row in conn.execute(query):
        (
            pid, ea_id, name, overall, pos, alt_raw, club, league, nation, rarity, quality,
            pace, shooting, passing, dribbling, defending, physicality,
            wf, sm, ps_plus_raw, ps_normal_raw, foot, height, age, detail_json,
        ) = row
        alt = parse_alt_positions(alt_raw)
        detail = {}
        if detail_json:
            # Une categorie principale (ex: "Dribbling") et une de ses propres
            # sous-stats peuvent porter EXACTEMENT le meme nom ("Dribbling"
            # est a la fois la note globale ET l'une de ses 6 sous-stats). Il
            # ne faut donc ignorer que la PREMIERE occurrence (la note
            # globale, deja stockee ailleurs) et garder la seconde (la vraie
            # sous-stat), sinon elle disparait completement de l'affichage.
            seen_main: set[str] = set()
            for label, val in json.loads(detail_json):
                if label in MAIN_LABELS and label not in seen_main:
                    seen_main.add(label)
                    continue
                try:
                    detail[label] = int(val)
                except (TypeError, ValueError):
                    pass
        out.append(
            {
                "id": pid,
                "eaId": ea_id,
                "name": name,
                "ovr": overall,
                "pos": pos,
                "alt": alt,
                "club": club,
                "league": league,
                "nation": nation,
                "rarity": rarity,
                "quality": quality,
                "foot": foot,
                "height": height,
                "age": age,
                "pace": pace,
                "sho": shooting,
                "pas": passing,
                "dri": dribbling,
                "def": defending,
                "phy": physicality,
                "wf": wf,
                "sm": sm,
                "psPlus": json.loads(ps_plus_raw or "[]"),
                "psNormal": json.loads(ps_normal_raw or "[]"),
                "detail": detail,
            }
        )
    return out


def export_evolutions(conn: sqlite3.Connection) -> list[dict]:
    out = []
    # include_inactive : une evolution deja realisee peut avoir expire depuis ;
    # le simulateur a quand meme besoin de ses gains pour rejouer l'historique
    # d'un joueur (flag "active" pour ne pas la proposer dans la liste).
    for e in load_evolutions(conn, include_inactive=True):
        out.append(
            {
                "id": e["id"],
                "active": bool(e.get("active")),
                "name": e["name"],
                "coinCost": e.get("coin_cost"),
                "pointCost": e.get("point_cost"),
                "req": json.loads(e["requirements_json"] or "{}"),
                "upgrades": json.loads(e["upgrades_json"] or "[]"),
                "grantedPlaystyles": json.loads(e.get("granted_playstyles") or "[]"),
                "repeatabilityCount": e.get("repeatability_count") or 1,
                "usedCount": e["used_count"],
                "remainingUses": e["remaining_uses"],
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--out", default="webapp_data.json")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    data = {
        "evolutions": export_evolutions(conn),
        "players": export_players(conn),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(data['players'])} joueurs, {len(data['evolutions'])} evolutions -> {args.out}")


if __name__ == "__main__":
    main()
