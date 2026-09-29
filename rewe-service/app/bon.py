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
TOLERANZ_TAGE = 45


def _zahl(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


def normalisieren(text: str) -> str:
    """Kleinbuchstaben, Umlaute auflösen (ä->a), nur Buchstaben/Ziffern und Leerzeichen."""
    t = unicodedata.normalize("NFKD", str(text or "").lower()).replace("ß", "ss")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


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


def _kassenwoerter(bon_text: str) -> list[tuple[str, bool]]:
    """Wörter des Kassentexts mit Kennzeichen, ob sie mit Punkt abgekürzt sind („HAHN.“ -> abgekürzt)."""
    woerter = []
    for m in re.finditer(r"([^\W_]+)(\.)?", str(bon_text or "")):
        w = normalisieren(m.group(1))
        if len(w) >= 2 and not w.isdigit():
            woerter.append((w, bool(m.group(2))))
    return woerter


def _wort_passt(wort: str, abgekuerzt: bool, name: str, zusammen: str) -> bool:
    if len(wort) < 3:
        return wort in name.split()
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
            "ballaststoffe_100", "naehrwert_verlauf_id")
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
              p.ballaststoffe_100, p.naehrwert_verlauf_id"""


def _preis_kandidaten(con, preis: Decimal, kaufdatum: date, pro_kg: bool) -> list[dict]:
    von, bis = kaufdatum - timedelta(days=TOLERANZ_TAGE), kaufdatum + timedelta(days=TOLERANZ_TAGE)
    if pro_kg:
        sql = f"SELECT {_SPALTEN} FROM rewe_products p WHERE p.price_per_kg_or_l = %(p)s OR (p.size_unit = 'g' AND p.size_value = 1000 AND p.price = %(p)s)"
    else:
        sql = f"""SELECT {_SPALTEN} FROM rewe_products p
                  WHERE p.price = %(p)s
                     OR (p.angebotspreis = %(p)s AND p.angebot_bis >= %(d)s AND p.angebot_bis <= %(d)s + 7)
                     OR EXISTS (SELECT 1 FROM rewe_price_history h WHERE h.rewe_product_id = p.rewe_product_id
                                AND h.price = %(p)s AND h.crawled_at::date BETWEEN %(von)s AND %(bis)s)"""
    return [_produkt(r) for r in con.execute(sql, {"p": preis, "d": kaufdatum, "von": von, "bis": bis})]


def _text_kandidaten(con, bon_text: str, preis: Decimal | None) -> list[dict]:
    """Produkte, deren Name den Kassentext vollständig enthält – sortiert nach Preisnähe."""
    woerter = sorted((w for w, _ in _kassenwoerter(bon_text) if len(w) >= 4), key=len, reverse=True)
    if not woerter:
        return []
    kandidaten = []
    for r in con.execute(f"SELECT {_SPALTEN} FROM rewe_products p WHERE translate(lower(p.name), 'äöüß', 'aous') LIKE %s LIMIT 300",
                         ("%" + woerter[0] + "%",)):
        p = _produkt(r)
        p["textwert"] = round(textwert(bon_text, p["name"], p["brand"]), 2)
        if p["textwert"] >= 0.99:
            kandidaten.append(p)
    kandidaten.sort(key=lambda p: (abs((p["price"] or 0) - float(preis or 0)), len(p["name"])))
    return kandidaten


def zeile_zuordnen(con, zeile: dict, kaufdatum: date) -> dict:
    schluessel = normalisieren(zeile["bon_text"])
    gelernt = con.execute(f"""SELECT {_SPALTEN}, z.bestaetigt FROM bon_zuordnung z JOIN rewe_products p USING (rewe_product_id)
                              WHERE z.bon_text_norm = %s""", (schluessel,)).fetchone()
    if gelernt:
        return {"status": "sicher", "grund": "gelernt" + (" (bestätigt)" if gelernt[-1] else ""), "produkt": _produkt(gelernt[:-1]), "kandidaten": []}

    pro_kg = zeile.get("kilopreis") is not None
    preis = zeile["kilopreis"] if pro_kg else zeile["einzelpreis"]
    kandidaten = []
    if preis:
        for p in _preis_kandidaten(con, preis, kaufdatum, pro_kg):
            p["textwert"] = round(textwert(zeile["bon_text"], p["name"], p["brand"]), 2)
            if p["textwert"] >= 0.5:
                kandidaten.append(p)
    kandidaten.sort(key=lambda p: (-p["textwert"], len(p["name"])))
    voll = [p for p in kandidaten if p["textwert"] >= 0.99]
    if len(voll) == 1 and (len(kandidaten) == 1 or kandidaten[1]["textwert"] <= 0.65):
        return {"status": "sicher", "grund": "Preis und Text eindeutig", "produkt": voll[0], "kandidaten": []}
    if len(voll) > 1:
        return {"status": "unsicher", "grund": f"{len(voll)} Produkte mit gleichem Preis passen", "produkt": None,
                "kandidaten": voll[:3]}
    # Preistreffer nur mit halbem Text oder gar kein Preistreffer (z.B. Ladenpreis weicht vom Onlinepreis ab):
    # Produkte mit vollständig passendem Text dazunehmen, nie automatisch übernehmen
    vorschlaege = {p["rewe_product_id"]: p for p in _text_kandidaten(con, zeile["bon_text"], preis)[:3]}
    for p in kandidaten:
        vorschlaege.setdefault(p["rewe_product_id"], p)
    liste = list(vorschlaege.values())[:3]
    if liste:
        grund = "Text passt, Preis nicht" if not kandidaten else "Preis passt, Text nur teilweise"
        return {"status": "unsicher", "grund": grund, "produkt": None, "kandidaten": liste}
    return {"status": "keine", "grund": "kein passendes Produkt in der REWE-Tabelle", "produkt": None, "kandidaten": []}


def zuordnen(con, bon_text_roh: str, bon_id: str, texte: list[str] | None = None, kaufdatum: str | None = None) -> dict:
    """Liest den Bon, ordnet alle Zeilen zu und merkt sie sich (für die spätere Rückfrage)."""
    bon = bon_lesen(bon_text_roh)
    datum = bon["datum"] or (date.fromisoformat(kaufdatum) if kaufdatum else date.today())
    ergebnisse = []
    for z in bon["zeilen"]:
        if z["ignorieren"]:
            continue
        erg = zeile_zuordnen(con, z, datum)
        zeile_id = con.execute("""
            INSERT INTO bon_zeilen (bon_id, kaufdatum, bon_text, bon_text_norm, anzahl, einzelpreis, gewicht_kg, kilopreis,
                                    status, rewe_product_id, kandidaten)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bon_id, bon_text_norm) DO UPDATE SET status = EXCLUDED.status,
                rewe_product_id = EXCLUDED.rewe_product_id, kandidaten = EXCLUDED.kandidaten
            RETURNING id""", (bon_id, datum, z["bon_text"], normalisieren(z["bon_text"]), z["anzahl"], z["einzelpreis"],
                               z["gewicht_kg"], z["kilopreis"], erg["status"],
                               (erg["produkt"] or {}).get("rewe_product_id"),
                               Jsonb([k["rewe_product_id"] for k in erg["kandidaten"]]))).fetchone()[0]
        # sichere Zuordnungen per Preis+Text lernen (bestätigte überschreiben sie nie)
        if erg["status"] == "sicher" and erg["grund"] == "Preis und Text eindeutig":
            lernen(con, z["bon_text"], erg["produkt"]["rewe_product_id"], bestaetigt=False)
        ergebnisse.append({"zeile_id": zeile_id, "bon_text": z["bon_text"], "anzahl": z["anzahl"],
                           "einzelpreis": float(z["einzelpreis"]) if z["einzelpreis"] is not None else None,
                           "gewicht_kg": float(z["gewicht_kg"]) if z["gewicht_kg"] is not None else None,
                           "kilopreis": float(z["kilopreis"]) if z["kilopreis"] is not None else None, **erg})
    # KI-Artikel (Kassentexte) den gelesenen Zeilen zuordnen, damit n8n die Ergebnisse übernehmen kann
    zu_artikeln = None
    if texte is not None:
        nach_text = {normalisieren(e["bon_text"]): e for e in ergebnisse}
        zu_artikeln = [nach_text.get(normalisieren(t)) for t in texte]
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


def antwort_speichern(con, zeile_id: int, rewe_product_id: str | None) -> dict:
    """Antwort auf die Rückfrage: Zuordnung lernen (oder „keins davon“ vermerken) und Produktdaten zurückgeben."""
    zeile = con.execute("SELECT bon_text, anzahl, gewicht_kg FROM bon_zeilen WHERE id = %s", (zeile_id,)).fetchone()
    if not zeile:
        return {"ok": False, "fehler": "Bonzeile unbekannt"}
    # Stückzahl bzw. Gewicht vom Bon: damit kann n8n die gebuchte Menge auf Packungsgröße × Anzahl korrigieren
    bon = {"anzahl": zeile[1], "gewicht_kg": float(zeile[2]) if zeile[2] is not None else None}
    if not rewe_product_id:
        con.execute("UPDATE bon_zeilen SET status = 'keins', beantwortet_at = now() WHERE id = %s", (zeile_id,))
        return {"ok": True, "bon_text": zeile[0], "produkt": None, **bon}
    produkt = con.execute(f"SELECT {_SPALTEN} FROM rewe_products p WHERE p.rewe_product_id = %s", (rewe_product_id,)).fetchone()
    if not produkt:
        return {"ok": False, "fehler": "Produkt unbekannt"}
    lernen(con, zeile[0], rewe_product_id, bestaetigt=True)
    con.execute("UPDATE bon_zeilen SET status = 'bestaetigt', rewe_product_id = %s, beantwortet_at = now() WHERE id = %s",
                (rewe_product_id, zeile_id))
    return {"ok": True, "bon_text": zeile[0], "produkt": _produkt(produkt), **bon}
