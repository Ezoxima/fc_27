"""
Petit serveur HTTP local pour le simulateur d'évolutions (simulateur.html).

Sert les fichiers statiques du dossier courant (dont simulateur.html) et
expose une API minimale pour enregistrer une évolution réellement appliquée
dans le jeu directement depuis la page, sans repasser par la ligne de
commande (record_evolution.py).

Usage:
    python record_server.py                     # http://127.0.0.1:8765
    python record_server.py --port 9000 --db autre.db
"""
import argparse
import json
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from evo_levels import ensure_level_columns
from evolution_report import load_evolutions
from record_evolution import record

DB_PATH = "fut27.db"
PORT = 8765
STATIC_ALLOWED = {"/", "/simulateur.html"}


def usage_payload(evo: dict) -> dict:
    return {
        "id": evo["id"],
        "usedCount": evo["used_count"],
        "remainingUses": evo["remaining_uses"],
        "active": bool(evo.get("active")),
    }


def load_history(conn: sqlite3.Connection) -> list[dict]:
    ensure_level_columns(conn)
    rows = conn.execute(
        """
        SELECT u.id, u.evolution_id, e.name, u.player_name, u.player_ea_id, u.date_applied, u.notes,
               u.level, u.max_level, u.path_choices
        FROM used_evolutions u
        JOIN evolutions e ON e.id = u.evolution_id
        ORDER BY u.date_applied DESC, u.id DESC
        """
    ).fetchall()
    return [
        {
            "id": uid,
            "evolutionId": evo_id,
            "evolutionName": evo_name,
            "playerName": player_name,
            "playerEaId": ea_id,
            "dateApplied": date,
            "notes": notes,
            "level": level,
            "maxLevel": max_level,
            "pathChoices": json.loads(choices) if choices else None,
        }
        for uid, evo_id, evo_name, player_name, ea_id, date, notes, level, max_level, choices in rows
    ]


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass  # silence la sortie standard de SimpleHTTPRequestHandler

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        """Protection DNS rebinding : seul l'hote local est accepte."""
        return self.headers.get("Host", "") in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

    def _origin_ok(self) -> bool:
        """Protection CSRF : un Origin present doit etre l'hote local."""
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

    def do_GET(self) -> None:
        if not self._host_ok():
            self._send_json(403, {"ok": False, "error": "hote refuse"})
            return
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            self._route_api_get()
        elif path in STATIC_ALLOWED:
            if path == "/":
                self.path = "/simulateur.html"
            super().do_GET()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._host_ok() or not self._origin_ok():
            self._send_json(403, {"ok": False, "error": "origine refusee"})
            return
        if self.path == "/api/record":
            self._handle_record()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_DELETE(self) -> None:
        if not self._host_ok() or not self._origin_ok():
            self._send_json(403, {"ok": False, "error": "origine refusee"})
            return
        if self.path.startswith("/api/history/"):
            self._handle_delete_history()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def _route_api_get(self) -> None:
        if self.path == "/api/usage":
            self._handle_usage()
        elif self.path == "/api/history":
            self._handle_history()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def _handle_history(self) -> None:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            history = load_history(conn)
        finally:
            conn.close()
        self._send_json(200, history)

    def _handle_delete_history(self) -> None:
        record_id_str = self.path.removeprefix("/api/history/")
        if not record_id_str.isdigit():
            self._send_json(400, {"ok": False, "error": "id invalide"})
            return
        record_id = int(record_id_str)

        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            cur = conn.execute("DELETE FROM used_evolutions WHERE id = ?", (record_id,))
            conn.commit()
        finally:
            conn.close()

        if cur.rowcount == 0:
            self._send_json(404, {"ok": False, "error": f"enregistrement id={record_id} introuvable"})
            return
        self._send_json(200, {"ok": True})

    def _handle_usage(self) -> None:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            evolutions = load_evolutions(conn, include_inactive=True)
        finally:
            conn.close()
        self._send_json(200, [usage_payload(e) for e in evolutions])

    def _handle_record(self) -> None:
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self._send_json(415, {"ok": False, "error": "Content-Type application/json requis"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if length < 0 or length > 65536:
            self._send_json(400, {"ok": False, "error": "Content-Length invalide"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "JSON invalide"})
            return

        evolution_id = body.get("evolutionId")
        player_name = body.get("playerName")
        player_ea_id = body.get("playerEaId")
        notes = body.get("notes")
        path_choices = body.get("pathChoices")
        if path_choices is not None and not (
            isinstance(path_choices, list) and all(isinstance(c, int) and c > 0 for c in path_choices)
        ):
            self._send_json(400, {"ok": False, "error": "pathChoices invalide"})
            return

        if not evolution_id or not player_name:
            self._send_json(400, {"ok": False, "error": "evolutionId et playerName sont requis"})
            return

        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            evolutions = load_evolutions(conn, include_inactive=True)
            evo = next((e for e in evolutions if e["id"] == evolution_id), None)
            if evo is None:
                self._send_json(404, {"ok": False, "error": f"evolution id={evolution_id} introuvable"})
                return

            record(conn, evolution_id, player_ea_id, player_name, notes, path_choices)

            updated = load_evolutions(conn, include_inactive=True)
            evo = next(e for e in updated if e["id"] == evolution_id)
        except sqlite3.Error as exc:
            self._send_json(500, {"ok": False, "error": f"erreur base: {exc}"})
            return
        finally:
            conn.close()

        self._send_json(200, {
            "ok": True,
            "evolutionId": evo["id"],
            "usedCount": evo["used_count"],
            "remainingUses": evo["remaining_uses"],
        })


def main() -> None:
    global DB_PATH, PORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default="fut27.db")
    args = parser.parse_args()

    DB_PATH = args.db
    PORT = args.port

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Serveur local sur http://127.0.0.1:{args.port}/simulateur.html (base: {DB_PATH})")
    print("Ctrl+C pour arreter.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
