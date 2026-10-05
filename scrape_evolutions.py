"""
Récupère les définitions des évolutions actives d'EA SPORTS FC 27
(conditions d'éligibilité + gains de statistiques) depuis fut.gg.

fut.gg ne publie pas d'API JSON propre pour la liste des évolutions
(page rendue côté serveur), donc ce script parse le HTML de
https://www.fut.gg/evolutions/ et complète, pour chaque évolution
détectée, les détails via sa page dédiée /evolutions/<id>-<slug>/.

Usage:
    python scrape_evolutions.py [--out fut27.db]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from evo_levels import ensure_level_columns, parse_levels_from_html
from playstyles import PLAY_STYLE_NAMES

KNOWN_PLAYSTYLE_NAMES = set(PLAY_STYLE_NAMES.values())

BASE = "https://www.fut.gg"
LIST_URL = f"{BASE}/evolutions/"
HEADERS = {
    "User-Agent": "fut27-db-builder/1.0 (usage personnel, contact via github)",
    "Accept": "text/html",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS evolutions (
    id INTEGER PRIMARY KEY,        -- id fut.gg de l'evolution (ex: 2508)
    slug TEXT,
    name TEXT,
    description TEXT,
    requirements_text TEXT,        -- texte brut des conditions (cf. requirements_json pour le parse)
    requirements_json TEXT,        -- {"overall_max": 79, "position_in": ["ST"], "position_excluded": [...], ...}
    upgrades_text TEXT,            -- texte brut des gains
    upgrades_json TEXT,            -- [{"stat": "OVR", "delta": 5}, ...] (branche principale)
    levels_json TEXT,              -- paliers et options (cf. evo_levels.py)
    coin_cost INTEGER,             -- cout en pieces FUT (NULL/0 si gratuite)
    point_cost INTEGER,            -- cout en FC Points (NULL/0 si gratuite)
    granted_playstyles TEXT,       -- liste JSON des PlayStyles accordes (pas visible sur la page liste,
                                    -- uniquement sur la page detail de chaque evolution)
    repeatability_count INTEGER,   -- nombre de fois qu'on peut utiliser cette evolution sur le compte
                                    -- (1 = usage unique, la grande majorite ; >1 = repetable N fois)
    active INTEGER DEFAULT 1,      -- 0 si l'evolution a expire (plus dans la liste active de fut.gg) ;
                                    -- on garde la ligne (au lieu de la supprimer) pour ne pas casser
                                    -- l'historique used_evolutions qui y fait reference.
    url TEXT
);

CREATE TABLE IF NOT EXISTS used_evolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evolution_id INTEGER NOT NULL REFERENCES evolutions(id),
    player_ea_id INTEGER,           -- id EA du joueur evolue (fiable, pas ambigu comme le nom)
    player_name TEXT,               -- copie du nom au moment de l'enregistrement (lisibilite)
    date_applied TEXT DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    level INTEGER,                  -- paliers termines (NULL = evolution terminee)
    max_level INTEGER,
    path_choices TEXT               -- JSON : option choisie par palier, ex. [1, 1, 3]
);
"""

STAT_LINE_RE = re.compile(r"^([+-])\s*(\d+)\s+(.+)$")


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def list_evolution_cards(session: requests.Session) -> list[dict]:
    """La page /evolutions/ est entièrement rendue côté serveur : chaque
    évolution y apparaît avec son nom, ses conditions et ses gains déjà en
    clair dans le HTML (pas besoin de visiter une page détail par évolution,
    qui utilise d'ailleurs une mise en page différente)."""
    soup = get_soup(LIST_URL, session)
    cards = []
    seen_ids = set()
    for a in soup.select("a[href^='/evolutions/']"):
        href = a.get("href", "")
        m = re.match(r"^/evolutions/(\d+)-([a-z0-9-]+)/$", href)
        if not m:
            continue
        evo_id = int(m.group(1))
        if evo_id in seen_ids:
            continue
        card = a.parent
        h3_tags = {h.get_text(strip=True): h for h in card.find_all("h3")}
        if "Requirements" not in h3_tags or "Upgrades" not in h3_tags:
            continue  # pas une carte d'évolution complète (ex: doublon de lien)
        seen_ids.add(evo_id)
        h2 = card.find("h2")
        cards.append(
            {
                "id": evo_id,
                "slug": m.group(2),
                "url": BASE + href,
                "name": h2.get_text(strip=True) if h2 else m.group(2),
                # "Requirements": le h3 est directement dans le conteneur des lignes.
                "req_container": h3_tags["Requirements"].parent,
                # "Upgrades": le h3 est dans un petit bandeau d'en-tête ; les chips
                # de gains sont dans le conteneur parent de ce bandeau.
                "upg_container": h3_tags["Upgrades"].parent.parent,
                "coin_cost": parse_cost(card, "FC Coin"),
                "point_cost": parse_cost(card, "FC Points"),
            }
        )
    return cards


