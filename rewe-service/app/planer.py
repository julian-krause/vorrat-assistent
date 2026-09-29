"""Zutaten aus dem Wochenplan den REWE-Produkten zuordnen (Nährwerte, Packungsgröße, Preis, Angebot).

Zweistufig: Dieser Dienst liefert pro Zutat bis zu 8 Kandidaten (Wortsuche + Ähnlichkeitssuche), das Sprachmodell
im n8n-Planer wählt daraus das passende Grundprodukt (Regeln allein verwechseln z.B. „Olivenöl“ mit „Feta in Olivenöl“).
Der erste Kandidat ist die beste Wahl nach Regeln und dient als Rückfall, wenn die Modellwahl ausfällt.

Regeln für die Kandidaten-Reihenfolge:
- Wortsuche: jedes Wort der Zutat muss (auch als Teil eines Kompositums) im Produktnamen vorkommen
- Varianten mit Geschmack/Zusatz („Erdbeere“, „mit …“, „Riegel“), die in der Zutat nicht vorkommen, fallen raus
- möglichst wenige Zusatzwörter (Marke und Füllwörter wie „aus“, „Stück“, „Bio“ zählen nicht), dann Preis pro kg/l
- Ähnlichkeitssuche (pg_trgm) ergänzt z.B. „Walnüsse“ -> „Walnusskerne“
- nur Produkte, die im letzten Crawl noch gelistet waren
"""

from __future__ import annotations

import re
from datetime import date

from .bon import _SPALTEN, _produkt, normalisieren

# Wörter, die eine Variante statt des Grundprodukts kennzeichnen
VARIANTEN = {
    "erdbeer", "himbeer", "heidelbeer", "kirsch", "pfirsich", "mango", "vanille", "schoko", "kakao", "karamell", "caramel",
    "zitrone", "orange", "maracuja", "kokos", "haselnuss", "honig", "zimt", "aprikose", "blaubeer", "waldfrucht", "pistazie",
    "cookie", "keks", "riegel", "drink", "shake", "pudding", "dessert", "eis", "smoothie", "chips", "snack", "salat",
    "aufstrich", "sauce", "sosse", "dip", "mariniert", "paniert", "gefullt", "fertig", "pommes", "sushi", "pizza", "burger",
}
# Füllwörter ohne Aussage über die Produktart
FUELLWOERTER = {
    "aus", "in", "im", "mit", "und", "vom", "von", "der", "die", "das", "fur", "ohne", "je", "ca", "stuck", "stk", "bio",
    "klasse", "frisch", "frische", "bodenhaltung", "freilandhaltung", "freiland", "gross", "grosse", "xl", "packung", "schale",
    "beutel", "dose", "glas", "netz", "lose", "natur", "naturell", "pur", "klassisch", "original", "nativ", "natives", "extra",
    "vergine", "fein", "feine", "zart", "zarte", "mild", "milde", "premium", "beste", "wahl", "regional", "deutsche",
    "deutschland", "kg", "g", "ml", "l",
}


# Zutatennamen aus Rezepten, die im Shop anders heißen: zusätzliche Suchbegriffe
SYNONYME = {
    "ei": ["eier"], "eiklar": ["eiklar", "eiweiss"],
    "vollkornreis": ["naturreis", "vollkorn reis"], "romersalat": ["romana", "romana salatherzen"],
    "nudeln": ["spaghetti", "penne", "fusilli", "farfalle", "tagliatelle", "makkaroni", "rigatoni", "linguine"],
    "blaubeeren": ["heidelbeeren"], "blaubeere": ["heidelbeere"],
    "hackfleisch": ["hack"], "rinderhack": ["rinderhackfleisch"],
    "magerquark": ["speisequark magerstufe"], "quark": ["speisequark"],
    "erdnussmus": ["erdnussbutter"], "walnusse": ["walnusskerne"], "mandeln": ["mandelkerne"],
    "haferdrink": ["haferdrink", "hafer drink"], "tomaten passiert": ["passata"], "passierte tomaten": ["passata"],
}


def _suchbegriffe(zutat: str) -> list[str]:
    """Zutat plus Synonyme; bei Komposita wie „Vollkornnudeln“ auch „Vollkorn Spaghetti“ usw.

    Kurze Synonyme (bis 3 Buchstaben, z.B. „ei“) greifen nur als ganzes Wort, längere auch in Komposita."""
    norm = normalisieren(zutat)
    woerter = norm.split()
    begriffe = [zutat]
    for wort, ersatz in SYNONYME.items():
        if len(wort) <= 3:
            if wort in woerter:
                begriffe += [" ".join(e if w == wort else w for w in woerter) for e in ersatz]
        elif wort in norm:
            begriffe += [re.sub(r"\s+", " ", norm.replace(wort, " " + e + " ")).strip() for e in ersatz]
    return list(dict.fromkeys(begriffe))


