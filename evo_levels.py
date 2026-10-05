"""
Paliers (levels) et options des evolutions fut.gg.

Chaque page /evolutions/<id>-<slug>/ embarque un objet JS serialise (React
Server Components) avec la cle `levels` : une liste de paliers, chacun avec
ses `upgrades` et, pour les evolutions "Pathway", des `upgradeOptions` (on
choisit UNE option par palier concerne). Ce module :

- extrait et normalise cette structure (`parse_levels_from_html`) ;
- choisit les gains a appliquer pour un nombre de paliers termines et des
  choix d'options donnes (`select_upgrades`) - utilise par le rejeu Python ;
  le simulateur (JS) reproduit la meme regle.

Format normalise stocke dans evolutions.levels_json :
    [{"idx": 1, "options": [{"upgrades": [{"stat","delta","result_value"}],
                              "playstyles": ["Tiki Taka"], "role_plus": [3]}]}]
Un palier sans choix a une seule option.
"""
import json
import re
import sqlite3

from playstyles import PLAY_STYLE_NAMES

# cle d'upgrade fut.gg -> libelle utilise par evolution_report.apply_upgrades
UPGRADE_LABELS = {
    "overall": "OVR", "weak_foot": "WF", "skill_moves": "SM",
    "attribute_acceleration": "Acceleration", "attribute_sprint_speed": "Sprint Speed",
    "attribute_agility": "Agility", "attribute_balance": "Balance",
    "attribute_jumping": "Jumping", "attribute_stamina": "Stamina",
    "attribute_strength": "Strength", "attribute_reactions": "Reactions",
    "attribute_aggression": "Aggression", "attribute_composure": "Composure",
    "attribute_interceptions": "Interceptions", "attribute_positioning": "Positioning",
    "attribute_vision": "Vision", "attribute_ball_control": "Ball Control",
    "attribute_crossing": "Crossing", "attribute_dribbling": "Dribbling",
    "attribute_finishing": "Finishing", "attribute_fk_accuracy": "Fk Accuracy",
    "attribute_heading_accuracy": "Heading Accuracy", "attribute_long_passing": "Long Pass",
    "attribute_short_passing": "Short Pass", "attribute_defensive_awareness": "Defensive Awareness",
    "attribute_shot_power": "Shot Power", "attribute_long_shots": "Long Shots",
    "attribute_standing_tackle": "Standing Tackle", "attribute_sliding_tackle": "Sliding Tackle",
    "attribute_volleys": "Volleys", "attribute_curve": "Curve", "attribute_penalties": "Penalties",
    "attribute_gk_diving": "Diving", "attribute_gk_handling": "Handling",
    "attribute_gk_kicking": "Kicking", "attribute_gk_reflexes": "Reflexes",
    "gk_face_positioning": "POS",
}


def _extract_array(html: str, key: str) -> str | None:
    """Sous-chaine de l'objet/tableau serialise qui suit `<key>:$R[n]=`."""
    i = html.find(f"{key}:$R[")
    if i < 0:
        return None
    start = html.index("=", i) + 1
    depth, k, in_str, quote = 0, start, False, ""
    while k < len(html):
        ch = html[k]
        if in_str:
            if ch == "\\":
                k += 2
                continue
            if ch == quote:
                in_str = False
        elif ch in "\"'":
            in_str, quote = True, ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return html[start:k + 1]
        k += 1
    return None


def _to_json(js: str) -> str:
    """Convertit la syntaxe JS serialisee (cles nues, !0/!1, $R[n]=) en JSON."""
    js = re.sub(r"\$R\[\d+\]=", "", js)
    out: list[str] = []
    in_str, quote, k = False, "", 0
    while k < len(js):
        ch = js[k]
        if in_str:
            out.append(ch)
            if ch == "\\":
                out.append(js[k + 1])
                k += 2
                continue
            if ch == quote:
                in_str = False
            k += 1
            continue
        if ch in "\"'":
            in_str, quote = True, ch
            out.append('"' if ch == "'" else ch)
            k += 1
            continue
        if js.startswith("!0", k):
            out.append("true")
            k += 2
            continue
        if js.startswith("!1", k):
            out.append("false")
            k += 2
            continue
        if js.startswith("void 0", k):
            out.append("null")
            k += 6
            continue
        m = re.match(r"([A-Za-z_$][\w$]*):", js[k:]) if out and out[-1] in "{," else None
        if m:
            out.append(json.dumps(m.group(1)) + ":")
            k += m.end()
            continue
        out.append(ch)
        k += 1
    return "".join(out)


