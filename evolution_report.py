"""
Liste TOUS les joueurs de la base FC 27 éligibles à une évolution donnée,
avec leurs stats actuelles et projetées une fois l'évolution appliquée.

Contrairement à optimize.py (qui ne regarde que ton club), ce script scanne
toute la base : utile pour voir qui, en théorie, remplit les critères
(poste, note max, vitesse max, nombre de PlayStyles...) d'une évolution.

Usage:
    python evolution_report.py --db fut27.db --evolution 2508 --out rapport.xlsx
    python evolution_report.py --db fut27.db --list                # voir les ids/noms disponibles
    python evolution_report.py --db fut27.db --list --include-inactive   # + les evolutions expirees (retrouver un id pour un rattrapage via record_evolution.py)
    python evolution_report.py --db fut27.db --evolution 2508 --out rapport.xlsx --position ST
"""
import argparse
import ast
import json
import sqlite3

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.filters import FilterColumn, Filters

# Filtre "Club" pre-applique par defaut sur chaque onglet (demande utilisateur :
# Ligue 1 -> PSG/OL, LaLiga -> Real Madrid/FC Barcelone, Bundesliga -> Bayern/
# Dortmund/Leipzig/Leverkusen). Le filtre auto reste modifiable dans Excel.
CLUB_FILTER_PRESET = [
    "PSG", "OL",
    "Real Madrid", "FC Barcelona",
    "FC Bayern München", "Borussia Dortmund", "RB Leipzig", "Leverkusen",
]

MAIN_STAT_FIELDS = ["pace", "shooting", "passing", "dribbling", "defending", "physicality"]
STAT_ALIASES = {
    "OVR": "overall",
    "PAC": "pace", "Sprint Speed": "pace", "Acceleration": "pace",
    "SHO": "shooting", "Finishing": "shooting", "Shot Power": "shooting",
    "Long Shots": "shooting", "Penalties": "shooting", "Volleys": "shooting",
    "Att. Pos.": "shooting",
    "PAS": "passing", "Vision": "passing", "Short Pass": "passing", "Long Pass": "passing",
    "Crossing": "passing", "Curve": "passing", "Fk Acc.": "passing",
    "DRI": "dribbling", "Ball Control": "dribbling", "Agility": "dribbling",
    "Balance": "dribbling", "Composure": "dribbling", "Reactions": "dribbling",
    "DEF": "defending", "Stand Tackle": "defending", "Slide Tackle": "defending",
    "Interceptions": "defending", "Def. Aware.": "defending", "Heading Acc.": "defending",
    "PHY": "physicality", "Strength": "physicality", "Stamina": "physicality",
    "Aggression": "physicality", "Jumping": "physicality",
    "WF": "weak_foot", "SM": "skill_moves",
}

# Sous-stats fixes de chaque categorie principale (joueurs de champ). La note
# globale d'une categorie (ex: Pace) est calculee sur TOUTES ses sous-stats,
# y compris celles que l'evolution ne touche pas (delta 0 pour celles-la) -
# sinon on fausse la moyenne en ne divisant que par le nombre de sous-stats
# effectivement modifiees par l'evolution.
CATEGORY_SUBSTATS = {
    "pace": ["Acceleration", "Sprint Speed"],
    "shooting": ["Att. Pos.", "Finishing", "Shot Power", "Long Shots", "Volleys", "Penalties"],
    "passing": ["Vision", "Crossing", "Fk Acc.", "Short Pass", "Long Pass", "Curve"],
    "dribbling": ["Agility", "Balance", "Reactions", "Ball Control", "Dribbling", "Composure"],
    "defending": ["Interceptions", "Heading Acc.", "Def. Aware.", "Stand Tackle", "Slide Tackle"],
    "physicality": ["Jumping", "Stamina", "Strength", "Aggression"],
}

