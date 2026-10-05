"""
Compare le rejeu des evolutions (apply_upgrades) a la carte REELLE du club.

Le dump GG Club (club_dump/players_p*.json, cree par fetch_my_evolutions.py
--dump-dir) contient pour chaque joueur evolue la carte actuelle (playerDef :
note, stats principales, sous-stats). On part de la carte de base de fut27.db,
on rejoue evolutionPath dans l'ordre et on affiche chaque ecart.

Usage:
    python validate_replay.py [--db fut27.db] [--dump club_dump] [--all]
"""
import argparse
import glob
import json
import sqlite3

from evo_levels import club_evolution_entries
from evolution_report import apply_upgrades, evolution_gains, parse_alt_positions

ATTR_LABELS = {
    "attributeAcceleration": "Acceleration", "attributeSprintSpeed": "Sprint Speed",
    "attributeAgility": "Agility", "attributeBalance": "Balance",
    "attributeJumping": "Jumping", "attributeStamina": "Stamina",
    "attributeStrength": "Strength", "attributeReactions": "Reactions",
    "attributeAggression": "Aggression", "attributeComposure": "Composure",
    "attributeInterceptions": "Interceptions", "attributePositioning": "Att. Pos.",
    "attributeVision": "Vision", "attributeBallControl": "Ball Control",
    "attributeCrossing": "Crossing", "attributeDribbling": "Dribbling",
    "attributeFinishing": "Finishing", "attributeFkAccuracy": "Fk Acc.",
    "attributeHeadingAccuracy": "Heading Acc.", "attributeLongPassing": "Long Pass",
    "attributeShortPassing": "Short Pass", "attributeDefensiveAwareness": "Def. Aware.",
    "attributeShotPower": "Shot Power", "attributeLongShots": "Long Shots",
    "attributeStandingTackle": "Stand Tackle", "attributeSlidingTackle": "Slide Tackle",
    "attributeVolleys": "Volleys", "attributeCurve": "Curve", "attributePenalties": "Penalties",
}
FACE_FIELDS = {
    "facePace": "pace", "faceShooting": "shooting", "facePassing": "passing",
    "faceDribbling": "dribbling", "faceDefending": "defending", "facePhysicality": "physicality",
}


def load_base(conn: sqlite3.Connection, ea_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT p.common_name, p.overall, p.position, p.alternative_positions,
               p.pace, p.shooting, p.passing, p.dribbling, p.defending, p.physicality,
               p.weak_foot, p.skill_moves, p.playstyles_plus, p.playstyles_normal,
               pa.detail_stats_json
        FROM players p LEFT JOIN player_attributes pa ON pa.player_id = p.id
        WHERE p.ea_id = ? ORDER BY p.is_evolution_item, p.id LIMIT 1
        """,
        (ea_id,),
    ).fetchone()
    if not row:
        return None
    (name, ovr, pos, alt, pac, sho, pas, dri, de, phy, wf, sm, psp, psn, detail) = row
    return {
        "common_name": name, "overall": ovr, "position": pos,
        "alt_positions": parse_alt_positions(alt),
        "pace": pac, "shooting": sho, "passing": pas, "dribbling": dri,
        "defending": de, "physicality": phy, "weak_foot": wf, "skill_moves": sm,
        "ps_plus": json.loads(psp or "[]"), "ps_normal": json.loads(psn or "[]"),
        "detail_pairs": json.loads(detail) if detail else None,
    }


def replay(conn: sqlite3.Connection, base: dict, entries: list[dict]) -> tuple[dict, dict, list[str]]:
    current, detail, notes = base, {}, []
    conn.row_factory = sqlite3.Row
    for entry in entries:
        evo_id = entry["evolution_id"]
        row = conn.execute("SELECT * FROM evolutions WHERE id = ?", (evo_id,)).fetchone()
        if not row:
            notes.append(f"evolution {evo_id} absente de la base")
            continue
        evo = dict(row)
        upgrades, playstyles = evolution_gains(evo, entry["levels_done"], entry["choices"])
        label = f"{evo['name']} ({evo_id})"
        if entry["in_progress"]:
            notes.append(f"{label} : en cours, {entry['levels_done']} palier(s) applique(s)")
        elif entry["choices"]:
            notes.append(f"{label} : choix {entry['choices']}")
        if not evo.get("levels_json"):
            notes.append(f"{label} : paliers inconnus, gains a plat")
        current, detail = apply_upgrades(current, upgrades, playstyles)
        current = dict(current)
        current["detail_pairs"] = list(detail.items())
    return current, detail, notes


def compare(after: dict, detail: dict, real: dict) -> list[str]:
    diffs = []
    if after["overall"] != real["overall"]:
        diffs.append(f"overall: simule {after['overall']} / reel {real['overall']}")
    for key, field in FACE_FIELDS.items():
        if real.get(key) is not None and after.get(field) != real[key]:
            diffs.append(f"{field}: simule {after.get(field)} / reel {real[key]}")
    if after.get("weak_foot") != real.get("weakFoot"):
        diffs.append(f"weak_foot: simule {after.get('weak_foot')} / reel {real.get('weakFoot')}")
    if after.get("skill_moves") != real.get("skillMoves"):
        diffs.append(f"skill_moves: simule {after.get('skill_moves')} / reel {real.get('skillMoves')}")
    for key, label in ATTR_LABELS.items():
        sim = detail.get(label)
        if sim is not None and real.get(key) is not None and int(sim) != real[key]:
            diffs.append(f"{label}: simule {sim} / reel {real[key]}")
    return diffs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--dump", default="club_dump")
    parser.add_argument("--all", action="store_true", help="afficher aussi les joueurs sans ecart")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    total = bad = 0
    for path_file in sorted(glob.glob(f"{args.dump}/players_p*.json")):
        with open(path_file, encoding="utf-8") as fh:
            rows = json.load(fh).get("data") or []
        for p in rows:
            entries = club_evolution_entries(p)
            path = [e["evolution_id"] for e in entries]
            real = p.get("playerDef") or {}
            if not entries or not real:
                continue
            base = load_base(conn, p["eaId"])
            if base is None:
                print(f"? {p['eaId']} absent de la base")
                continue
            after, detail, notes = replay(conn, base, entries)
            diffs = compare(after, detail, real)
            total += 1
            bad += bool(diffs)
            print(f"\n{'KO' if diffs else 'OK'}  {base['common_name']} (ea_id {p['eaId']})  chemin {path}")
            for n in notes:
                print(f"    note : {n}")
            if diffs or args.all:
                for d in diffs:
                    print(f"    {d}")
    print(f"\n{total - bad}/{total} joueurs identiques a la carte reelle")


if __name__ == "__main__":
    main()
