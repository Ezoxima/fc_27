"""
Enregistre une évolution que tu as réellement réalisée dans le jeu.

La plupart des évolutions FC 27 ne sont utilisables qu'UNE SEULE FOIS par
compte (rarement plus, voir "repeatability_count" dans la table evolutions).
Une fois enregistrée ici, l'évolution disparaît automatiquement des rapports
(evolution_report.py, simulate_evolution.py, simulateur.html) dès que son
quota d'usages est atteint.

Usage:
    python record_evolution.py --evolution 2507 --player "Simon Sohm"
    python record_evolution.py --evolution 2507 --ea-id 12345 --notes "coup de coeur"
    python record_evolution.py --history                 # voir tout l'historique
    python record_evolution.py --undo 4                   # annuler l'enregistrement id=4 (erreur de saisie)
"""
import argparse
import sqlite3

from evolution_report import load_evolutions, load_players
from simulate_evolution import find_matches, print_player_choice


def record(conn: sqlite3.Connection, evolution_id: int, player_ea_id: int, player_name: str, notes: str | None) -> None:
    conn.execute(
        "INSERT INTO used_evolutions (evolution_id, player_ea_id, player_name, notes) VALUES (?, ?, ?, ?)",
        (evolution_id, player_ea_id, player_name, notes),
    )
    conn.commit()


def print_history(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT u.id, e.name, u.player_name, u.player_ea_id, u.date_applied, u.notes
        FROM used_evolutions u
        JOIN evolutions e ON e.id = u.evolution_id
        ORDER BY u.date_applied DESC
        """
    ).fetchall()
    if not rows:
        print("Aucune evolution enregistree pour l'instant.")
        return
    for uid, evo_name, player_name, ea_id, date, notes in rows:
        note_str = f" - {notes}" if notes else ""
        print(f"  [{uid}] {date}  {evo_name}  ->  {player_name} (ea_id={ea_id}){note_str}")


def undo(conn: sqlite3.Connection, record_id: int) -> None:
    cur = conn.execute("DELETE FROM used_evolutions WHERE id = ?", (record_id,))
    conn.commit()
    if cur.rowcount:
        print(f"Enregistrement [{record_id}] supprime.")
    else:
        print(f"Aucun enregistrement avec l'id {record_id}.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--evolution", type=int, default=None)
    parser.add_argument("--player", default=None, help="nom (ou partie du nom) du joueur")
    parser.add_argument("--ea-id", type=int, default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--history", action="store_true", help="afficher tout l'historique")
    parser.add_argument("--undo", type=int, default=None, metavar="ID", help="supprimer un enregistrement par son id")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    if args.history:
        print_history(conn)
        return
    if args.undo is not None:
        undo(conn, args.undo)
        return

    if not args.evolution or (not args.player and args.ea_id is None):
        print("Precise --evolution <id> et --player \"Nom\" (ou --ea-id <id>).")
        print("Utilise --history pour voir ce qui est deja enregistre.")
        return

    # include_inactive=True : on doit pouvoir enregistrer (ou corriger apres coup)
    # une evolution que tu as reellement realisee AVANT qu'elle expire de fut.gg,
    # meme si elle n'apparait plus dans les rapports actuels.
    evolutions = load_evolutions(conn, include_inactive=True)
    evo = next((e for e in evolutions if e["id"] == args.evolution), None)
    if evo is None:
        print(f"Evolution id={args.evolution} introuvable (voir evolution_report.py --list).")
        return

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

    player = matches[0]
    limit = evo.get("repeatability_count") or 1
    if evo["remaining_uses"] <= 0:
        print(
            f"ATTENTION : '{evo['name']}' a deja atteint son quota ({evo['used_count']}/{limit}). "
            "Enregistrement quand meme, a toi de confirmer que c'est voulu (ex: le quota a peut-etre change)."
        )

    record(conn, evo["id"], player.get("ea_id"), player["common_name"], args.notes)
    print(
        f"Enregistre : '{evo['name']}' appliquee a {player['common_name']} "
        f"(ea_id={player.get('ea_id')}). Usages restants : {max(0, evo['remaining_uses'] - 1)}/{limit}."
    )


if __name__ == "__main__":
    main()