# Poids reels utilises par EA pour deriver une note principale (Pace, Shooting,
# ...) a partir de ses sous-stats detaillees (source : fifauteam.com/fc-27-attributes,
# recoupe empiriquement sur des cartes avant/apres evolution reelles). Ce n'est
# PAS une moyenne equiponderee : ex. Fk Acc. ne pese que 5% dans Passing alors
# que Short Pass pese 35%. Une moyenne simple surestime l'effet des sous-stats
# a faible poids (souvent celles qui recoivent les plus gros gains d'evolution,
# comme Fk Acc.) et fausse la note principale projetee.
CATEGORY_WEIGHTS = {
    "pace": {"Acceleration": 0.45, "Sprint Speed": 0.55},
    "shooting": {
        "Att. Pos.": 0.05, "Finishing": 0.45, "Shot Power": 0.20,
        "Long Shots": 0.20, "Volleys": 0.05, "Penalties": 0.05,
    },
    "passing": {
        "Vision": 0.20, "Crossing": 0.20, "Fk Acc.": 0.05,
        "Short Pass": 0.35, "Long Pass": 0.15, "Curve": 0.05,
    },
    "dribbling": {
        "Agility": 0.10, "Balance": 0.05, "Reactions": 0.0,
        "Ball Control": 0.35, "Dribbling": 0.50, "Composure": 0.0,
    },
    "defending": {
        "Interceptions": 0.20, "Heading Acc.": 0.10, "Def. Aware.": 0.30,
        "Stand Tackle": 0.30, "Slide Tackle": 0.10,
    },
    "physicality": {
        "Jumping": 0.05, "Stamina": 0.25, "Strength": 0.50, "Aggression": 0.20,
    },
}

# Les libellés utilisés par fut.gg dans les upgrades d'évolution ne sont pas
# toujours exactement ceux affichés sur la fiche détaillée d'une carte
# (abréviations différentes). Table de correspondance pour appliquer le bon
# delta à la bonne sous-stat détaillée.
DETAIL_LABEL_ALIASES = {
    "Positioning": "Att. Pos.",
    "Fk Accuracy": "Fk Acc.",
    "Defensive Awareness": "Def. Aware.",
    "Standing Tackle": "Stand Tackle",
    "Sliding Tackle": "Slide Tackle",
    "Heading Accuracy": "Heading Acc.",
}


def parse_alt_positions(raw) -> list:
    """Lit `alternative_positions` : JSON, ou repr Python (anciennes lignes)."""
    if not raw or raw == "None":
        return []
    try:
        return json.loads(raw)
    except ValueError:
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []


def load_evolutions(conn: sqlite3.Connection, include_inactive: bool = False) -> list[dict]:
    query = "SELECT * FROM evolutions"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY id DESC"
    cur = conn.execute(query)
    cols = [d[0] for d in cur.description]
    evolutions = [dict(zip(cols, r)) for r in cur.fetchall()]

    usage = dict(
        conn.execute(
            "SELECT evolution_id, COUNT(*) FROM used_evolutions GROUP BY evolution_id"
        ).fetchall()
    )
    for evo in evolutions:
        used = usage.get(evo["id"], 0)
        # repeatability_count absent (page pas encore re-scrapee, ou champ
        # introuvable) : on part du principe le plus prudent, usage unique.
        limit = evo.get("repeatability_count") or 1
        evo["used_count"] = used
        evo["remaining_uses"] = max(0, limit - used)
    return evolutions


def available_evolutions(evolutions: list[dict]) -> list[dict]:
    """Ecarte les evolutions dont le quota d'usage (repeatability_count) est
    deja epuise d'apres l'historique enregistre dans used_evolutions."""
    return [e for e in evolutions if e["remaining_uses"] > 0]


def check_eligibility(player: dict, req: dict) -> list[str]:
    """Renvoie la liste des conditions non remplies (vide = eligible). Le
    poste requis ("Position") est valide des que le poste principal OU un
    poste alternatif du joueur correspond - comme dans le jeu, un MC pouvant
    jouer MDC est eligible a une evolution qui demande MDC."""
    reasons: list[str] = []

    primary = player["position"]
    alt = player.get("alt_positions") or []
    all_positions = {primary, *alt}

    if "overall_max" in req and player["overall"] > req["overall_max"]:
        reasons.append(f"Note {player['overall']} > max {req['overall_max']}")
    if "position_in" in req and not (all_positions & set(req["position_in"])):
        reasons.append(f"Poste {sorted(all_positions)} pas dans {req['position_in']}")
    if "position_excluded" in req:
        bad = all_positions & set(req["position_excluded"])
        if bad:
            reasons.append(f"Poste exclu present: {sorted(bad)}")
    if "max_position_count" in req and (1 + len(alt)) > req["max_position_count"]:
        reasons.append(f"Trop de postes ({1 + len(alt)} > {req['max_position_count']})")
    if "pace_max" in req and (player["pace"] or 0) > req["pace_max"]:
        reasons.append(f"Vitesse {player['pace']} > max {req['pace_max']}")
    if "max_playstyles" in req:
        total_ps = len(player.get("ps_plus") or []) + len(player.get("ps_normal") or [])
        if total_ps > req["max_playstyles"]:
            reasons.append(f"Trop de PlayStyles ({total_ps} > {req['max_playstyles']})")
    return reasons