def parse_cost(card, icon_alt: str) -> int | None:
    """Le cout (pieces ou FC Points) est affiche comme un nombre juste avant une
    icone <img alt="FC Coin"|"FC Points">. Absent si l'evolution est gratuite."""
    img = card.find("img", alt=icon_alt)
    if img is None:
        return None
    container = img.parent
    span = container.find("span") if container else None
    if span is None:
        return None
    text = span.get_text(strip=True).replace(",", "")
    return int(text) if text.isdigit() else None


def parse_requirements(container) -> dict:
    """Transforme le bloc 'Requirements' en dict structuré (best-effort)."""
    req: dict = {}
    if container is None:
        return req
    rows = container.select("div.flex.justify-between")
    for row in rows:
        texts = [t.get_text(strip=True) for t in row.find_all("div", recursive=False)]
        if len(texts) < 2:
            continue
        label, value = texts[0], texts[1]
        label_l = label.lower()
        if label_l == "overall":
            m = re.search(r"(\d+)", value)
            if m:
                req["overall_max"] = int(m.group(1))
        elif label_l == "position":
            req["position_in"] = [v.strip() for v in value.split(",")]
        elif label_l == "excluded position":
            req["position_excluded"] = [v.strip() for v in value.split(",")]
        elif label_l == "max ps":
            m = re.search(r"(\d+)", value)
            if m:
                req["max_playstyles"] = int(m.group(1))
        elif label_l == "pace":
            m = re.search(r"(\d+)", value)
            if m:
                req["pace_max"] = int(m.group(1))
        elif label_l == "max pos.":
            m = re.search(r"(\d+)", value)
            if m:
                req["max_position_count"] = int(m.group(1))
        else:
            req[label] = value
    return req


def parse_upgrades(container) -> list[dict]:
    """Transforme le bloc 'Upgrades' en liste de deltas de stats. Chaque gain est
    affiché comme un "chip" (ex: "+5 OVR" avec la valeur finale 81 dans un span
    imbriqué). On isole le span (valeur finale) du texte du chip (signe+delta+nom)."""
    upgrades: list[dict] = []
    if container is None:
        return upgrades
    for chip in container.select("div.rounded.font-bold.flex.items-center.gap-1"):
        chip = BeautifulSoup(str(chip), "html.parser")
        result_span = chip.find("span")
        result_value = result_span.get_text(strip=True) if result_span else None
        if result_span:
            result_span.decompose()
        for svg in chip.find_all("svg"):
            svg.decompose()
        label = chip.get_text(" ", strip=True)
        m = STAT_LINE_RE.match(label)
        if not m:
            continue
        sign, amount, stat = m.groups()
        delta = int(amount) if sign == "+" else -int(amount)
        upgrades.append(
            {
                "stat": stat.strip(),
                "delta": delta,
                "result_value": int(result_value) if result_value and result_value.isdigit() else None,
            }
        )
    return upgrades


REPEATABILITY_RE = re.compile(r"repeatabilityCount:(-?\d+)")


