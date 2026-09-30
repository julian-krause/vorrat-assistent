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
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import naehrwerte as nw
from . import text
from .bon import _SPALTEN, _produkt
from .text import normalisieren

# Wörter, die eine Variante statt des Grundprodukts kennzeichnen
VARIANTEN = {
    "erdbeer", "himbeer", "heidelbeer", "kirsch", "pfirsich", "mango", "vanille", "schoko", "kakao", "karamell", "caramel",
    "zitrone", "orange", "maracuja", "kokos", "haselnuss", "honig", "zimt", "aprikose", "blaubeer", "waldfrucht", "pistazie",
    "cookie", "keks", "riegel", "drink", "shake", "pudding", "dessert", "eis", "smoothie", "chips", "snack", "salat",
    "aufstrich", "sauce", "sosse", "dip", "mariniert", "paniert", "gefuellt", "fertig", "pommes", "sushi", "pizza", "burger",
}
# Füllwörter ohne Aussage über die Produktart
FUELLWOERTER = {
    "aus", "in", "im", "mit", "und", "vom", "von", "der", "die", "das", "fuer", "ohne", "je", "ca", "stueck", "stk", "bio",
    "klasse", "frisch", "frische", "bodenhaltung", "freilandhaltung", "freiland", "gross", "grosse", "xl", "packung", "schale",
    "beutel", "dose", "glas", "netz", "lose", "natur", "naturell", "pur", "klassisch", "original", "nativ", "natives", "extra",
    "vergine", "fein", "feine", "zart", "zarte", "mild", "milde", "premium", "beste", "wahl", "regional", "deutsche",
    "deutschland", "kg", "g", "ml", "l",
}


