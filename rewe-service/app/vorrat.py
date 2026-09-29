"""Vorratsprodukte in Postgres: Verknüpfung Grocy ↔ REWE, eigene Nährwerte und Stückgewicht mit Rangregel.

Ein Wert wird nur durch einen gleich guten oder besseren ersetzt (kleinerer Rang = besser), leere Werte
überschreiben nie, unplausible Nährwerte werden nicht gespeichert, sondern gemeldet.
"""

from __future__ import annotations

import re

from psycopg.rows import dict_row

from . import naehrwerte as nw

_NW_SPALTEN = {"kcal": "kcal_100", "protein": "protein_100", "fett": "fett_100", "kh": "kh_100",
               "zucker": "zucker_100", "ballaststoffe": "ballaststoffe_100", "salz": "salz_100"}
REWE_ID = re.compile(r"REWE-ID\s*(\d+)")


def einheit_code(einheit: str | None) -> str:
    e = str(einheit or "").strip().lower()
    if e in ("ml", "milliliter"):
        return "ml"
    return "stk" if e in ("stk", "stück", "st", "stueck") else "g"


def lesen(con, grocy_product_id: int) -> dict | None:
    with con.cursor(row_factory=dict_row) as cur:
        return cur.execute("SELECT * FROM vorrat_naehrwerte WHERE grocy_product_id = %s", (grocy_product_id,)).fetchone()


def _roh(con, grocy_product_id: int) -> dict | None:
    with con.cursor(row_factory=dict_row) as cur:
        return cur.execute("SELECT * FROM vorrat_produkte WHERE grocy_product_id = %s", (grocy_product_id,)).fetchone()


def _rewe_rang(con, rewe_product_id: str | None) -> int:
    """Rang der (plausiblen) Nährwerte des verknüpften REWE-Produkts, 99 = keine."""
    if not rewe_product_id:
        return 99
    z = con.execute("""SELECT CASE naehrwerte_quelle WHEN 'rewe' THEN 2 WHEN 'openfoodfacts' THEN 3 END
                       FROM rewe_products WHERE rewe_product_id = %s
                         AND naehrwerte_plausibel(kcal_100, protein_100, fett_100, kh_100, ballaststoffe_100)""",
                    (rewe_product_id,)).fetchone()
    return z[0] if z and z[0] else 99


def speichern(con, grocy_product_id: int, daten: dict) -> dict:
    """Legt an oder aktualisiert. daten (alles optional außer name bei neuen Produkten):
    name, einheit, kategorie, rewe_product_id, ean, nutriscore, nova,
    naehrwerte {kcal, protein, fett, kh, zucker, ballaststoffe, salz}, naehrwert_quelle, naehrwert_detail,
    gramm_pro_stk, gramm_quelle, gramm_detail.

    Rückgabe: {produkt: Zeile der View, naehrwerte: gespeichert|schlechter|unplausibel|rewe|keine,
               gramm: gespeichert|schlechter|keine, hinweise: [...]}
    """
    hinweise: list[str] = []
    alt = _roh(con, grocy_product_id)
    if alt is None:
        con.execute("INSERT INTO vorrat_produkte (grocy_product_id, name, einheit) VALUES (%s, %s, %s)",
                    (grocy_product_id, daten.get("name") or f"Produkt {grocy_product_id}", einheit_code(daten.get("einheit"))))
        alt = _roh(con, grocy_product_id)

    felder: dict = {}
    for k in ("name", "kategorie", "nutriscore"):
        if daten.get(k):
            felder[k] = str(daten[k])
    if daten.get("einheit"):
        felder["einheit"] = einheit_code(daten["einheit"])
    if daten.get("nova"):
        felder["nova"] = int(daten["nova"])
    if daten.get("ean"):
        felder["ean"] = str(daten["ean"])
    rid = str(daten.get("rewe_product_id") or "").strip()
    if rid:
        if con.execute("SELECT 1 FROM rewe_products WHERE rewe_product_id = %s", (rid,)).fetchone():
            felder["rewe_product_id"] = rid
        else:
            hinweise.append(f"REWE-ID {rid} unbekannt, nicht verknüpft")

    # Nährwerte: nur mit Quelle; REWE-Werte kommen über die Verknüpfung, nicht als eigene Kopie
    status_nw = "keine"
    werte = nw.bereinigen(daten.get("naehrwerte"))
    quelle = daten.get("naehrwert_quelle")
    if werte and quelle == "rewe":
        status_nw = "rewe"
    elif werte and quelle in nw.RANG:
        ok, grund = nw.plausibel(werte)
        rang = nw.RANG[quelle]
        if not ok:
            status_nw = "unplausibel"
            hinweise.append(f"Nährwerte ({quelle}) unplausibel: {grund}")
            nw.melden(con, "unplausibel", f"{felder.get('name') or alt['name']} (Grocy {grocy_product_id}, {quelle}): {grund} – nicht übernommen",
                      {"grocy_product_id": grocy_product_id, "quelle": quelle, "werte": werte, "grund": grund})
        elif (alt["naehrwert_rang"] is not None and rang > alt["naehrwert_rang"]) or \
                rang > _rewe_rang(con, felder.get("rewe_product_id") or alt["rewe_product_id"]):
            status_nw = "schlechter"
        else:
            status_nw = "gespeichert"
            gleiche_quelle = alt["naehrwert_quelle"] == quelle
            for k, s in _NW_SPALTEN.items():
                # Zucker/Ballaststoffe/Salz: fehlende Angaben überschreiben bei gleicher Quelle nie vorhandene
                if werte.get(k) is None and gleiche_quelle and k not in nw.MAKROS:
                    continue
                felder[s] = werte.get(k)
            felder.update(naehrwert_quelle=quelle, naehrwert_rang=rang, naehrwert_detail=daten.get("naehrwert_detail"))

    status_g = "keine"
    gramm = nw._zahl(daten.get("gramm_pro_stk"))
    gq = daten.get("gramm_quelle")
    if gramm and gramm > 0 and gq in nw.GRAMM_RANG:
        if alt["gramm_rang"] is not None and nw.GRAMM_RANG[gq] > alt["gramm_rang"]:
            status_g = "schlechter"
        else:
            status_g = "gespeichert"
            felder.update(gramm_pro_stk=round(gramm, 1), gramm_quelle=gq, gramm_rang=nw.GRAMM_RANG[gq],
                          gramm_detail=daten.get("gramm_detail"))

    if felder:
        teile = [f"{k} = %({k})s" for k in felder]
        if status_nw == "gespeichert":
            teile.append("naehrwert_stand = now()")
        con.execute(f"UPDATE vorrat_produkte SET {', '.join(teile)}, aktualisiert_at = now() WHERE grocy_product_id = %(gid)s",
                    {**felder, "gid": grocy_product_id})
    return {"produkt": lesen(con, grocy_product_id), "naehrwerte": status_nw, "gramm": status_g, "hinweise": hinweise}