def matches_requirements(player: dict, req: dict) -> bool:
    return not check_eligibility(player, req)


def apply_upgrades(
    player: dict, upgrades: list[dict], granted_playstyles: list[str] | None = None
) -> tuple[dict, dict[str, str]]:
    """Projette les stats d'un joueur apres application d'une evolution.

    Important : les gains d'évolution ("+40 Vision", ...) ne sont PAS des
    deltas bruts a additionner tels quels - fut.gg (et le jeu) les affiche
    comme "current + delta, plafonne a result_value". Un joueur a 72 avec
    "+40 (max 79)" finit a 79, pas a 112. On applique donc le plafond sur
    chaque sous-stat detaillee, PUIS on derive la stat principale (Pace,
    Shooting, ...) en moyennant les deltas *deja plafonnes* de ses sous-stats,
    ce qui reproduit correctement l'effet du plafond sur l'agregat aussi.
    """
    detail_values: dict[str, int | str] = {}
    if player.get("detail_pairs"):
        for label, val in player["detail_pairs"]:
            try:
                detail_values[label] = int(val)
            except (TypeError, ValueError):
                detail_values[label] = val

    after_detail: dict[str, str] = {
        label: str(val) for label, val in detail_values.items()
    }
    category_capped_deltas: dict[str, list[int]] = {}
    overall_delta = 0
    weak_foot = player.get("weak_foot")
    skill_moves = player.get("skill_moves")

    for u in upgrades:
        stat, delta, cap = u["stat"], u["delta"], u.get("result_value")

        if stat == "OVR":
            new_val = player["overall"] + delta
            if cap is not None:
                new_val = max(player["overall"], min(new_val, cap))
            overall_delta = new_val - player["overall"]
            continue
        if stat == "WF":
            if weak_foot is not None:
                new_val = weak_foot + delta
                weak_foot = max(weak_foot, min(new_val, cap)) if cap is not None else new_val
            continue
        if stat == "SM":
            if skill_moves is not None:
                new_val = skill_moves + delta
                skill_moves = max(skill_moves, min(new_val, cap)) if cap is not None else new_val
            continue

        label = DETAIL_LABEL_ALIASES.get(stat, stat)
        category = STAT_ALIASES.get(label)
        current = detail_values.get(label)
        if isinstance(current, int):
            new_val = current + delta
            # Le plafond ne doit jamais FAIRE BAISSER une stat deja au-dessus
            # (ex: Jumping deja a 87 avec un plafond d'evolution a 76 : on
            # garde 87, on ne redescend pas).
            if cap is not None:
                new_val = max(current, min(new_val, cap))
            after_detail[label] = str(new_val)
            capped_delta = new_val - current
        else:
            # pas de sous-stat detaillee correspondante disponible : on retombe
            # sur le delta brut (sans plafond, moins precis mais rare une fois
            # la base entierement detaillee).
            capped_delta = delta

        if category in MAIN_STAT_FIELDS:
            category_capped_deltas.setdefault(category, {})[label] = capped_delta

    after_main = dict(player)
    after_main["overall"] = player["overall"] + overall_delta
    after_main["weak_foot"] = weak_foot
    after_main["skill_moves"] = skill_moves
    for field, touched_deltas in category_capped_deltas.items():
        if player.get(field) is None:
            continue
        substats = CATEGORY_SUBSTATS.get(field, [])
        weights = CATEGORY_WEIGHTS.get(field)

        weighted_value = None
        if weights and substats:
            try:
                weighted_value = round(
                    sum(weights.get(s, 0.0) * int(after_detail[s]) for s in substats)
                )
            except (KeyError, TypeError, ValueError):
                # sous-stat detaillee manquante (carte pas entierement scrapee) :
                # on retombe sur l'approximation par delta ci-dessous.
                weighted_value = None

        if weighted_value is not None:
            after_main[field] = weighted_value
        elif substats:
            # Repli si les sous-stats detaillees sont incompletes : moyenne sur
            # TOUTES les sous-stats de la categorie (0 pour celles non touchees
            # par l'evolution), pas seulement celles modifiees - sinon on divise
            # par le mauvais nombre et on fausse la moyenne. Moins precis que le
            # calcul pondere ci-dessus (qui reproduit la vraie formule EA).
            total_delta = sum(touched_deltas.get(s, 0) for s in substats)
            after_main[field] = player[field] + round(total_delta / len(substats))
        else:
            avg = round(sum(touched_deltas.values()) / len(touched_deltas))
            after_main[field] = player[field] + avg

    if granted_playstyles:
        existing = set(player.get("ps_plus") or []) | set(player.get("ps_normal") or [])
        new_ones = [ps for ps in granted_playstyles if ps not in existing]
        after_main["ps_normal"] = list(player.get("ps_normal") or []) + new_ones

    return after_main, after_detail


