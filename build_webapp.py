"""
Assemble simulateur.html a partir du template + des donnees JSON.

A relancer a chaque fois que la base change (nouveaux joueurs, nouvelles
evolutions, stats mises a jour) pour rafraichir l'outil interactif.

Usage:
    python export_web_data.py --db fut27.db --out webapp_data.json   (a jour ?)
    python build_webapp.py
"""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", default="simulateur_template.html")
    parser.add_argument("--data", default="webapp_data.json")
    parser.add_argument("--out", default="simulateur.html")
    args = parser.parse_args()

    with open(args.template, encoding="utf-8") as f:
        template = f.read()
    with open(args.data, encoding="utf-8") as f:
        data = f.read()

    if "/*__DATA__*/" not in template:
        raise SystemExit(f"Placeholder /*__DATA__*/ introuvable dans {args.template}")

    html = template.replace("/*__DATA__*/", data)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"{args.out} genere ({len(html):,} caracteres)".replace(",", " "))


if __name__ == "__main__":
    main()