def scrape_detail_page_extras(
    url: str, session: requests.Session
) -> tuple[list[str], int | None, list[dict] | None]:
    """Deux infos ne sont visibles QUE sur la page detail de l'evolution (pas
    sur la page liste /evolutions/) :
    - les PlayStyles accordes : une icone (div title="<Nom du PlayStyle>",
      sans le "+N" habituel des gains de stats) ;
    - repeatabilityCount : combien de fois cette evolution peut etre utilisee
      sur le compte (1 = usage unique, la grande majorite des evolutions ;
      >1 = repetable N fois). Ce champ vient d'un objet JS serialise (React
      Server Components) embarque brut dans le HTML, pas d'une vraie API JSON."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except requests.RequestException:
        return [], None, None

    soup = BeautifulSoup(html, "html.parser")
    names = {
        el.get("title")
        for el in soup.select("div[title]")
        if el.get("title") in KNOWN_PLAYSTYLE_NAMES
    }

    m = REPEATABILITY_RE.search(html)
    repeatability_count = int(m.group(1)) if m else None

    return sorted(names), repeatability_count, parse_levels_from_html(html)


OBJECTIVE_LINK_RE = re.compile(r"/objectives/[a-z-]+/(\d+)-([a-z0-9-]+)/")
EVOLUTION_LINK_RE = re.compile(r"/evolutions/(\d+)-([a-z0-9-]+)/")
NAME_SUFFIX_RE = re.compile(r"^(.*?)\s+-\s+EA SPORTS FC \d+$")


def find_objective_detail_urls(session: requests.Session) -> list[str]:
    """La page /objectives/ liste, en une seule page, toutes les campagnes/
    objectifs actifs (Season Pass, Foundations, Seasonal, Campaigns, Live
    Events, Milestones, Mastery, FC Pro...) avec un lien vers leur page
    detail /objectives/<categorie>/<id>-<slug>/. On y recupere tous ces
    liens (regex sur le HTML brut, plus simple/robuste que parcourir chaque
    onglet de categorie separement)."""
    resp = session.get(f"{BASE}/objectives/", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    paths = sorted({m.group(0) for m in OBJECTIVE_LINK_RE.finditer(resp.text)})
    return [BASE + p for p in paths]


def find_evolution_refs(url: str, session: requests.Session) -> list[tuple[int, str]]:
    """Certaines evolutions (ex: 'Believe', recompense de la campagne 'Ted
    Lasso's Masterclass') ne sont JAMAIS listees sur /evolutions/ ni
    /evolutions/expired/ : elles ne sont accessibles que via un lien depuis
    la page detail de l'objectif qui les debloque. On extrait ces liens
    /evolutions/<id>-<slug>/ du HTML de la page objectif."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    found: dict[int, str] = {}
    for m in EVOLUTION_LINK_RE.finditer(resp.text):
        found.setdefault(int(m.group(1)), m.group(2))
    return list(found.items())


def _find_h2(soup: BeautifulSoup, text: str):
    for h2 in soup.find_all("h2"):
        if h2.get_text(strip=True) == text:
            return h2
    return None


def scrape_evolution_detail_page(evo_id: int, slug: str, session: requests.Session) -> dict | None:
    """Scrape une evolution directement depuis sa page detail /evolutions/<id>-<slug>/
    plutot que depuis une carte de /evolutions/ (mise en page differente : sections
    'Player Requirements' / 'Evolution Upgrades' / 'Details' identifiees par leur <h2>
    plutot que par les <h3> 'Requirements'/'Upgrades' des cartes de la page liste).
    Necessaire pour les evolutions trouvees via find_evolution_refs (objectifs),
    qui n'ont pas de carte sur /evolutions/."""
    url = f"{BASE}/evolutions/{evo_id}-{slug}/"
    try:
        soup = get_soup(url, session)
    except requests.RequestException:
        return None

    h1 = soup.find("h1")
    if h1 is None:
        return None
    raw_name = h1.get_text(strip=True)
    m = NAME_SUFFIX_RE.match(raw_name)
    name = m.group(1) if m else raw_name
    desc_p = h1.find_next_sibling("p")
    description = desc_p.get_text(strip=True) if desc_p else None

    req_h2 = _find_h2(soup, "Player Requirements")
    upg_h2 = _find_h2(soup, "Evolution Upgrades")
    details_h2 = _find_h2(soup, "Details")

    req_container = req_h2.parent.parent if req_h2 else None
    # Le conteneur h2.parent.parent regroupe uniquement le bandeau 'Evolution
    # Upgrades' + les chips du recap global (ex: branche par defaut/recommandee
    # d'une evolution a paliers) : les paliers detailles (Level 1, Level 2, ...)
    # vivent dans un conteneur frere separe et ne sont pas inclus ici, ce qui
    # garde une structure upgrades_json compatible avec celle des cartes liste.
    upg_container = upg_h2.parent.parent if upg_h2 else None

    coin_cost = point_cost = None
    if details_h2 is not None:
        for row in details_h2.parent.parent.select("div.flex.justify-between"):
            cells = [d.get_text(strip=True) for d in row.find_all("div", recursive=False)]
            if len(cells) < 2:
                continue
            label, value = cells
            digits = re.sub(r"[^\d]", "", value)
            if label == "Coins Cost" and value != "Free":
                coin_cost = int(digits) if digits else None
            elif label == "Points Cost" and value != "Free":
                point_cost = int(digits) if digits else None

    return {
        "id": evo_id,
        "slug": slug,
        "url": url,
        "name": name,
        "description": description,
        "req_container": req_container,
        "upg_container": upg_container,
        "coin_cost": coin_cost,
        "point_cost": point_cost,
    }