def load_players(conn: sqlite3.Connection, position: str | None) -> list[dict]:
    query = """
        SELECT p.id, p.common_name, p.overall, p.position, p.alternative_positions,
               p.club, p.league, p.nation, p.rarity_name,
               p.pace, p.shooting, p.passing, p.dribbling, p.defending, p.physicality,
               p.weak_foot, p.skill_moves, p.playstyles_plus, p.playstyles_normal,
               pa.detail_stats_json
        FROM players p
        LEFT JOIN player_attributes pa ON pa.player_id = p.id
    """
    params: list = []
    if position:
        query += " WHERE p.position = ?"
        params.append(position)

    out = []
    for row in conn.execute(query, params):
        (
            pid, name, overall, pos, alt_raw, club, league, nation, rarity,
            pace, shooting, passing, dribbling, defending, physicality,
            weak_foot, skill_moves, ps_plus_raw, ps_normal_raw, detail_json,
        ) = row
        alt_positions = parse_alt_positions(alt_raw)
        out.append(
            {
                "id": pid,
                "common_name": name,
                "overall": overall,
                "position": pos,
                "alt_positions": alt_positions,
                "club": club,
                "league": league,
                "nation": nation,
                "rarity_name": rarity,
                "pace": pace,
                "shooting": shooting,
                "passing": passing,
                "dribbling": dribbling,
                "defending": defending,
                "physicality": physicality,
                "weak_foot": weak_foot,
                "skill_moves": skill_moves,
                "ps_plus": json.loads(ps_plus_raw or "[]"),
                "ps_normal": json.loads(ps_normal_raw or "[]"),
                "detail_pairs": json.loads(detail_json) if detail_json else None,
            }
        )
    return out


CONDITION_LABELS = {
    "overall_max": lambda v: f"Overall Max {v}",
    "position_in": lambda v: f"Position {', '.join(v)}",
    "position_excluded": lambda v: f"Excluded Position : {', '.join(v)}",
    "max_playstyles": lambda v: f"Max PS {v}",
    "pace_max": lambda v: f"Pace Max. {v}",
    "max_position_count": lambda v: f"Max Pos. {v}",
}

CATEGORY_GROUP_CODE = {
    "pace": "PAC", "shooting": "SHO", "passing": "PAS",
    "dribbling": "DRI", "defending": "DEF", "physicality": "PHY",
}
GROUP_ORDER = ["OVR", "PAC", "SHO", "PAS", "DRI", "DEF", "PHY", "WF", "SM", "PS", "Autre"]

BOLD = Font(bold=True)


def write_conditions_block(ws, start_row: int, req: dict) -> int:
    ws.cell(row=start_row, column=1, value="Conditions").font = BOLD
    row = start_row + 1
    lines = [fmt(req[key]) for key, fmt in CONDITION_LABELS.items() if key in req]
    for line in lines or ["Aucune condition"]:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        ws.cell(row=row, column=1, value=line)
        row += 1
    return row


def write_gains_block(
    ws, start_row: int, upgrades: list[dict], granted_playstyles: list[str] | None = None, start_col: int = 3
) -> int:
    ws.cell(row=start_row, column=start_col, value="Gains").font = BOLD

    grouped: dict[str, list[dict]] = {}
    for u in upgrades:
        stat = u["stat"]
        if stat in ("OVR", "WF", "SM"):
            group = stat
        else:
            normalized = DETAIL_LABEL_ALIASES.get(stat, stat)
            group = CATEGORY_GROUP_CODE.get(STAT_ALIASES.get(normalized), "Autre")
        grouped.setdefault(group, []).append(u)
    if granted_playstyles:
        grouped["PS"] = [{"stat": ps, "delta": None, "result_value": None} for ps in granted_playstyles]

    col = start_col
    max_row = start_row + 1
    for group in GROUP_ORDER:
        items = grouped.get(group)
        if not items:
            continue
        ws.cell(row=start_row + 1, column=col, value=group).font = BOLD
        row = start_row + 2
        for u in items:
            cap = f" (max {u['result_value']})" if u.get("result_value") is not None else ""
            if group == "PS":
                text = u["stat"]
            elif group in ("OVR", "WF", "SM"):
                text = f"+{u['delta']}{cap}"
            else:
                text = f"+{u['delta']} {u['stat']}{cap}"
            ws.cell(row=row, column=col, value=text)
            row += 1
        max_row = max(max_row, row)
        col += 1
    return max_row


