"""
Simulation rapide en ligne de commande : "si je mets CE joueur dans CETTE
évolution, qu'est-ce que ça donne ?" - sans repasser par Excel.

Usage:
    python simulate_evolution.py --db fut27.db --evolution 2507 --player "Simon Sohm"
    python simulate_evolution.py --db fut27.db --evolution 2507 --ea-id 12345
"""
import argparse
import json
import sqlite3

from evolution_report import (
    MAIN_STAT_FIELDS,
    apply_upgrades,
    check_eligibility,
    load_evolutions,
    load_players,
)


def find_matches(players: list[dict], name: str | None, ea_id: int | None) -> list[dict]:
    if ea_id is not None:
        return [p for p in players if p.get("ea_id") == ea_id]
    needle = name.strip().lower()
    return [p for p in players if needle in (p["common_name"] or "").lower()]


def print_player_choice(players: list[dict]) -> None:
    print(f"{len(players)} correspondances - precise davantage (ou utilise --ea-id) :")
    for p in players[:20]:
        print(f"  ea_id={p.get('ea_id')}  {p['common_name']} ({p['position']}, {p['overall']} OVR, {p['club']})")
    if len(players) > 20:
        print(f"  ... et {len(players) - 20} de plus")


def print_simulation(player: dict, evo: dict) -> None:
    req = json.loads(evo["requirements_json"] or "{}")
    upgrades = json.loads(evo["upgrades_json"] or "[]")

    print(f"\n=== {player['common_name']} ({player['position']}, {player['overall']} OVR) ===")
    print(f"--- Evolution : {evo['name']} ---")
    print(f"Conditions : {evo['requirements_text'] or 'aucune'}")
    if evo.get("remaining_uses") is not None and evo["remaining_uses"] <= 0:
        limit = evo.get("repeatability_count") or 1
        print(f"ATTENTION : deja epuisee ({evo['used_count']}/{limit} usages enregistres) - simulation indicative")

    reasons = check_eligibility(player, req)
    if reasons:
        print("\nNON ELIGIBLE :")
        for r in reasons:
            print(f"  - {r}")
        print("\n(simulation ci-dessous a titre indicatif quand meme)")
    else:
        print("\nELIGIBLE")

    granted_playstyles = json.loads(evo.get("granted_playstyles") or "[]")
    after_main, after_detail = apply_upgrades(player, upgrades, granted_playstyles)
    before_detail = {lbl: val for lbl, val in (player["detail_pairs"] or [])}

    print(f"\nNote : {player['overall']} -> {after_main['overall']} (+{after_main['overall'] - player['overall']})")
    if player.get("weak_foot") != after_main.get("weak_foot"):
        print(f"Pied faible : {player['weak_foot']} -> {after_main['weak_foot']}")
    if player.get("skill_moves") != after_main.get("skill_moves"):
        print(f"Skill moves : {player['skill_moves']} -> {after_main['skill_moves']}")
    new_ps = [ps for ps in (after_main.get("ps_normal") or []) if ps not in (player.get("ps_normal") or [])]
    if new_ps:
        print(f"PlayStyle(s) gagne(s) : {', '.join(new_ps)}")

    print("\nStats principales :")
    for s in MAIN_STAT_FIELDS:
        before, after = player[s], after_main[s]
        marker = f" (+{after - before})" if after != before else ""
        print(f"  {s.capitalize():<12} {before:>3} -> {after:>3}{marker}")

    if before_detail:
        print("\nSous-stats detaillees :")
        for label, before in before_detail.items():
            after = after_detail.get(label, before)
            if str(after) != str(before):
                try:
                    delta = int(after) - int(before)
                    print(f"  {label:<18} {before:>3} -> {after:>3} (+{delta})")
                except (TypeError, ValueError):
                    print(f"  {label:<18} {before} -> {after}")
    else:
        print("\n(pas de sous-stats detaillees pour cette carte - lance scrape_player_details.py)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--evolution", type=int, required=True)
    parser.add_argument("--player", default=None, help="nom (ou partie du nom) du joueur")
    parser.add_argument("--ea-id", type=int, default=None)
    args = parser.parse_args()

    if not args.player and args.ea_id is None:
        print("Precise --player \"Nom\" ou --ea-id <id>")
        return

    conn = sqlite3.connect(args.db)
    evolutions = load_evolutions(conn, include_inactive=True)
    evo = next((e for e in evolutions if e["id"] == args.evolution), None)
    if evo is None:
        print(f"Evolution id={args.evolution} introuvable (utilise evolution_report.py --list).")
        return

    # load_players ne renvoie pas ea_id (pas necessaire pour les rapports) ;
    # on l'ajoute ici a la volee pour permettre la recherche par --ea-id.
    players = load_players(conn, position=None)
    ea_ids = dict(conn.execute("SELECT id, ea_id FROM players").fetchall())
    for p in players:
        p["ea_id"] = ea_ids.get(p["id"])

    matches = find_matches(players, args.player, args.ea_id)
    if not matches:
        print("Aucun joueur trouve.")
        return
    if len(matches) > 1:
        print_player_choice(matches)
        return

    print_simulation(matches[0], evo)


if __name__ == "__main__":
    main()
