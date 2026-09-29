"""Nährwert-Regeln: Rangfolge der Quellen, Plausibilität, Verlauf und Meldungen.

Grundsätze: Jeder Wert hat eine Quelle mit Rang (1 = beste). Ein Wert wird nur durch einen gleich guten oder
besseren ersetzt, leere Werte überschreiben nie, unplausible Werte werden nicht übernommen, sondern gemeldet.
"""

from __future__ import annotations

import logging

from psycopg.types.json import Jsonb

log = logging.getLogger("naehrwerte")

# Rangfolge der Nährwert-Quellen (Werte pro 100 g/ml)
RANG = {"manuell": 1, "rewe": 2, "off_barcode": 3, "off_name": 4, "bls": 5, "ki": 6}
# Rangfolge des Stückgewichts (immer essbarer Anteil)
GRAMM_RANG = {"manuell": 1, "packung": 2, "referenz": 3, "ki": 4}
# rewe_products.naehrwerte_quelle -> Quelle der Rangfolge
REWE_QUELLE = {"rewe": "rewe", "openfoodfacts": "off_barcode"}

FELDER = ("kcal", "protein", "kh", "fett", "zucker", "ballaststoffe", "salz")
MAKROS = ("kcal", "protein", "kh", "fett")
TOLERANZ = 0.15
# bei sehr energiearmen Lebensmitteln (Gurke, Tee) machen gerundete Etikettwerte mehr als 15 % aus
TOLERANZ_KCAL_MIN = 5
ABWEICHUNG = 0.20
# Mindestunterschied, damit eine 20-%-Abweichung gemeldet wird (0,5 g -> 0,6 g Fett ist Rundung, kein Crawl-Fehler)
ABWEICHUNG_MIN = {"kcal": 10, "protein": 1, "kh": 1, "fett": 1}