def add_sheet(wb: Workbook, ws_title: str, players: list[dict], evo: dict) -> int:
    req = json.loads(evo["requirements_json"] or "{}")
    upgrades = json.loads(evo["upgrades_json"] or "[]")
    granted_playstyles = json.loads(evo.get("granted_playstyles") or "[]")

    eligible = [p for p in players if matches_requirements(p, req)]
    eligible.sort(key=lambda p: p["overall"], reverse=True)

    # Colonnes de detail : union de tout ce qui existe chez les joueurs eligibles
    # deja detailles (evite une colonne par sous-stat si personne n'en a).
    # Une categorie principale (ex: "Dribbling") partage son nom avec l'une de
    # ses propres sous-stats : on ne saute que la PREMIERE occurrence (la note
    # globale), pas la seconde (la vraie sous-stat), sinon elle disparait de
    # l'export.
    MAIN_LABELS_CAP = {"Pace", "Shooting", "Passing", "Dribbling", "Defending", "Physical"}
    detail_labels: list[str] = []
    for p in eligible:
        if not p["detail_pairs"]:
            continue
        seen_main: set[str] = set()
        for label, _ in p["detail_pairs"]:
            if label in MAIN_LABELS_CAP and label not in seen_main:
                seen_main.add(label)
                continue
            if label not in detail_labels:
                detail_labels.append(label)

    columns = (
        ["Nom", "Poste", "Note actuelle", "Note finale", "Gain OVR",
         "Club", "Ligue", "Nation", "Rarete",
         "PS+", "PS (avant)", "PS (apres)"]
        + [f"{s.capitalize()} (avant)" for s in MAIN_STAT_FIELDS]
        + [f"{s.capitalize()} (apres)" for s in MAIN_STAT_FIELDS]
        + [f"{lbl} (avant)" for lbl in detail_labels]
        + [f"{lbl} (apres)" for lbl in detail_labels]
    )

    rows = []
    for p in eligible:
        after_main, after_detail = apply_upgrades(p, upgrades, granted_playstyles)
        before_detail = {lbl: val for lbl, val in (p["detail_pairs"] or [])}

        row = (
            [
                p["common_name"], p["position"], p["overall"], after_main["overall"],
                after_main["overall"] - p["overall"],
                p["club"], p["league"], p["nation"], p["rarity_name"],
                ", ".join(p["ps_plus"]), ", ".join(p["ps_normal"]),
                ", ".join(after_main.get("ps_normal") or p["ps_normal"]),
            ]
            + [p[s] for s in MAIN_STAT_FIELDS]
            + [after_main[s] for s in MAIN_STAT_FIELDS]
            + [before_detail.get(lbl, "") for lbl in detail_labels]
            + [after_detail.get(lbl, "") for lbl in detail_labels]
        )
        rows.append(row)

    coin_cost = evo.get("coin_cost")
    point_cost = evo.get("point_cost")
    if coin_cost or point_cost:
        cost_bits = []
        if coin_cost:
            cost_bits.append(f"{coin_cost:,} pieces".replace(",", " "))
        if point_cost:
            cost_bits.append(f"{point_cost:,} FC Points".replace(",", " "))
        cost_label = "PAYANTE : " + " + ".join(cost_bits)
    else:
        cost_label = "Gratuite"

    ws = wb.create_sheet(title=ws_title)
    n_cols = len(columns)

    ws.cell(row=1, column=1, value=f"{evo['name']}  -  {cost_label}").font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)

    cond_end = write_conditions_block(ws, 3, req)
    gains_end = write_gains_block(ws, 3, upgrades, granted_playstyles, start_col=4)
    header_end = max(cond_end, gains_end)

    table_header_row = header_end + 1
    for i, col in enumerate(columns, start=1):
        ws.cell(row=table_header_row, column=i, value=col).font = BOLD
    for row in rows:
        ws.append(row)
    for i, col in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(22, len(col) + 2))
    ws.freeze_panes = f"A{table_header_row + 1}"

    last_row = table_header_row + len(rows)
    ws.auto_filter.ref = f"A{table_header_row}:{get_column_letter(n_cols)}{last_row}"

    club_col_idx = columns.index("Club")  # 0-based, position dans la plage du filtre
    filter_col = FilterColumn(colId=club_col_idx)
    filter_col.filters = Filters(filter=CLUB_FILTER_PRESET)
    ws.auto_filter.filterColumn = [filter_col]
    for i, row in enumerate(rows):
        if row[club_col_idx] not in CLUB_FILTER_PRESET:
            ws.row_dimensions[table_header_row + 1 + i].hidden = True

    return len(rows)