# --- Übernahme aus der n8n-Datentabelle ------------------------------------------------------------

_ALTE_QUELLE = {"nutzer": "manuell", "manuell": "manuell", "ki-schaetzung": "ki", "ki": "ki",
                "openfoodfacts": "off_name", "rewe": "rewe"}


def migrieren(con, zeilen: list[dict]) -> list[dict]:
    """zeilen: n8n-Datentabelle vorrat_produkte + Grocy-Beschreibung (Feld beschreibung).

    REWE-ID aus der Beschreibung („REWE-ID 123“), nur wenn sie in rewe_products existiert. Alte Quelle „rewe“ braucht
    keine eigene Kopie (die View liest das REWE-Produkt mit dessen echter Quelle). Stückgewichte -> Quelle ki,
    aber nur bei Stückware (bei g/ml war es das Packungsgewicht).
    """
    bericht = []
    for z in zeilen:
        gid = int(z["grocy_product_id"])
        m = REWE_ID.search(str(z.get("beschreibung") or ""))
        einheit = einheit_code(z.get("einheit"))
        quelle = _ALTE_QUELLE.get(str(z.get("quelle") or "").strip().lower())
        daten = {"name": z.get("name"), "einheit": einheit, "kategorie": z.get("kategorie"),
                 "rewe_product_id": m.group(1) if m else None, "ean": z.get("off_code") or None,
                 "nutriscore": z.get("nutriscore") or None, "nova": z.get("nova") or None,
                 "naehrwerte": {"kcal": z.get("kcal_100"), "protein": z.get("protein_100"), "fett": z.get("fett_100"),
                                "kh": z.get("kh_100")},
                 "naehrwert_quelle": quelle, "naehrwert_detail": "aus n8n-Datentabelle übernommen"}
        if quelle == "rewe" and not m:
            daten["naehrwert_quelle"] = "ki"  # ohne REWE-Verknüpfung nicht belegbar
        if einheit == "stk" and nw._zahl(z.get("gramm_pro_stk")):
            daten.update(gramm_pro_stk=z["gramm_pro_stk"], gramm_quelle="ki", gramm_detail="aus n8n-Datentabelle übernommen")
        erg = speichern(con, gid, daten)
        p = erg["produkt"]
        bericht.append({"grocy_product_id": gid, "name": p["name"], "rewe_product_id": p["rewe_product_id"],
                        "quelle": p["naehrwert_quelle"], "rang": p["naehrwert_rang"], "kcal_100": p["kcal_100"],
                        "gramm_pro_stk": p["gramm_pro_stk"], "gramm_quelle": p["gramm_quelle"], "hinweise": erg["hinweise"]})
    return bericht