def _zahl(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def bereinigen(werte: dict | None) -> dict:
    """Nur bekannte Felder mit Zahlenwert; leere Werte fallen weg."""
    return {k: _zahl(werte.get(k)) for k in FELDER if werte and _zahl(werte.get(k)) is not None}


def plausibel(werte: dict | None) -> tuple[bool, str | None]:
    """kcal ≈ 4·Protein + 4·KH + 9·Fett (+ 2·Ballaststoffe) ±15 %, Protein + Fett + KH ≤ 100 g."""
    w = bereinigen(werte)
    fehlend = [k for k in MAKROS if k not in w]
    if fehlend:
        return False, "unvollständig (fehlt: " + ", ".join(fehlend) + ")"
    if min(w[k] for k in MAKROS) < 0:
        return False, "negativer Wert"
    summe = w["protein"] + w["fett"] + w["kh"]
    if summe > 100.5:  # 0,5 g Luft für gerundete Etikettwerte
        return False, f"Protein + Fett + KH = {summe:.1f} g > 100 g"
    rechnerisch = 4 * w["protein"] + 4 * w["kh"] + 9 * w["fett"] + 2 * w.get("ballaststoffe", 0)
    if abs(w["kcal"] - rechnerisch) > max(TOLERANZ * rechnerisch, TOLERANZ_KCAL_MIN):
        return False, f"{w['kcal']:.0f} kcal passen nicht zu den Makros (rechnerisch {rechnerisch:.0f} kcal)"
    return True, None


def abweichungen(alt: dict, neu: dict) -> dict:
    """Felder, die sich um mehr als 20 % (und mehr als die Rundungsgrenze) geändert haben: {feld: (alt, neu)}."""
    erg = {}
    for k, mindest in ABWEICHUNG_MIN.items():
        a, n = _zahl(alt.get(k)), _zahl(neu.get(k))
        if a is None or n is None:
            continue
        diff = abs(n - a)
        if diff > mindest and diff > ABWEICHUNG * abs(a):
            erg[k] = (a, n)
    return erg


def gleich(a: dict, b: dict) -> bool:
    a, b = bereinigen(a), bereinigen(b)
    return a.keys() == b.keys() and all(abs(a[k] - b[k]) < 0.05 for k in a)


def melden(con, art: str, text: str, daten: dict | None = None) -> None:
    """Meldung für den nächtlichen Telegram-Versand (n8n liest die Tabelle meldungen)."""
    con.execute("INSERT INTO meldungen (art, text, daten) VALUES (%s, %s, %s)",
                (art, text, Jsonb(daten) if daten is not None else None))


def _log(con, run_id, level, text, daten=None):
    con.execute("INSERT INTO crawl_log (run_id, level, message, payload) VALUES (%s, %s, %s, %s)",
                (run_id, level, text, Jsonb(daten) if daten is not None else None))


_SPALTEN = {"kcal": "kcal_100", "protein": "protein_100", "kh": "kh_100", "fett": "fett_100",
            "zucker": "zucker_100", "ballaststoffe": "ballaststoffe_100", "salz": "salz_100"}


def rewe_werte(con, rewe_product_id: str) -> dict | None:
    """Aktueller Stand eines REWE-Produkts: Nährwerte, Quelle, Verlaufs-ID, Details-Datum."""
    z = con.execute(f"""
        SELECT {', '.join(_SPALTEN.values())}, naehrwerte_quelle, naehrwert_verlauf_id, details_fetched_at, name, grammage_raw
        FROM rewe_products WHERE rewe_product_id = %s""", (rewe_product_id,)).fetchone()
    if not z:
        return None
    werte = {k: float(v) for k, v in zip(_SPALTEN, z[:7]) if v is not None}
    return {"werte": werte, "quelle": z[7], "verlauf_id": z[8], "details_fetched_at": z[9], "name": z[10], "grammage": z[11]}


def rewe_speichern(con, rewe_product_id: str, werte: dict | None, quelle: str, meta: dict | None = None,
                   run_id: int | None = None) -> str:
    """Einzige Stelle, die Nährwerte in rewe_products schreibt (Crawler und /products/{id}/aktualisieren).

    quelle: rewe | openfoodfacts. Rückgabe: leer | unplausibel | schlechter | unveraendert | neu | geaendert.
    Jede tatsächliche Änderung erzeugt eine Zeile in rewe_naehrwert_verlauf.
    """
    meta = meta or {}
    stand = rewe_werte(con, rewe_product_id)
    if stand is None:
        raise ValueError(f"REWE-Produkt {rewe_product_id} unbekannt")
    neu = bereinigen(werte)
    alt = stand["werte"]
    info = {"rewe_product_id": rewe_product_id, "name": stand["name"], "quelle": quelle}
    if not neu:
        if alt:
            _log(con, run_id, "info", "Keine Nährwerte geliefert, alte Werte bleiben", info)
        return "leer"
    # fehlende Zusatzangaben (Zucker, Ballaststoffe, Salz) nicht mit leer überschreiben
    neu = {**{k: v for k, v in alt.items() if k not in MAKROS}, **neu}
    ok, grund = plausibel(neu)
    if not ok:
        _log(con, run_id, "warn", f"Nährwerte unplausibel: {grund}", {**info, "werte": neu})
        melden(con, "unplausibel", f"{stand['name']} ({rewe_product_id}, {quelle}): {grund} – nicht übernommen",
               {**info, "werte": neu, "grund": grund})
        return "unplausibel"
    alt_rang = RANG.get(REWE_QUELLE.get(stand["quelle"] or ""), 99) if alt else 99
    if RANG[REWE_QUELLE[quelle]] > alt_rang:
        return "schlechter"
    if alt and stand["quelle"] == quelle and gleich(alt, neu):
        return "unveraendert"
    if alt:
        letzter = con.execute("SELECT name, grammage_raw FROM rewe_naehrwert_verlauf WHERE id = %s",
                              (stand["verlauf_id"],)).fetchone() if stand["verlauf_id"] else None
        # Name/Größe gleich geblieben, Werte stark verändert -> möglicher Crawl-Fehler (trotzdem speichern)
        if letzter and (letzter[0], letzter[1]) == (stand["name"], stand["grammage"]):
            diff = abweichungen(alt, neu)
            if diff:
                text = ", ".join(f"{k} {a:g} → {n:g}" for k, (a, n) in diff.items())
                melden(con, "abweichung", f"{stand['name']} ({rewe_product_id}): {text}",
                       {**info, "alt": alt, "neu": neu})
    vid = con.execute("""
        INSERT INTO rewe_naehrwert_verlauf (rewe_product_id, kcal_100, protein_100, kh_100, fett_100, zucker_100,
                                            ballaststoffe_100, salz_100, quelle, ean, marke, name, grammage_raw)
        SELECT %(id)s, %(kcal)s, %(protein)s, %(kh)s, %(fett)s, %(zucker)s, %(ballaststoffe)s, %(salz)s, %(quelle)s,
               coalesce(%(ean)s, p.ean), coalesce(%(marke)s, p.brand), p.name, p.grammage_raw
        FROM rewe_products p WHERE p.rewe_product_id = %(id)s
        RETURNING id""", {"id": rewe_product_id, "quelle": quelle, "ean": meta.get("ean"), "marke": meta.get("marke"),
                          **{k: neu.get(k) for k in FELDER}}).fetchone()[0]
    con.execute(f"""
        UPDATE rewe_products SET {', '.join(f'{s} = %({k})s' for k, s in _SPALTEN.items())},
               naehrwerte_quelle = %(quelle)s, naehrwert_verlauf_id = %(vid)s
        WHERE rewe_product_id = %(id)s""", {"id": rewe_product_id, "quelle": quelle, "vid": vid,
                                            **{k: neu.get(k) for k in FELDER}})
    return "geaendert" if alt else "neu"