def unique_sheet_title(name: str, evo_id: int, used: set[str]) -> str:
    base = (name or f"Evolution {evo_id}")[:31]
    title = base
    if title in used:
        suffix = f" ({evo_id})"
        title = base[: 31 - len(suffix)] + suffix
    used.add(title)
    return title


def build_report(players: list[dict], evo: dict, out_path: str) -> int:
    wb = Workbook()
    wb.remove(wb.active)
    n = add_sheet(wb, unique_sheet_title(evo["name"], evo["id"], set()), players, evo)
    wb.save(out_path)
    return n


def has_real_conditions(evo: dict) -> bool:
    req = json.loads(evo["requirements_json"] or "{}")
    return bool(req)


def build_all_reports(players: list[dict], evolutions: list[dict], out_path: str) -> list[tuple[str, int]]:
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    counts = []
    for evo in evolutions:
        if not has_real_conditions(evo):
            continue
        title = unique_sheet_title(evo["name"], evo["id"], used)
        n = add_sheet(wb, title, players, evo)
        counts.append((evo["name"], n))
    wb.save(out_path)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fut27.db")
    parser.add_argument("--evolution", type=int, default=None)
    parser.add_argument("--all", action="store_true", help="un onglet par evolution active, dans un seul xlsx")
    parser.add_argument("--out", default="rapport_evolution.xlsx")
    parser.add_argument("--position", default=None, help="filtre optionnel, ex: ST")
    parser.add_argument("--list", action="store_true", help="lister les evolutions disponibles")
    parser.add_argument(
        "--include-inactive", action="store_true",
        help="avec --list : inclut aussi les evolutions expirees (utile pour retrouver l'id "
             "d'une evolution deja disparue de fut.gg, ex: rattrapage via record_evolution.py)",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    evolutions = load_evolutions(conn, include_inactive=args.include_inactive)

    if args.list or not (args.evolution or args.all):
        print("Evolutions disponibles :" if not args.include_inactive else "Evolutions (actives + expirees) :")
        for e in evolutions:
            cost = []
            if e.get("coin_cost"):
                cost.append(f"{e['coin_cost']:,} pieces".replace(",", " "))
            if e.get("point_cost"):
                cost.append(f"{e['point_cost']:,} FC Points".replace(",", " "))
            cost_str = f" [PAYANTE: {' + '.join(cost)}]" if cost else ""
            limit = e.get("repeatability_count") or 1
            if e["remaining_uses"] <= 0:
                usage_str = f" [EPUISEE {e['used_count']}/{limit}]"
            elif limit > 1:
                usage_str = f" [{e['remaining_uses']}/{limit} restants]"
            else:
                usage_str = ""
            print(f"  {e['id']:>6}  {e['name']}{cost_str}{usage_str}  -  {e['requirements_text'] or 'aucune condition'}")
        if not (args.evolution or args.all):
            return

    players = load_players(conn, args.position)

    if args.all:
        usable = available_evolutions(evolutions)
        skipped = len(evolutions) - len(usable)
        if skipped:
            print(f"({skipped} evolution(s) epuisee(s) exclue(s) - voir --list)")
        counts = build_all_reports(players, usable, args.out)
        for name, n in counts:
            print(f"  {name}: {n} joueurs eligibles")
        print(f"-> {args.out} ({len(counts)} onglets)")
        return

    evo = next((e for e in evolutions if e["id"] == args.evolution), None)
    if evo is None:
        print(f"Evolution id={args.evolution} introuvable. Utilise --list pour voir les ids.")
        return
    if evo["remaining_uses"] <= 0:
        print(f"ATTENTION : '{evo['name']}' est deja epuisee ({evo['used_count']} usage(s) enregistre(s)). Rapport genere quand meme.")

    n = build_report(players, evo, args.out)
    print(f"{n} joueurs eligibles a '{evo['name']}' -> {args.out}")


if __name__ == "__main__":
    main()