END_TIME_RE = re.compile(r'endTime:"([^"]+)"')


def evolution_is_live(url: str, session: requests.Session) -> bool:
    """Vrai si la page detail annonce une date de fin (endTime) dans le futur."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return False
    m = END_TIME_RE.search(resp.text)
    if not m:
        return False
    try:
        end = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    except ValueError:
        return False
    return end > datetime.now(timezone.utc)


def discover_objective_evolutions(
    conn: sqlite3.Connection, session: requests.Session, known_ids: set[int],
    current_ids: set[int] | None = None,
) -> list[int]:
    """Parcourt toutes les pages d'objectifs a la recherche d'evolutions qui
    n'apparaissent pas dans le scrape normal de /evolutions/ (recompenses de
    campagnes narratives, ex: 'Believe' via 'Ted Lasso's Masterclass'), et les
    ajoute en base. Retourne la liste des ids nouvellement ajoutes."""
    print("Recherche d'evolutions liees a des objectifs...")
    obj_urls = find_objective_detail_urls(session)
    print(f"  {len(obj_urls)} pages d'objectifs a inspecter")

    found: dict[int, str] = {}
    for url in obj_urls:
        for evo_id, evo_slug in find_evolution_refs(url, session):
            found.setdefault(evo_id, evo_slug)
        time.sleep(0.2)

    new_ids: list[int] = []
    for evo_id, evo_slug in found.items():
        if evo_id in known_ids:
            # deja en base : elle n'est pas dans /evolutions/ (sinon elle serait
            # deja active), donc on verifie sa date de fin avant de la laisser expirer.
            if current_ids is not None and evo_id not in current_ids:
                url = f"{BASE}/evolutions/{evo_id}-{evo_slug}/"
                if evolution_is_live(url, session):
                    conn.execute("UPDATE evolutions SET active = 1 WHERE id = ?", (evo_id,))
                    conn.commit()
                    new_ids.append(evo_id)
                    print(f"  = {evo_slug} (id={evo_id}) toujours active [source: objectif]")
                time.sleep(0.2)
            continue
        card = scrape_evolution_detail_page(evo_id, evo_slug, session)
        if card is None:
            print(f"  echec scraping evolution id={evo_id} ({evo_slug})", file=sys.stderr)
            continue
        granted_ps, repeatability_count, levels = scrape_detail_page_extras(card["url"], session)
        detail = build_record(card, granted_ps, repeatability_count, levels)
        upsert_evolution(conn, detail)
        conn.commit()
        new_ids.append(evo_id)
        print(f"  + {detail['name']} (id={evo_id}) ajoutee [source: objectif, {card['url']}]")
        time.sleep(0.2)

    if not new_ids:
        print("  aucune nouvelle evolution trouvee via les objectifs.")
    return new_ids


def build_record(
    card: dict, granted_playstyles: list[str], repeatability_count: int | None,
    levels: list[dict] | None = None,
) -> dict:
    req_container = card["req_container"]
    upg_container = card["upg_container"]
    requirements_json = parse_requirements(req_container)
    upgrades_json = parse_upgrades(upg_container)

    return {
        "id": card["id"],
        "slug": card["slug"],
        "name": card["name"],
        "description": card.get("description"),
        "requirements_text": req_container.get_text(" ", strip=True) if req_container else None,
        "requirements_json": json.dumps(requirements_json, ensure_ascii=False),
        "upgrades_text": upg_container.get_text(" ", strip=True) if upg_container else None,
        "upgrades_json": json.dumps(upgrades_json, ensure_ascii=False),
        "levels_json": json.dumps(levels, ensure_ascii=False) if levels else None,
        "coin_cost": card["coin_cost"],
        "point_cost": card["point_cost"],
        "granted_playstyles": json.dumps(granted_playstyles, ensure_ascii=False),
        "repeatability_count": repeatability_count,
        "active": 1,
        "url": card["url"],
    }


def upsert_evolution(conn: sqlite3.Connection, e: dict) -> None:
    conn.execute(
        """
        INSERT INTO evolutions (id, slug, name, description, requirements_text,
                                 requirements_json, upgrades_text, upgrades_json, levels_json,
                                 coin_cost, point_cost, granted_playstyles,
                                 repeatability_count, active, url)
        VALUES (:id, :slug, :name, :description, :requirements_text,
                :requirements_json, :upgrades_text, :upgrades_json, :levels_json,
                :coin_cost, :point_cost, :granted_playstyles,
                :repeatability_count, :active, :url)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, description=excluded.description,
            requirements_text=excluded.requirements_text,
            requirements_json=excluded.requirements_json,
            upgrades_text=excluded.upgrades_text,
            upgrades_json=excluded.upgrades_json,
            levels_json=COALESCE(excluded.levels_json, evolutions.levels_json),
            coin_cost=excluded.coin_cost,
            point_cost=excluded.point_cost,
            granted_playstyles=excluded.granted_playstyles,
            repeatability_count=excluded.repeatability_count,
            active=excluded.active,
            url=excluded.url
        """,
        e,
    )


def backfill_levels(conn: sqlite3.Connection, session: requests.Session) -> None:
    """Complete les paliers des evolutions deja en base qui n'en ont pas
    (expirees : jamais re-scrapees depuis la liste, ou base anterieure aux paliers)."""
    rows = conn.execute("SELECT id, url FROM evolutions WHERE levels_json IS NULL AND url IS NOT NULL").fetchall()
    for evo_id, url in rows:
        try:
            _, _, levels = scrape_detail_page_extras(url, session)
        except Exception as exc:  # noqa: BLE001
            print(f"  paliers id={evo_id} ECHEC: {exc}", file=sys.stderr)
            continue
        if levels:
            conn.execute("UPDATE evolutions SET levels_json = ? WHERE id = ?",
                         (json.dumps(levels, ensure_ascii=False), evo_id))
            print(f"  paliers recuperes pour id={evo_id}")
        else:
            print(f"  paliers introuvables pour id={evo_id} (page retiree ?)")
        time.sleep(0.3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="fut27.db")
    parser.add_argument(
        "--skip-objectives",
        action="store_true",
        help="ne pas chercher les evolutions recompenses d'objectifs (ex: 'Believe'), plus rapide",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.out)
    conn.executescript(SCHEMA)
    ensure_level_columns(conn)

    session = requests.Session()
    cards = list_evolution_cards(session)
    print(f"{len(cards)} evolutions actives trouvees")

    # On marque tout inactif d'abord : seules celles retrouvees ci-dessous
    # repasseront a active=1. Celles qui ont expire (retirees de fut.gg,
    # ex: remplacees par une nouvelle evolution) restent en base pour ne pas
    # casser l'historique used_evolutions, mais disparaissent des rapports.
    conn.execute("UPDATE evolutions SET active = 0")

    current_ids = []
    for i, card in enumerate(cards, start=1):
        try:
            granted_ps, repeatability_count, levels = scrape_detail_page_extras(card["url"], session)
            detail = build_record(card, granted_ps, repeatability_count, levels)
            upsert_evolution(conn, detail)
            conn.commit()
            current_ids.append(card["id"])
            extra_ps = f" (+ PlayStyle: {', '.join(granted_ps)})" if granted_ps else ""
            extra_rep = f" [x{repeatability_count}]" if repeatability_count else " [x? inconnu]"
            print(f"[{i}/{len(cards)}] {detail['name']} (id={card['id']}) OK{extra_rep}{extra_ps}")
        except Exception as exc:  # noqa: BLE001 - on veut logguer et continuer
            print(f"[{i}/{len(cards)}] id={card['id']} ECHEC: {exc}", file=sys.stderr)
        time.sleep(0.3)

    if not args.skip_objectives:
        known_ids = {row[0] for row in conn.execute("SELECT id FROM evolutions")}
        current_ids.extend(discover_objective_evolutions(conn, session, known_ids, set(current_ids)))

    expired = conn.execute(
        "SELECT id, name FROM evolutions WHERE active = 0 AND id NOT IN ({})".format(
            ",".join("?" * len(current_ids))
        ),
        current_ids,
    ).fetchall() if current_ids else []
    for eid, ename in expired:
        print(f"  (expiree, retiree des rapports : {ename} id={eid})")

    backfill_levels(conn, session)

    conn.commit()
    print(f"Termine. {len(cards)} evolutions actives enregistrees dans {args.out}")
    conn.close()


if __name__ == "__main__":
    main()
