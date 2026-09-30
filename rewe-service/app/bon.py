"""REWE-eBon: Zeilen auslesen und den Produkten aus der REWE-Tabelle zuordnen.

Der eBon enthält pro Zeile nur einen abgekürzten Kassentext („HAHN.LYONER“), den Betrag und die Steuerklasse,
bei Mehrfachkauf „2 Stk x 1,19“ und bei Gewichtsware „0,512 kg x 11,70 EUR/kg“ – keinen Barcode.
Zuordnung pro Zeile:
  1. Lerntabelle bon_zuordnung (Kassentext -> Produkt, aus früheren sicheren oder bestätigten Zuordnungen)
  2. Kandidaten mit exakt passendem Preis (aktueller Preis, Angebot oder Preisverlauf um das Kaufdatum;
     bei Gewichtsware der Preis pro kg)
  3. Textabgleich: jedes Wort des Kassentexts muss (als Abkürzung) im Produktnamen vorkommen
Eindeutiger Treffer -> „sicher“, sonst „unsicher“ mit bis zu 3 Kandidaten zur Rückfrage.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

from . import text
from .text import normalisieren

_BETRAG = r"-?\d+,\d{2}"
_ZEILE = re.compile(rf"^\s*(?P<text>\S.*?)\s+(?P<betrag>{_BETRAG})\s+(?P<mwst>[A-Z])(?:\s*\*)?\s*$")
_STUECK = re.compile(r"^\s*(?P<anzahl>\d+)\s*Stk\s*x\s*(?P<preis>\d+,\d{2})\s*$", re.I)
_GEWICHT = re.compile(r"^\s*(?P<kg>\d+,\d{1,3})\s*kg\s*x\s*(?P<preis>\d+,\d{2})\s*(?:EUR|€)\s*/\s*kg\s*$", re.I)
_DATUM = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_MARKT = re.compile(r"Markt:\s*(\d+)")
_IGNORIEREN = re.compile(r"^(pfand|leergut|rabatt|coupon|bonus|payback|summe|zwischensumme|geg\.|rückgeld|mwst)", re.I)
# Wasser wird nie erfasst (Mineral-, Tafel-, Heil-, Quell-, Sprudelwasser), wohl aber Wassermelone oder Kokoswasser
_WASSER = re.compile(r"wasser|sprudel", re.I)
_KEIN_WASSER = re.compile(r"melone|kokos|rosen|orangenbl", re.I)


def ist_wasser(text: str) -> bool:
    t = normalisieren(text)
    return bool(_WASSER.search(t)) and not _KEIN_WASSER.search(t)


# Marken, die (fast) nur Wasser verkaufen: „RHEINFELS KLASSI“ ist Wasser, auch wenn die Zeile nicht sicher zugeordnet wird
_WASSER_MARKEN = re.compile(r"\b(rheinfels|gerolst\w*|volvic|evian|apollinaris|selters|vilsa|fachingen|lauretana|vittel|contrex|badoit|perrier|pellegrino|adelholzener|teinacher|hensel|lichtenauer|harzer grauhof|bad vilbeler|gaensefurther|christinen|romina)\b")
_KEIN_WASSER_MARKE = re.compile(r"schorle|limo|saft|tee|fruit|frucht|cola|drink|near|aroma|geschmack|zitrone|apfel|orange")


def ist_wasser_marke(text: str) -> bool:
    t = normalisieren(text)
    return bool(_WASSER_MARKEN.search(t)) and not _KEIN_WASSER_MARKE.search(t)


# Der Kassentext verrät Wasser oft nicht („RHEINFELS KLASSI“), das zugeordnete REWE-Produkt schon
_WASSER_PRODUKT = re.compile(r"\b(mineral|tafel|heil|quell)wasser\b", re.I)


def ist_wasser_produkt(con, rewe_product_id: str | None) -> bool:
    if not rewe_product_id:
        return False
    z = con.execute("SELECT name, category, description FROM rewe_products WHERE rewe_product_id = %s", (rewe_product_id,)).fetchone()
    if not z:
        return False
    name, kategorie, beschreibung = z
    if ist_wasser(name or ""):
        return True
    return (kategorie or "") == "Getränke" and bool(_WASSER_PRODUKT.search(beschreibung or ""))
TOLERANZ_TAGE = 45
MIN_RANG = 0.5          # darunter wird ein Kandidat nicht mehr vorgeschlagen


def _zahl(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


_NUR_BETRAG = re.compile(rf"^\s*{_BETRAG}\s+[A-Z](?:\s*\*)?\s*$")


def _zeilen_zusammenfuegen(text: str) -> list[str]:
    """Manche PDF-Extraktoren trennen Kassentext und Betrag auf zwei Zeilen – wieder zusammenfügen."""
    aus = []
    for zeile in str(text or "").splitlines():
        if _NUR_BETRAG.match(zeile) and aus and aus[-1].strip() and not _ZEILE.match(aus[-1]):
            aus[-1] = aus[-1].rstrip() + " " + zeile.strip()
        else:
            aus.append(zeile)
    return aus


def bon_lesen(text: str) -> dict:
    """PDF-Text eines REWE-eBons -> Kaufdatum, Marktnummer und Artikelzeilen."""
    zeilen = []
    kopf_vorbei = False
    for roh in _zeilen_zusammenfuegen(text):
        if re.match(r"^\s*-{5,}", roh) or re.match(r"^\s*SUMME\b", roh, re.I):
            if zeilen:
                break
            continue
        if roh.strip() == "EUR":
            kopf_vorbei = True
            continue
        m = _STUECK.match(roh)
        if m and zeilen:
            zeilen[-1]["anzahl"] = int(m.group("anzahl"))
            zeilen[-1]["einzelpreis"] = _zahl(m.group("preis"))
            continue
        m = _GEWICHT.match(roh)
        if m and zeilen:
            zeilen[-1]["gewicht_kg"] = _zahl(m.group("kg"))
            zeilen[-1]["kilopreis"] = _zahl(m.group("preis"))
            zeilen[-1]["einzelpreis"] = None
            continue
        m = _ZEILE.match(roh)
        if not m:
            continue
        kopf_vorbei = True
        text_zeile = m.group("text").strip()
        betrag = _zahl(m.group("betrag"))
        zeilen.append({"bon_text": text_zeile, "betrag": betrag, "mwst": m.group("mwst"), "anzahl": 1,
                       "einzelpreis": betrag, "gewicht_kg": None, "kilopreis": None,
                       "ignorieren": betrag <= 0 or bool(_IGNORIEREN.match(text_zeile)) or ist_wasser(text_zeile)})
    datum = None
    m = re.search(r"Datum:\s*(\d{2}\.\d{2}\.\d{4})", text or "") or _DATUM.search(text or "")
    if m:
        datum = datetime.strptime(m.group(1) if m.lastindex == 1 else ".".join(m.groups()), "%d.%m.%Y").date()
    markt = _MARKT.search(text or "")
    return {"datum": datum, "markt": markt.group(1) if markt else None, "zeilen": zeilen, "kopf_erkannt": kopf_vorbei}


_ARTIKELWOERTER = {"die", "der", "das", "den", "dem", "ein", "eine", "und", "mit", "von", "aus", "in", "im", "vom", "zum", "zur"}


def _kassenwoerter(bon_text: str) -> list[tuple[str, bool]]:
    """Wörter des Kassentexts mit Kennzeichen, ob sie mit Punkt abgekürzt sind („HAHN.“ -> abgekürzt). Artikelwörter zählen nicht."""
    woerter = []
    for m in re.finditer(r"([^\W_]+)(\.)?", str(bon_text or "")):
        w = normalisieren(m.group(1))
        if len(w) >= 2 and not w.isdigit() and w not in _ARTIKELWOERTER:
            woerter.append((w, bool(m.group(2))))
    return woerter


def _wort_passt(wort: str, abgekuerzt: bool, name: str, zusammen: str) -> bool:
    if _wort_passt_roh(wort, abgekuerzt, name, zusammen):
        return True
    # „HAHN.“ ist Hähnchen (haehnchen): zusätzlich ohne Umlaut-Auflösung vergleichen
    w2, n2, z2 = text.skelett(wort), text.skelett(name), text.skelett(zusammen)
    return (w2 != wort or n2 != name) and _wort_passt_roh(w2, abgekuerzt, n2, z2)


def _wort_passt_roh(wort: str, abgekuerzt: bool, name: str, zusammen: str) -> bool:
    if len(wort) < 3:
        # „SP.“ (mit Punkt abgekürzt) = Anfang eines Wortes („Spitzpaprika“ -> spitz…), ohne Punkt nur ganzes Wort
        return any(w.startswith(wort) for w in name.split()) if abgekuerzt else wort in name.split()
    start = zusammen.find(wort)
    while start >= 0:
        rest = zusammen[start + len(wort):]
        # „STEINOFENBROT“ ist kein Steinofenbrötchen: ausgeschriebene Wörter nicht in Verkleinerungsformen verlängern
        if abgekuerzt or not rest.startswith(("chen", "lein")):
            return True
        start = zusammen.find(wort, start + 1)
    return False


def textwert(bon_text: str, produktname: str, marke: str | None = None) -> float:
    """Anteil der Kassentext-Wörter, die (auch abgekürzt oder in Komposita) im Produktnamen vorkommen."""
    woerter = _kassenwoerter(bon_text)
    if not woerter:
        return 0.0
    name = normalisieren(f"{marke or ''} {produktname}")
    zusammen = name.replace(" ", "")
    return sum(1 for w, abk in woerter if _wort_passt(w, abk, name, zusammen)) / len(woerter)


def _produkt(row) -> dict:
    keys = ("rewe_product_id", "name", "brand", "category", "size_value", "size_unit", "price", "price_per_kg_or_l",
            "angebotspreis", "angebot_bis", "ean", "kcal_100", "protein_100", "kh_100", "fett_100", "naehrwerte_quelle",
            "ballaststoffe_100", "naehrwert_verlauf_id", "grammage_raw")
    d = dict(zip(keys, row))
    for k in ("size_value", "price", "price_per_kg_or_l", "angebotspreis", "kcal_100", "protein_100", "kh_100", "fett_100",
              "ballaststoffe_100"):
        if d.get(k) is not None:
            d[k] = float(d[k])
    if d.get("angebot_bis"):
        d["angebot_bis"] = d["angebot_bis"].isoformat()
    return d


_SPALTEN = """p.rewe_product_id, p.name, p.brand, p.category, p.size_value, p.size_unit, p.price, p.price_per_kg_or_l,
              p.angebotspreis, p.angebot_bis, p.ean, p.kcal_100, p.protein_100, p.kh_100, p.fett_100, p.naehrwerte_quelle,
              p.ballaststoffe_100, p.naehrwert_verlauf_id, p.grammage_raw"""


def _preis_kandidaten(con, preis: Decimal, kaufdatum: date, pro_kg: bool, markt: str | None = None) -> list[dict]:
    von, bis = kaufdatum - timedelta(days=TOLERANZ_TAGE), kaufdatum + timedelta(days=TOLERANZ_TAGE)
    # bestätigte Bonpreise dieses Marktes (Einkaufsmarkt): beim nächsten Einkauf greift die Preiszuordnung auch bei abweichendem Katalogpreis
    bonpreis = """OR EXISTS (SELECT 1 FROM bon_preise b WHERE b.rewe_product_id = p.rewe_product_id AND b.markt = %(m)s AND b.{spalte} = %(p)s)"""
    if pro_kg:
        sql = f"""SELECT {_SPALTEN} FROM rewe_products p WHERE p.price_per_kg_or_l = %(p)s OR (p.size_unit = 'g' AND p.size_value = 1000 AND p.price = %(p)s)
                  OR replace((regexp_match(p.grammage_raw, '1 ?(?:kg|l) = (\\d+(?:,\\d+)?)'))[1], ',', '.')::numeric = %(p)s
                  {bonpreis.format(spalte='kilopreis')}"""
    else:
        sql = f"""SELECT {_SPALTEN} FROM rewe_products p
                  WHERE p.price = %(p)s
                     OR (p.angebotspreis = %(p)s AND p.angebot_bis >= %(d)s AND p.angebot_bis <= %(d)s + 7)
                     OR EXISTS (SELECT 1 FROM rewe_price_history h WHERE h.rewe_product_id = p.rewe_product_id
                                AND h.price = %(p)s AND h.crawled_at::date BETWEEN %(von)s AND %(bis)s)
                     {bonpreis.format(spalte='preis')}"""
    return [_produkt(r) for r in con.execute(sql, {"p": preis, "d": kaufdatum, "von": von, "bis": bis, "m": markt or ""})]


def bonpreis_merken(con, rewe_product_id: str, markt: str | None, zeile: dict) -> None:
    """Bestätigten Bonpreis pro Markt speichern (Ladenpreise weichen vom Katalogmarkt ab)."""
    if not markt:
        return
    con.execute("""INSERT INTO bon_preise (rewe_product_id, markt, preis, kilopreis, datum) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (rewe_product_id, markt) DO UPDATE SET preis = EXCLUDED.preis, kilopreis = EXCLUDED.kilopreis, datum = EXCLUDED.datum""",
                (rewe_product_id, markt, zeile.get("einzelpreis"), zeile.get("kilopreis"), zeile.get("datum") or date.today()))


# Merkmale, die ein Kandidat haben darf, wenn sie auf dem Bon stehen – sonst wird abgewertet (Geschmack/Verarbeitungsform)
_GESCHMACK = ("zitron", "pfirsich", "mango", "erdbeer", "himbeer", "kirsch", "vanille", "schoko", "karamell", "caramel", "heidelbeer",
              "blaubeer", "maracuja", "kokos", "haselnuss", "honig", "zimt", "aprikose", "waldfrucht", "pistazie", "ananas", "banane",
              "apfel", "orange", "holunder", "minze", "ingwer")
_VERARBEITUNG = ("saft", "shot", "drink", "fertig", "puree", "smoothie", "suppe", "eintopf", "pfanne", "salat", "pommes", "kroketten",
                 "knoedel", "puffer", "rosti", "gratin", "chips", "tee", "pulver", "sirup", "konzentrat", "aufstrich", "sauce", "sosse",
                 "pesto", "dip", "teig", "mix", "riegel", "snack", "bowl", "gericht", "menue", "paniert", "mariniert", "gefuellt", "kloesse",
                 "nuggets", "burger", "pizza", "pfanni", "mccain", "knorr", "maggi", "erasco", "fix", "gepoekelt", "gebacken", "gegrillt",
                 "gebraten", "frittiert", "ofengebacken", "hauchzart", "geschnetzelt")
# Kategorien, in denen Aufschnitt/Fertigware liegt: nur passend, wenn der Bon selbst danach klingt
_AUFSCHNITT_KATEGORIEN = {"Wurst & Aufschnitt"}
_TK_WORTE = ("tk", "tiefk", "tiefkuehl", "frost")
_AUFSCHNITT_WORTE = ("wurst", "salami", "lyoner", "schinken", "aufschnitt", "mortadella", "bierschinken", "mett", "leberwurst", "speck")
_FUELL = {"rewe", "ja", "bio", "beste", "wahl", "natur", "naturell", "frisch", "frische", "lose", "klasse", "stueck", "stk", "kg", "g",
          "ml", "l", "gross", "grosse", "mild", "milde", "fein", "feine", "feinen", "die", "der", "das", "und", "mit", "aus", "in",
          "im", "vom", "von", "regional", "deutschland", "extra", "premium", "original", "classic", "klassik", "klassisch", "pur"}
_ZAHLWORT = re.compile(r"^\d+(?:[a-z]+|x\d+[a-z]*)?$")


def _hat(wort_menge, stamm) -> bool:
    return any(w.startswith(stamm) for w in wort_menge)


def bewerten(zeile: dict, p: dict, katalog_score: float = 0.0) -> float:
    """Rangwert eines Kandidaten für eine Bonzeile. Textähnlichkeit zuerst; Preisnähe nur als kleiner Tiebreaker
    (Katalogmarkt und Einkaufsmarkt haben verschiedene Preise); abwerten bei Merkmalen, die nicht auf dem Bon stehen
    (Geschmack, Verarbeitungsform), aufwerten bei passenden Bon-Merkmalen (BIO, Eigenmarke)."""
    bon_w = set(normalisieren(zeile["bon_text"]).split())
    name_w = set(normalisieren(p["name"]).split())
    marke_w = set(normalisieren(p.get("brand") or "").split())
    score = max(textwert(zeile["bon_text"], p["name"], p.get("brand")), katalog_score)
    extra = {w for w in name_w if not any(b.startswith(w) or w.startswith(b) for b in bon_w if len(b) >= 3 or b == w)}
    extra = {w for w in extra if w not in _FUELL and not _ZAHLWORT.match(w)}
    abzug = 0.0
    verarbeitet = False
    for w in extra:
        if _hat({w}, "") and any(w.startswith(g) for g in _GESCHMACK):
            abzug += 0.25
        if any(w.startswith(v) for v in _VERARBEITUNG):
            abzug += 0.25
            verarbeitet = True
    if marke_w & set(_VERARBEITUNG):
        abzug += 0.25
        verarbeitet = True
    if p.get("category") in _AUFSCHNITT_KATEGORIEN and not any(w.startswith(a) for w in bon_w for a in _AUFSCHNITT_WORTE):
        abzug += 0.25
    if p.get("category") == "Tiefkühl" and not any(w.startswith(t) for w in bon_w for t in _TK_WORTE):
        abzug += 0.25            # Tiefkühlware nur vorschlagen, wenn der Bon danach klingt
    score -= min(abzug, 0.6)
    if "bio" in bon_w and ("bio" in name_w or "bio" in marke_w):
        score += 0.1
    if bon_w & {"ja", "rewe"} and marke_w & {"ja", "rewe"}:
        score += 0.05
    preis = zeile.get("kilopreis") if zeile.get("kilopreis") is not None else zeile.get("einzelpreis")
    p_katalog = p.get("price_per_kg_or_l") if zeile.get("kilopreis") is not None else p.get("price")
    if preis and p_katalog:
        rel = abs(float(p_katalog) - float(preis)) / float(preis)
        score += 0.04 * max(0.0, 1 - rel / 0.5)          # großzügige Toleranz, nur Tiebreaker
    if zeile.get("kilopreis") is not None:
        lose = (p.get("size_unit") == "g" and float(p.get("size_value") or 0) == 1000) or "lose" in name_w or "kg" in name_w
        score += 0.12 if lose else 0.0
        score -= 0.5 if verarbeitet else 0.0
    p["verarbeitet"] = verarbeitet
    p["merkmale_extra"] = abzug > 0
    return round(score - len(p["name"]) / 100000, 4)


def _de(zahl, stellen: int = 2) -> str:
    return f"{float(zahl):.{stellen}f}".replace(".", ",")


def zeile_text(zeile: dict) -> str:
    """Bonzeile lesbar für die Rückfrage – nie leere Klammern: „0,106 kg × 3,99 €/kg = 0,42 €“, „2 Stk × 1,19 €“, „1,29 €“."""
    betrag = zeile.get("betrag")
    if zeile.get("gewicht_kg") is not None and zeile.get("kilopreis") is not None:
        text_ = f"{_de(zeile['gewicht_kg'], 3)} kg × {_de(zeile['kilopreis'])} €/kg"
        return text_ + (f" = {_de(betrag)} €" if betrag is not None else "")
    if (zeile.get("anzahl") or 1) > 1 and zeile.get("einzelpreis") is not None:
        return f"{zeile['anzahl']} Stk × {_de(zeile['einzelpreis'])} €"
    preis = zeile.get("einzelpreis") if zeile.get("einzelpreis") is not None else betrag
    return f"{_de(preis)} €" if preis is not None else ""


def produkt_anzeige(p: dict) -> str:
    """Kandidat für Buttons: Name · Preis · €/kg bzw. €/l · Packungsgröße (nur, was bekannt ist)."""
    teile = [p["name"]]
    if p.get("price") is not None:
        teile.append(f"{_de(p['price'])} €")
    if p.get("price_per_kg_or_l") is not None:
        teile.append(f"{_de(p['price_per_kg_or_l'])} €/{'l' if p.get('size_unit') == 'ml' else 'kg'}")
    if p.get("size_value") and p.get("size_unit"):
        g = float(p["size_value"])
        teile.append(f"{g / 1000:g} {'l' if p['size_unit'] == 'ml' else 'kg'}" if g >= 1000 and p["size_unit"] in ("g", "ml")
                     else f"{g:g} {p['size_unit'] if p['size_unit'] != 'Stück' else 'Stk'}")
    return " · ".join(teile)


def _kandidaten_laden(con, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    return {r[0]: _produkt(r) for r in con.execute(f"SELECT {_SPALTEN} FROM rewe_products p WHERE p.rewe_product_id = ANY(%s)", (ids,))}


def _text_kandidaten(con, bon_text: str, zeile: dict | None = None, mindest: float = 0.5) -> list[dict]:
    """Produkte, die zum Kassentext passen (abgekürzte Wörter, Komposita, Schreibvarianten und Synonyme), nach bewerten() sortiert."""
    zeile = zeile or {"bon_text": bon_text}
    woerter = sorted((w for w, _ in _kassenwoerter(bon_text) if len(w) >= 4), key=len, reverse=True)
    ids: dict[str, float] = {}
    if woerter:
        for r in con.execute("SELECT p.rewe_product_id FROM rewe_products p WHERE p.suchtext LIKE %s LIMIT 300", ("%" + woerter[0] + "%",)):
            ids[r[0]] = 0.0
    anfrage = " ".join(w for w, _ in _kassenwoerter(bon_text))
    for t in text.suche(con, anfrage, 0.4, 40):
        ids[t["rewe_product_id"]] = max(ids.get(t["rewe_product_id"], 0.0), t["score"])
    kandidaten = []
    for pid, p in _kandidaten_laden(con, list(ids)).items():
        p["textwert"] = round(textwert(bon_text, p["name"], p["brand"]), 2)
        if p["textwert"] < mindest and ids[pid] < 0.75:          # Trigramm-Treffer allein nur bei starker Ähnlichkeit (Synonyme, Schreibvarianten)
            continue
        p["rang"] = bewerten(zeile, p, ids[pid])
        kandidaten.append(p)
    kandidaten.sort(key=lambda p: -p["rang"])
    return kandidaten


def zeile_zuordnen(con, zeile: dict, kaufdatum: date) -> dict:
    schluessel = normalisieren(zeile["bon_text"])
    gelernt = con.execute(f"""SELECT {_SPALTEN}, z.bestaetigt FROM bon_zuordnung z JOIN rewe_products p USING (rewe_product_id)
                              WHERE z.bon_text_norm = %s""", (schluessel,)).fetchone()
    if gelernt:
        return {"status": "sicher", "grund": "gelernt" + (" (bestätigt)" if gelernt[-1] else ""), "produkt": _produkt(gelernt[:-1]), "kandidaten": []}
    if ist_wasser_marke(zeile["bon_text"]):
        return {"status": "wasser", "grund": "Wassermarke im Kassentext", "produkt": None, "kandidaten": []}

    pro_kg = zeile.get("kilopreis") is not None
    preis = zeile["kilopreis"] if pro_kg else zeile["einzelpreis"]
    kandidaten = []
    if preis:
        for p in _preis_kandidaten(con, preis, kaufdatum, pro_kg, zeile.get("markt")):
            p["textwert"] = round(textwert(zeile["bon_text"], p["name"], p["brand"]), 2)
            if p["textwert"] >= 0.5:
                p["rang"] = bewerten(zeile, p)
                kandidaten.append(p)
    kandidaten.sort(key=lambda p: (-p["textwert"], len(p["name"])))
    voll = [p for p in kandidaten if p["textwert"] >= 0.99 and not (pro_kg and p.get("verarbeitet"))]
    if len(voll) == 1 and (len(kandidaten) == 1 or kandidaten[1]["textwert"] <= 0.65):
        return {"status": "sicher", "grund": "Preis und Text eindeutig", "produkt": voll[0], "kandidaten": []}
    if len(voll) > 1:
        voll.sort(key=lambda p: -p["rang"])
        return {"status": "unsicher", "grund": f"{len(voll)} Produkte mit gleichem Preis passen", "produkt": None,
                "kandidaten": voll[:3]}
    # Preistreffer nur mit halbem Text oder gar kein Preistreffer (Ladenpreis weicht vom Onlinepreis ab, anderer Markt):
    # nach Textähnlichkeit ordnen, nie automatisch übernehmen
    vorschlaege = {p["rewe_product_id"]: p for p in _text_kandidaten(con, zeile["bon_text"], zeile)}
    for p in kandidaten:
        vorschlaege.setdefault(p["rewe_product_id"], p)
    liste = sorted(vorschlaege.values(), key=lambda p: -p["rang"])
    # Schwache Vorschläge (Geschmacksvariante, Fertiggericht, kaum Textübereinstimmung) lieber gar nicht vorschlagen
    liste = [p for p in liste if p["rang"] >= MIN_RANG]
    frisch = [p for p in liste if not p.get("verarbeitet")]
    liste = (frisch or []) if (pro_kg or frisch) else liste   # nicht Verarbeitetes bevorzugen, bei Gewichtsware ausschließlich
    # Geschmacksvarianten/Verarbeitungsformen, die nicht auf dem Bon stehen, nur vorschlagen, wenn es nichts Schlichtes gibt
    sauber = [p for p in liste if not p.get("merkmale_extra")]
    liste = (sauber or liste)[:3]
    if liste and all(ist_wasser_produkt(con, p["rewe_product_id"]) for p in liste):
        return {"status": "wasser", "grund": "alle Kandidaten sind Wasser", "produkt": None, "kandidaten": []}
    if liste:
        grund = "Text passt, Preis nicht" if not kandidaten else "Preis passt, Text nur teilweise"
        return {"status": "unsicher", "grund": grund, "produkt": None, "kandidaten": liste}
    return {"status": "keine", "grund": "kein passendes Produkt in der REWE-Tabelle", "produkt": None, "kandidaten": []}


# --- Mengen -------------------------------------------------------------------------------------------------------
# Rangfolge: 1. Gewicht/Mengenangabe vom Bon, 2. Packungsgröße des sicheren Treffers, 3. Packungsgröße des bestätigten bzw.
# gelernten Treffers, 4. Stückzahl vom Bon („2 Stk x …“). Sonst wird nicht geraten: Menge offen -> Rückfrage.
_MENGE_TEXT = re.compile(r"(?<![\w,.])(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", re.I)


def _ziffern(zahl) -> str:
    """Nur die Ziffern einer Zahl ohne führende Nullen: 4,45 -> „445“, 0,89 -> „89“, 445.0 -> „445“."""
    d = Decimal(str(zahl)).normalize()
    return re.sub(r"\D", "", format(d, "f")).lstrip("0")


def bon_angabe(zeile: dict) -> tuple[float, str, str] | None:
    """Menge, die auf dem Bon selbst steht: gewogenes Gewicht oder Gramm-/Milliliterangabe im Kassentext."""
    if zeile.get("gewicht_kg") is not None:
        return float(round(Decimal(str(zeile["gewicht_kg"])) * 1000)), "g", "bon_gewicht"
    m = _MENGE_TEXT.search(str(zeile.get("bon_text") or ""))
    if m:
        wert = float(_zahl(m.group(1)))
        einheit = m.group(2).lower()
        faktor = {"kg": 1000, "l": 1000}.get(einheit, 1)
        return round(wert * faktor * (zeile.get("anzahl") or 1), 2), "ml" if einheit in ("ml", "l") else "g", "bon_angabe"
    return None


def ki_menge_pruefen(zeile: dict, menge, einheit: str | None = None) -> tuple[float | None, str]:
    """Menge aus der KI-Extraktion: nur gültig, wenn der Bon ein Gewicht/eine Angabe zeigt und sie nicht aus dem Preis stammt."""
    if menge is None or menge == "":
        return None, "keine Menge"
    try:
        m = float(str(menge).replace(",", "."))
    except ValueError:
        return None, "keine Zahl"
    if m <= 0:
        return None, "nicht positiv"
    preise = [zeile.get(k) for k in ("betrag", "einzelpreis", "kilopreis") if zeile.get(k) is not None]
    if any(_ziffern(m) == _ziffern(p) for p in preise if _ziffern(p)):
        return None, "Ziffern entsprechen dem Preis"
    if bon_angabe(zeile) is None:
        return None, "kein Gewicht auf dem Bon"
    return m, "ok"


def menge_bestimmen(zeile: dict, produkt: dict | None = None, vertrauen: str = "sicher") -> dict:
    """Zu buchende Menge einer Bonzeile. vertrauen: „sicher“ | „bestaetigt“ | „gelernt“ (Herkunft des Produkts)."""
    anzahl = zeile.get("anzahl") or 1
    angabe = bon_angabe(zeile)
    if angabe:
        return {"menge": angabe[0], "einheit": angabe[1], "quelle": angabe[2], "offen": False}
    if produkt and produkt.get("size_unit") == "Stück" and produkt.get("size_value") == 1:
        ca = re.search(r"ca\.?\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", f"{produkt.get('grammage_raw') or ''} {produkt.get('name') or ''}", re.I)
        if ca:
            faktor = 1000 if ca.group(2).lower() in ("kg", "l") else 1
            return {"menge": round(float(ca.group(1).replace(",", ".")) * faktor * anzahl, 2),
                    "einheit": "ml" if ca.group(2).lower() in ("ml", "l") else "g", "quelle": "packung_" + vertrauen + "_ca", "offen": False}
    if produkt and produkt.get("size_unit") == "Stück" and produkt.get("size_value") == 1:
        # Einzelstück-Ware (Kiwi, Avocado): die Stückzahl steht auf dem Bon („2 Stk x 0,89“ bzw. eine Zeile = ein Stück)
        return {"menge": float(anzahl), "einheit": "stk", "quelle": "bon_stueck", "offen": False}
    if produkt and produkt.get("size_value") and produkt.get("size_unit") in ("g", "ml", "Stück"):
        einheit = "stk" if produkt["size_unit"] == "Stück" else produkt["size_unit"]
        return {"menge": round(float(produkt["size_value"]) * anzahl, 2), "einheit": einheit,
                "quelle": "packung_" + vertrauen, "offen": False}
    if anzahl > 1:
        return {"menge": float(anzahl), "einheit": "stk", "quelle": "bon_stueck", "offen": False}
    return {"menge": None, "einheit": None, "quelle": None, "offen": True}


def zuordnen(con, bon_text_roh: str, bon_id: str, texte: list[str] | None = None, kaufdatum: str | None = None) -> dict:
    """Liest den Bon, ordnet alle Zeilen zu und merkt sie sich (für die spätere Rückfrage)."""
    bon = bon_lesen(bon_text_roh)
    datum = bon["datum"] or (date.fromisoformat(kaufdatum) if kaufdatum else date.today())
    ergebnisse = []
    wasser: set[str] = set()
    ignoriert: dict[str, str] = {}
    for z in bon["zeilen"]:
        if z["ignorieren"]:
            # Pfand, Leergut, Rabatt, Wasser: gehört nie in den Vorrat, auch wenn die KI die Zeile als Artikel liefert
            ignoriert[normalisieren(z["bon_text"])] = "Wasser" if ist_wasser(z["bon_text"]) else "Pfand/Leergut/Rabatt"
            continue
        z["markt"] = bon["markt"]
        erg = zeile_zuordnen(con, z, datum)
        if erg["status"] == "wasser" or (erg["status"] == "sicher" and ist_wasser_produkt(con, (erg["produkt"] or {}).get("rewe_product_id"))):
            # Wasser wird nie erfasst: Zeile weglassen, n8n bekommt „ignorieren“ für den KI-Artikel
            wasser.add(normalisieren(z["bon_text"]))
            continue
        zeile_id = con.execute("""
            INSERT INTO bon_zeilen (bon_id, kaufdatum, bon_text, bon_text_norm, anzahl, einzelpreis, gewicht_kg, kilopreis,
                                    status, rewe_product_id, kandidaten, markt)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bon_id, bon_text_norm) DO UPDATE SET status = EXCLUDED.status,
                rewe_product_id = EXCLUDED.rewe_product_id, kandidaten = EXCLUDED.kandidaten
            RETURNING id""", (bon_id, datum, z["bon_text"], normalisieren(z["bon_text"]), z["anzahl"], z["einzelpreis"],
                               z["gewicht_kg"], z["kilopreis"], erg["status"],
                               (erg["produkt"] or {}).get("rewe_product_id"),
                               Jsonb([k["rewe_product_id"] for k in erg["kandidaten"]]), bon["markt"])).fetchone()[0]
        # sichere Zuordnungen per Preis+Text lernen (bestätigte überschreiben sie nie)
        if erg["status"] == "sicher" and erg["grund"] == "Preis und Text eindeutig":
            lernen(con, z["bon_text"], erg["produkt"]["rewe_product_id"], bestaetigt=False)
            bonpreis_merken(con, erg["produkt"]["rewe_product_id"], bon["markt"], {**z, "datum": datum})
        vertrauen = "gelernt" if erg["grund"].startswith("gelernt") else "sicher"
        menge_info = menge_bestimmen(z, erg["produkt"] if erg["status"] == "sicher" else None, vertrauen)
        for k in erg["kandidaten"]:
            k["anzeige"] = produkt_anzeige(k)
        ergebnisse.append({"zeile_id": zeile_id, "bon_text": z["bon_text"], "anzahl": z["anzahl"], "menge_info": menge_info,
                           "zeile_text": zeile_text(z),
                           "einzelpreis": float(z["einzelpreis"]) if z["einzelpreis"] is not None else None,
                           "gewicht_kg": float(z["gewicht_kg"]) if z["gewicht_kg"] is not None else None,
                           "kilopreis": float(z["kilopreis"]) if z["kilopreis"] is not None else None, **erg})
    # KI-Artikel (Kassentexte) den gelesenen Zeilen zuordnen, damit n8n die Ergebnisse übernehmen kann
    zu_artikeln = None
    if texte is not None:
        nach_text = {normalisieren(e["bon_text"]): e for e in ergebnisse}
        zu_artikeln = [{"bon_text": t, "ignorieren": True, "grund": "Wasser"} if normalisieren(t) in wasser
                       else {"bon_text": t, "ignorieren": True, "grund": ignoriert[normalisieren(t)]} if normalisieren(t) in ignoriert
                       else nach_text.get(normalisieren(t)) for t in texte]
    return {"kaufdatum": datum.isoformat(), "markt": bon["markt"], "zeilen": ergebnisse, "artikel": zu_artikeln,
            "statistik": {s: sum(1 for e in ergebnisse if e["status"] == s) for s in ("sicher", "unsicher", "keine")}}


def lernen(con, bon_text: str, rewe_product_id: str, bestaetigt: bool = True) -> None:
    con.execute("""
        INSERT INTO bon_zuordnung (bon_text_norm, bon_text, rewe_product_id, bestaetigt)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (bon_text_norm) DO UPDATE SET
            rewe_product_id = CASE WHEN bon_zuordnung.bestaetigt AND NOT EXCLUDED.bestaetigt
                                   THEN bon_zuordnung.rewe_product_id ELSE EXCLUDED.rewe_product_id END,
            bestaetigt = bon_zuordnung.bestaetigt OR EXCLUDED.bestaetigt,
            anzahl = bon_zuordnung.anzahl + 1, zuletzt = now()""",
                (normalisieren(bon_text), bon_text, rewe_product_id, bestaetigt))


def _nachbuchen(con, zeile_id: int, bon_text: str, menge_info: dict) -> dict:
    """Produktwahl für eine noch nicht gebuchte Zeile („Menge offen“): steht die Menge jetzt fest, soll n8n nachbuchen,
    sonst wird daraus eine Mengen-Rückfrage."""
    from . import rueckfragen
    r = con.execute("""SELECT id, chat_id, payload FROM offene_rueckfragen
                       WHERE bon_zeile_id = %s AND art = 'produkt' AND status = 'offen' ORDER BY id DESC LIMIT 1""", (zeile_id,)).fetchone()
    if not r or not (r[2] or {}).get("unbucht"):
        return {}
    payload = r[2]
    menge = None if menge_info["offen"] else rueckfragen._in_einheit(menge_info["menge"], menge_info["einheit"], payload.get("einheit"),
                                                                     payload.get("gramm_pro_stk"))
    rueckfragen.abschliessen(con, r[0])
    if menge is not None:
        return {"nachbuchen": {"menge": menge, "einheit": payload.get("einheit") or menge_info["einheit"], "payload": payload}}
    if not menge_info["offen"] and payload.get("neu"):
        # Das Grocy-Produkt wurde vom Import nur mit der KI-Einheit angelegt und hat noch keinen Bestand: Lagereinheit auf die des gewählten Produkts stellen
        return {"nachbuchen": {"menge": menge_info["menge"], "einheit": menge_info["einheit"], "payload": payload, "einheit_aendern": True}}
    rueckfragen.anlegen(con, r[1], "menge", zeile_id, bon_text, payload=payload)
    return {"menge_nachfragen": True}


def antwort_speichern(con, zeile_id: int, rewe_product_id: str | None, menge: float | None = None, einheit: str | None = None) -> dict:
    """Antwort auf die Rückfrage: Zuordnung lernen (oder „keins davon“ vermerken) und Produktdaten zurückgeben."""
    zeile = con.execute("SELECT bon_text, anzahl, gewicht_kg, einzelpreis, kilopreis, markt FROM bon_zeilen WHERE id = %s", (zeile_id,)).fetchone()
    if not zeile:
        return {"ok": False, "fehler": "Bonzeile unbekannt"}
    # Stückzahl bzw. Gewicht vom Bon: damit kann n8n die gebuchte Menge auf Packungsgröße × Anzahl korrigieren
    bon = {"anzahl": zeile[1], "gewicht_kg": float(zeile[2]) if zeile[2] is not None else None}
    bon_zeile = {"bon_text": zeile[0], "anzahl": zeile[1], "gewicht_kg": zeile[2], "einzelpreis": zeile[3], "kilopreis": zeile[4]}
    if rewe_product_id == "s":       # „🔍 Anderes Produkt suchen“: Rückfrage bleibt offen, der nächste Freitext wird als Suchbegriff genommen
        con.execute("UPDATE offene_rueckfragen SET payload = payload || '{\"suche\": true}' WHERE bon_zeile_id = %s AND art = 'produkt' AND status = 'offen'", (zeile_id,))
        return {"ok": True, "suche": True, "bon_text": zeile[0], "produkt": None,
                "text": f"🔍 Schreib mir den Produktnamen für „{zeile[0]}“ (z. B. „Bio Kefir natur“). Mit „abbrechen“ lasse ich es, wie es ist."}
    if not rewe_product_id:
        con.execute("UPDATE bon_zeilen SET status = 'keins', beantwortet_at = now() WHERE id = %s", (zeile_id,))
        info = menge_bestimmen(bon_zeile, None)
        if menge:
            info = {"menge": float(menge), "einheit": einheit, "quelle": "nutzer", "offen": False}
        folge = _nachbuchen(con, zeile_id, zeile[0], info)
        con.execute("UPDATE offene_rueckfragen SET status = 'beantwortet' WHERE bon_zeile_id = %s AND art = 'produkt' AND status = 'offen'", (zeile_id,))
        return {"ok": True, "bon_text": zeile[0], "produkt": None, "menge_info": info, **folge, **bon}
    produkt = con.execute(f"SELECT {_SPALTEN} FROM rewe_products p WHERE p.rewe_product_id = %s", (rewe_product_id,)).fetchone()
    if not produkt:
        return {"ok": False, "fehler": "Produkt unbekannt"}
    lernen(con, zeile[0], rewe_product_id, bestaetigt=True)
    bonpreis_merken(con, rewe_product_id, zeile[5], bon_zeile)
    con.execute("UPDATE bon_zeilen SET status = 'bestaetigt', rewe_product_id = %s, beantwortet_at = now() WHERE id = %s",
                (rewe_product_id, zeile_id))
    produkt = _produkt(produkt)
    # Packungsgröße gilt auch nach Bestätigung einer Rückfrage (Rang 3), nicht nur bei sicheren Treffern
    info = menge_bestimmen(bon_zeile, produkt, "bestaetigt")
    if menge:                       # Menge, die der Nutzer selbst genannt hat („Speisekartoffeln 1000g“), geht vor der Packungsgröße
        info = {"menge": float(menge), "einheit": einheit or info.get("einheit"), "quelle": "nutzer", "offen": False}
    folge = _nachbuchen(con, zeile_id, zeile[0], info)
    con.execute("UPDATE offene_rueckfragen SET status = 'beantwortet' WHERE bon_zeile_id = %s AND art = 'produkt' AND status = 'offen'", (zeile_id,))
    return {"ok": True, "bon_text": zeile[0], "produkt": produkt, "menge_info": info, **folge, **bon}