def _woerter(text: str) -> list[str]:
    return [w for w in normalisieren(text).split() if len(w) >= 2 and not re.fullmatch(r"\d+([gml]|kg|l|er|x)?|\d+x\d+[gml]*", w)]


def _preis(p: dict) -> tuple[float | None, bool]:
    angebot = p.get("angebotspreis") is not None and (p.get("angebot_bis") or "") >= date.today().isoformat()
    return (p["angebotspreis"] if angebot else p["price"]), angebot


def _anreichern(p: dict) -> dict:
    preis, angebot = _preis(p)
    p["preis_aktuell"] = preis
    p["im_angebot"] = angebot
    p["preis_pro_kg"] = round(preis / p["size_value"] * 1000, 2) if preis and p.get("size_value") and p.get("size_unit") in ("g", "ml") else None
    return p


_AKTUELL = "p.last_seen >= (SELECT max(last_seen) FROM rewe_products) - interval '40 days'"


def _ist_variante(extra: list[str], gesucht: list[str]) -> bool:
    """True, wenn ein Zusatzwort eine Geschmacks-/Produktvariante ist, die in der Zutat nicht vorkommt."""
    for w in extra:
        treffer = [v for v in VARIANTEN if v in w]
        if treffer and not any(v in g for v in treffer for g in gesucht):
            return True
    return False


def _wortsuche(con, begriff: str) -> list[tuple]:
    gesucht = _woerter(begriff)
    if not gesucht:
        return []
    laengstes = max(gesucht, key=len)
    treffer = []
    for r in con.execute(f"SELECT {_SPALTEN} FROM rewe_products p WHERE translate(lower(p.name), 'äöüß', 'aous') LIKE %s AND {_AKTUELL} LIMIT 500",
                         ("%" + laengstes + "%",)):
        p = _anreichern(_produkt(r))
        name_woerter = _woerter(p["name"])
        zusammen = "".join(name_woerter)
        # kurze Wörter („ei“) nur als ganzes Wort, längere auch in Komposita („Hähnchenbrustfilet“)
        if not all((w in name_woerter) if len(w) <= 3 else (w in zusammen) for w in gesucht):
            continue
        extra = [w for w in name_woerter if not any(g in w or w in g for g in gesucht)]
        if _ist_variante(extra, gesucht):
            continue
        marke = set(_woerter(p["brand"] or ""))
        extra = [w for w in extra if w not in marke and w not in FUELLWOERTER]
        treffer.append((len(extra), p["preis_pro_kg"] if p["preis_pro_kg"] is not None else 1e9, len(p["name"]), p))
    return treffer


def kandidaten(con, zutat: str, anzahl: int = 8) -> list[dict]:
    # Klammerzusätze („Garnelen (roh, geschält)“, „Kichererbsen (Dose)“) sind Hinweise für die Modellwahl, nicht für die Suche
    kern = re.sub(r"\([^)]*\)", " ", zutat).strip() or zutat
    gesucht = _woerter(kern)
    if not gesucht:
        return []
    wortsuche = {}
    for begriff in _suchbegriffe(kern):
        for k in _wortsuche(con, begriff):
            wortsuche.setdefault(k[3]["rewe_product_id"], k)
    sortiert = sorted(wortsuche.values(), key=lambda k: k[:3])
    liste = [k[3] for k in sortiert[:anzahl - 2]]
    # Ähnlichkeitssuche ergänzt Schreibvarianten („Walnüsse“ -> „Walnusskerne“), ebenfalls ohne Varianten
    gesehen = {p["rewe_product_id"] for p in liste}
    for r in con.execute(f"""SELECT {_SPALTEN} FROM rewe_products p WHERE {_AKTUELL}
                             AND similarity(lower(p.name), lower(%s)) > 0.25
                             ORDER BY similarity(lower(p.name), lower(%s)) DESC LIMIT 6""", (kern, kern)):
        p = _anreichern(_produkt(r))
        extra = [w for w in _woerter(p["name"]) if not any(g in w or w in g for g in gesucht)]
        if p["rewe_product_id"] in gesehen or len(liste) >= anzahl or _ist_variante(extra, gesucht):
            continue
        liste.append(p)
        gesehen.add(p["rewe_product_id"])
    return liste


def zutaten_kandidaten(con, namen: list[str]) -> dict:
    return {name: kandidaten(con, name) for name in dict.fromkeys(n for n in namen if n and str(n).strip())}