# Zutatennamen aus Rezepten, die im Shop anders heißen: zusätzliche Suchbegriffe
SYNONYME = {
    "ei": ["eier"], "eiklar": ["eiklar", "eiweiss"],
    "vollkornreis": ["naturreis", "vollkorn reis"], "roemersalat": ["romana", "romana salatherzen"],
    "nudeln": ["spaghetti", "penne", "fusilli", "farfalle", "tagliatelle", "makkaroni", "rigatoni", "linguine"],
    "blaubeeren": ["heidelbeeren"], "blaubeere": ["heidelbeere"],
    "hackfleisch": ["hack"], "rinderhack": ["rinderhackfleisch"],
    "magerquark": ["speisequark magerstufe"], "quark": ["speisequark"],
    "erdnussmus": ["erdnussbutter"], "walnuesse": ["walnusskerne"], "mandeln": ["mandelkerne"],
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
    # Quelle und Rang der Nährwerte (für ≈ im Plan und das Verzehr-Protokoll); unplausible Werte nicht verwenden
    werte = {"kcal": p.get("kcal_100"), "protein": p.get("protein_100"), "fett": p.get("fett_100"), "kh": p.get("kh_100"),
             "ballaststoffe": p.get("ballaststoffe_100")}
    q = nw.REWE_QUELLE.get(p.get("naehrwerte_quelle") or "")
    if q and nw.plausibel(werte)[0]:
        p["nw_quelle"], p["nw_rang"] = q, nw.RANG[q]
    else:
        p["nw_quelle"] = p["nw_rang"] = None
        for k in ("kcal_100", "protein_100", "fett_100", "kh_100"):
            p[k] = None
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
    for r in con.execute(f"SELECT {_SPALTEN} FROM rewe_products p WHERE p.suchtext LIKE %s AND {_AKTUELL} LIMIT 500",
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
    # Schreibvarianten/Synonyme aus der Tabelle (Brokkoli ↔ Broccoli, Parmesan ↔ Parmigiano, Hähnchen ↔ Huhn) zusätzlich zu den Rezept-Synonymen
    for begriff in list(dict.fromkeys(_suchbegriffe(kern) + text.varianten(con, kern))):
        for k in _wortsuche(con, begriff):
            wortsuche.setdefault(k[3]["rewe_product_id"], k)
    sortiert = sorted(wortsuche.values(), key=lambda k: k[:3])
    liste = [k[3] for k in sortiert[:anzahl - 2]]
    # Ähnlichkeitssuche ergänzt Schreibvarianten („Walnüsse“ -> „Walnusskerne“), ebenfalls ohne Varianten
    gesehen = {p["rewe_product_id"] for p in liste}
    for r in con.execute(f"""SELECT {_SPALTEN} FROM rewe_products p WHERE {_AKTUELL}
                             AND similarity(p.suchtext, norm_text(%s)) > 0.25
                             ORDER BY similarity(p.suchtext, norm_text(%s)) DESC LIMIT 6""", (kern, kern)):
        p = _anreichern(_produkt(r))
        extra = [w for w in _woerter(p["name"]) if not any(g in w or w in g for g in gesucht)]
        if p["rewe_product_id"] in gesehen or len(liste) >= anzahl or _ist_variante(extra, gesucht):
            continue
        liste.append(p)
        gesehen.add(p["rewe_product_id"])
    return liste


def zutaten_kandidaten(con, namen: list[str]) -> dict:
    return {name: kandidaten(con, name) for name in dict.fromkeys(n for n in namen if n and str(n).strip())}


# --- Vorgaben des Nutzers: Tagesziel, Mahlzeiten, „restlicher Tag“, Ausschlüsse ----------------------------------------------
# Nur was nicht übergeben wird, kommt aus dem Profil. Alles hier wird im Code hart eingehalten; die KI bekommt die Vorgaben
# zusätzlich im Prompt, begrenzt damit aber weder die Skalierung noch die Ausschlüsse.

# Standardverteilung des Tagesziels auf die Mahlzeiten (Summe = 1) je Anzahl Mahlzeiten pro Tag
VERTEILUNG = {
    1: [("Mittag", 1.0)],
    2: [("Frühstück", 0.45), ("Abend", 0.55)],
    3: [("Frühstück", 0.30), ("Mittag", 0.35), ("Abend", 0.35)],
    4: [("Frühstück", 0.25), ("Mittag", 0.30), ("Abend", 0.30), ("Snack", 0.15)],
    5: [("Frühstück", 0.22), ("Mittag", 0.28), ("Abend", 0.28), ("Snack", 0.11), ("Snack 2", 0.11)],
}
# Gewichte, wenn der Nutzer Mahlzeiten nennt (werden auf die genannten normiert) und Uhrzeit (Stunde, Minute), bis zu der sie „dran“ sind
GEWICHT = {"fruehstueck": 0.25, "mittag": 0.35, "abend": 0.35, "snack": 0.15, "snack 2": 0.10}
ENDE = {"fruehstueck": (10, 30), "mittag": (14, 30), "snack": (16, 30), "abend": (21, 0), "snack 2": (22, 0)}
NAME = {"fruehstueck": "Frühstück", "mittag": "Mittag", "abend": "Abend", "snack": "Snack", "snack 2": "Snack 2"}
# Bei einer bloßen Anzahl („2 Mahlzeiten“): bevorzugt Mittag und Abend, dann Frühstück, dann Snacks
PRIORITAET = ["mittag", "abend", "fruehstueck", "snack", "snack 2"]
CHRONOLOGIE = ["fruehstueck", "mittag", "snack", "abend", "snack 2"]
_ALIAS = {"fruhstuck": "fruehstueck", "fruehstueck": "fruehstueck", "breakfast": "fruehstueck", "mittagessen": "mittag", "mittag": "mittag",
          "lunch": "mittag", "abendessen": "abend", "abend": "abend", "dinner": "abend", "snack": "snack", "snacks": "snack",
          "snack 2": "snack 2", "zwischenmahlzeit": "snack", "zwischenmahlzeiten": "snack"}


def _mahlzeiten_lesen(wert) -> tuple[int | None, list[str]]:
    """„2“, 2, „Mittag, Abend“, ["Mittag","Abend"] oder JSON-Liste -> (Anzahl, Namen)."""
    if wert is None or wert == "":
        return None, []
    if isinstance(wert, (int, float)):
        return int(wert), []
    if isinstance(wert, str):
        w = wert.strip()
        if w.startswith("["):
            import json
            try:
                wert = json.loads(w)
            except ValueError:
                wert = [w]
        elif re.fullmatch(r"\d+", w):
            return int(w), []
        else:
            wert = [x for x in re.split(r"[,;/]| und ", w) if x.strip()]
    namen = []
    for x in wert:
        k = _ALIAS.get(normalisieren(str(x)))
        if k and k not in namen:
            namen.append(k)
    return None, namen


def _zahl(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and v > 0 else 0.0


def bereits_gegessen(con, tag: date, grocy_verbrauch: list[dict] | None = None) -> dict:
    """Heute Gegessenes: Verzehr-Protokoll (ohne Korrekturen) plus Grocy-Ausbuchungen, die der 5-Minuten-Abgleich noch nicht übernommen hat
    (Verbrauch, nicht weggeworfen, nicht rückgängig, noch nicht im Protokoll)."""
    z = con.execute("""SELECT coalesce(sum(kcal), 0), coalesce(sum(protein), 0), coalesce(sum(fett), 0), coalesce(sum(kh), 0), count(*)
                       FROM verzehr WHERE NOT ignoriert AND (zeitpunkt AT TIME ZONE 'Europe/Berlin')::date = %s""", (tag,)).fetchone()
    summe = {"kcal": float(z[0]), "p": float(z[1]), "f": float(z[2]), "kh": float(z[3])}
    protokoll, offen, unbekannt = int(z[4]), 0, []
    bekannt = {r[0] for r in con.execute("SELECT grocy_log_id FROM verzehr WHERE grocy_log_id IS NOT NULL")}
    for l in grocy_verbrauch or []:
        if not l or l.get("transaction_type") != "consume" or int(l.get("undone") or 0) == 1 or int(l.get("spoiled") or 0) == 1:
            continue
        if l.get("id") in bekannt or str(l.get("row_created_timestamp") or "")[:10] != tag.isoformat():
            continue
        n = con.execute("SELECT name, einheit, kcal_100, protein_100, fett_100, kh_100, gramm_pro_stk FROM vorrat_naehrwerte WHERE grocy_product_id = %s",
                        (l.get("product_id"),)).fetchone()
        menge = abs(_zahl(l.get("amount")))
        if not n or n[2] is None or not menge:
            unbekannt.append(l.get("product_id"))
            continue
        gramm = menge if n[1] in ("g", "ml") else menge * float(n[6]) if n[6] else None
        if gramm is None:
            unbekannt.append(l.get("product_id"))
            continue
        for k, v in zip(("kcal", "p", "f", "kh"), n[2:6]):
            summe[k] += float(v or 0) * gramm / 100
        offen += 1
    return {**{k: round(v, 1) for k, v in summe.items()}, "eintraege": protokoll, "grocy_offen": offen, "ohne_werte": len(unbekannt)}


def vorgaben(con, profil: dict, kcal_ziel=None, mahlzeiten=None, restlicher_tag: bool = False, ausschluesse=None,
             ziel_protein=None, ziel_fett=None, ziel_kh=None, jetzt: datetime | None = None, grocy_verbrauch: list[dict] | None = None) -> dict:
    """Effektive Ziele und Mahlzeiten für einen Tag. Übergebene Werte gewinnen, sonst gilt das Profil.
    restlicher_tag: Tagesziel minus bereits Gegessenes (Protokoll + noch nicht übernommene Grocy-Ausbuchungen),
    vergangene Mahlzeiten entfallen, der Rest wird auf die verbleibenden Mahlzeiten verteilt."""
    jetzt = jetzt or datetime.now(ZoneInfo("Europe/Berlin"))
    hinweise: list[str] = []
    pk = _zahl(profil.get("kcal"))
    tag_kcal = _zahl(kcal_ziel) or pk or 2000.0
    if not _zahl(kcal_ziel) and not pk:
        hinweise.append("Keine Ziele im Profil, Standard 2000 kcal.")
    # Makros: übergeben > Profil (skaliert auf das Tagesziel) > Standardanteile
    basis = tag_kcal / pk if pk else 1.0
    p = _zahl(ziel_protein) or (_zahl(profil.get("protein_g")) * basis if _zahl(profil.get("protein_g")) else tag_kcal * 0.30 / 4)
    f = _zahl(ziel_fett) or (_zahl(profil.get("fett_g")) * basis if _zahl(profil.get("fett_g")) else tag_kcal * 0.28 / 9)
    kh = _zahl(ziel_kh) or (_zahl(profil.get("kh_g")) * basis if _zahl(profil.get("kh_g")) else max(0.0, tag_kcal - p * 4 - f * 9) / 4)
    ziel = {"kcal": round(tag_kcal), "p": round(p), "f": round(f), "kh": round(kh)}

    anzahl, namen = _mahlzeiten_lesen(mahlzeiten)
    profil_anzahl = max(1, min(5, int(round(_zahl(profil.get("mahlzeiten_pro_tag")))) or 3))
    layout = lambda n: [(_ALIAS[normalisieren(x)], a) for x, a in VERTEILUNG[max(1, min(5, n))]]      # noqa: E731
    noch_dran = lambda k: not restlicher_tag or (jetzt.hour, jetzt.minute) < ENDE[k]                   # noqa: E731
    gewichte: dict[str, float]
    if namen:                                            # ausdrücklich genannte Mahlzeiten
        auswahl = list(namen)
        gewichte = {k: GEWICHT[k] for k in auswahl}
    elif anzahl:                                         # nur eine Anzahl: bevorzugt Mittag/Abend, bei „restlicher Tag“ nur, was noch ansteht
        auswahl = [k for k in (PRIORITAET if restlicher_tag else [k for k, _ in layout(anzahl)]) if noch_dran(k)][:max(1, min(5, anzahl))]
        gewichte = dict(layout(len(auswahl))) if not restlicher_tag and len(auswahl) in VERTEILUNG else {k: GEWICHT[k] for k in auswahl}
    else:                                                # Standard aus dem Profil
        basis_layout = layout(profil_anzahl)
        auswahl = [k for k, _ in basis_layout if noch_dran(k)]
        gewichte = dict(basis_layout)
    if restlicher_tag:
        vorbei = [k for k in (namen or []) if not noch_dran(k)] or ([k for k, _ in layout(profil_anzahl) if not noch_dran(k)] if not namen and not anzahl else [])
        if vorbei:
            hinweise.append("Schon vorbei, entfallen: " + ", ".join(NAME[k] for k in vorbei) + ".")
        auswahl = [k for k in auswahl if noch_dran(k)]
    auswahl = sorted(dict.fromkeys(auswahl), key=CHRONOLOGIE.index)

    bereits = {"kcal": 0.0, "p": 0.0, "f": 0.0, "kh": 0.0, "eintraege": 0, "grocy_offen": 0, "ohne_werte": 0}
    if restlicher_tag:
        bereits = bereits_gegessen(con, jetzt.date(), grocy_verbrauch)
        if bereits["ohne_werte"]:
            hinweise.append(f"{bereits['ohne_werte']} Ausbuchung(en) ohne Nährwerte nicht mitgezählt.")
    rest = {k: max(0.0, ziel[k] - bereits[k]) for k in ("kcal", "p", "f", "kh")}
    if restlicher_tag and rest["kcal"] < 50:
        hinweise.append("Das Tagesziel ist schon erreicht, es bleibt nichts zu verplanen.")
        auswahl = []
    summe_g = sum(gewichte.get(k, GEWICHT[k]) for k in auswahl) or 1.0
    slots = []
    for k in auswahl:
        anteil = gewichte.get(k, GEWICHT[k]) / summe_g
        slots.append({"name": NAME[k], "anteil": round(anteil, 4), "kcal": round(rest["kcal"] * anteil), "p": round(rest["p"] * anteil),
                      "f": round(rest["f"] * anteil), "kh": round(rest["kh"] * anteil)})
    # Rundung so ausgleichen, dass die kcal der Mahlzeiten genau das Ziel ergeben
    if slots and round(rest["kcal"]) != sum(s["kcal"] for s in slots):
        slots[-1]["kcal"] += round(rest["kcal"]) - sum(s["kcal"] for s in slots)
    return {"ziel": ziel, "bereits": bereits, "rest": {k: round(v) for k, v in rest.items()}, "slots": slots,
            "restlicher_tag": bool(restlicher_tag), "ausschluesse": ausschluss_begriffe(con, ausschluesse), "hinweise": hinweise,
            "ziel_text": ("Ziel für den Rest des Tages: " if restlicher_tag else "Ziel pro Tag: ") + f"{round(rest['kcal'])} kcal · P {round(rest['p'])} g · F {round(rest['f'])} g · KH {round(rest['kh'])} g"
                         + (f" (Tagesziel {ziel['kcal']} kcal, schon gegessen {round(bereits['kcal'])} kcal)" if restlicher_tag else "")}


# --- Ausschlüsse ---------------------------------------------------------------------------------------------------------------

def ausschluss_liste(wert) -> list[str]:
    if wert is None:
        return []
    if isinstance(wert, str):
        wert = re.split(r"[,;\n]| und ", wert)
    return [w.strip() for w in wert if isinstance(w, str) and w.strip()]


def ausschluss_begriffe(con, ausschluesse) -> list[str]:
    """Ausgeschlossene Zutaten als normalisierte Suchbegriffe inkl. Schreibvarianten (Synonyme) und Mitgliedern von Oberbegriffen
    („Nüsse“ -> Walnuss, Mandel, …)."""
    begriffe: list[str] = []
    for a in ausschluss_liste(ausschluesse):
        n = normalisieren(a)
        gefunden = [n] + (text.varianten(con, a) or [])
        for r in con.execute("SELECT mitglied FROM ausschluss_oberbegriffe WHERE oberbegriff = ANY(%s)", ([n, text.skelett(n)],)):
            gefunden.append(r[0])
        for g in gefunden:
            if g and g not in begriffe:
                begriffe.append(g)
    return begriffe


# Pflanzliche Ersatzprodukte sind keine Milchprodukte/Nüsse usw. („Hafermilch“, „Erdnussbutter“ bei „ohne Butter“ – Nüsse bleiben Nüsse)
_PFLANZLICH = ("hafer", "soja", "mandel", "kokos", "reis", "erdnuss", "cashew", "pflanzlich", "vegan", "sonnenblumen", "dinkeldrink")
_MILCHWORTE = {"milch", "butter", "sahne", "joghurt", "kaese", "quark", "skyr", "frischkaese", "schmand", "kefir"}


def ausschluss_treffer(begriffe: list[str], text_: str) -> str | None:
    """Erster ausgeschlossener Begriff, der in der Zutat steckt (Wort, Kompositum oder Mehrzahl), sonst None.
    Kurze Begriffe (bis 3 Buchstaben, z.B. „ei“) gelten nur als ganzes Wort. Gleiche Logik wie in n8n (Planer „Antwort auswerten“)."""
    norm = normalisieren(text_)
    woerter = norm.split()
    sk = [text.skelett(w) for w in woerter]
    for b in begriffe:
        bs = text.skelett(b)
        if len(bs) <= 3:
            if b in woerter:
                return b
            continue
        stamm = bs[: max(4, len(bs) - 2)] if len(bs) >= 6 else bs
        for w in sk:
            if stamm in w and not (b in _MILCHWORTE and any(w.startswith(pf) or pf in w for pf in _PFLANZLICH)):
                return b
    return None