def _normalize_option(raw_upgrades: list[dict]) -> dict:
    upgrades, playstyles, role_plus = [], [], []
    for u in raw_upgrades:
        key, value, max_value = u.get("upgrade"), u.get("value"), u.get("maxValue")
        if key == "play_style":
            name = PLAY_STYLE_NAMES.get(value)
            if name:
                playstyles.append(name)
        elif key == "role_plus":
            role_plus.append(value)
        elif key in UPGRADE_LABELS:
            upgrades.append({"stat": UPGRADE_LABELS[key], "delta": value, "result_value": max_value})
    return {"upgrades": upgrades, "playstyles": playstyles, "role_plus": role_plus}


def parse_levels_from_html(html: str) -> list[dict] | None:
    """Paliers normalises d'une page evolution, ou None si introuvables."""
    raw = _extract_array(html, "levels")
    if not raw:
        return None
    try:
        levels = json.loads(_to_json(raw))
    except ValueError:
        return None
    out = []
    for lv in levels:
        options = lv.get("upgradeOptions") or []
        if options:
            normalized = [_normalize_option(o.get("upgrades") or []) for o in options]
        else:
            normalized = [_normalize_option(lv.get("upgrades") or [])]
        out.append({"idx": lv.get("idx"), "options": normalized})
    return out


def select_upgrades(
    levels: list[dict], levels_done: int | None = None, choices: list[int] | None = None
) -> tuple[list[dict], list[str]]:
    """Gains (dans l'ordre des paliers) et PlayStyles d'une evolution.

    levels_done : nombre de paliers termines (None = tous).
    choices     : option choisie (1-based) pour chaque palier, par index de
                  palier (comme `evolutionPathChoices` de GG Club) ; absent ou
                  invalide = option 1.
    """
    upgrades: list[dict] = []
    playstyles: list[str] = []
    for i, lv in enumerate(levels):
        if levels_done is not None and i >= levels_done:
            break
        options = lv["options"]
        pick = 1
        if choices and i < len(choices) and isinstance(choices[i], int):
            pick = choices[i]
        option = options[pick - 1] if 1 <= pick <= len(options) else options[0]
        upgrades.extend(option["upgrades"])
        for ps in option["playstyles"]:
            if ps not in playstyles:
                playstyles.append(ps)
    return upgrades, playstyles


# colonnes ajoutees apres coup (bases creees avant les paliers)
LEVEL_COLUMNS = {
    "evolutions": {"levels_json": "TEXT"},
    "used_evolutions": {
        "level": "INTEGER",         # paliers termines (NULL = evolution terminee)
        "max_level": "INTEGER",
        "path_choices": "TEXT",     # JSON : option choisie par palier, ex. [1, 1, 3]
    },
}


def ensure_level_columns(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes de paliers aux tables existantes (idempotent)."""
    for table, columns in LEVEL_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table pas encore creee
        for name, sql_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
    conn.commit()


def club_evolution_entries(player: dict) -> list[dict]:
    """Evolutions d'une carte du club (reponse GG Club), dans l'ordre d'application.

    Chaque entree : {"evolution_id", "levels_done" (None = terminee), "max_level",
    "choices" (option par palier), "in_progress"}. `evolutionPath`,
    `evolutionPathChoices` et `evolutions` sont alignes par position ;
    l'evolution en cours (`activeEvolution`) n'est pas dans `evolutionPath`.
    """
    path = [int(e) for e in (player.get("evolutionPath") or []) if e is not None]
    path_choices = player.get("evolutionPathChoices") or []
    instances = player.get("evolutions") or []
    entries = []
    for i, evo_id in enumerate(path):
        inst = instances[i] if i < len(instances) else {}
        done = len(inst.get("completedLevels") or [])
        complete = inst.get("completed", True)
        entries.append({
            "evolution_id": evo_id,
            "levels_done": None if complete else done,
            "max_level": None,
            "choices": list(path_choices[i]) if i < len(path_choices) else [],
            "in_progress": not complete,
        })
    active = player.get("activeEvolution")
    if active and active.get("evolutionId") is not None:
        active_id = int(active["evolutionId"])
        inst = instances[len(path)] if len(path) < len(instances) else {}
        done = max(int(active.get("level") or 0), len(inst.get("completedLevels") or []))
        entries.append({
            "evolution_id": active_id,
            "levels_done": done,
            "max_level": active.get("maxLevel"),
            "choices": [],
            "in_progress": True,
        })
    return entries
