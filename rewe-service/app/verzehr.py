"""Korrektur des Verzehr-Protokolls (Nachtjob).

Neu berechnet (Gramm × aktuelle Werte) wird nur, wenn sich die QUELLE verbessert hat (kleinerer Rang) oder das
Stückgewicht einen besseren Rang hat. Hat sich nur der REWE-Stand geändert (neue Rezeptur, gleicher Rang), bleibt
der alte Wert: er galt damals. Einträge ohne Produktbezug (auswärts gegessen) bleiben unverändert.
"""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import naehrwerte as nw

_MAKRO = {"kcal": "kcal_100", "protein": "protein_100", "fett": "fett_100", "kh": "kh_100"}


def _aktuell(con, grocy_product_id, rewe_product_id) -> dict | None:
    with con.cursor(row_factory=dict_row) as cur:
        if grocy_product_id is not None:
            v = cur.execute("SELECT * FROM vorrat_naehrwerte WHERE grocy_product_id = %s", (grocy_product_id,)).fetchone()
            if v:
                return v
        if rewe_product_id:
            r = nw.rewe_werte(con, rewe_product_id)
            q = nw.REWE_QUELLE.get((r or {}).get("quelle") or "")
            if r and q and nw.plausibel(r["werte"])[0]:
                return {"naehrwert_quelle": q, "naehrwert_rang": nw.RANG[q], "naehrwert_verlauf_id": r["verlauf_id"],
                        **{s: r["werte"].get(k) for k, s in _MAKRO.items()}, "gramm_pro_stk": None, "gramm_rang": None, "gramm_quelle": None}
    return None


def korrigieren(con) -> dict:
    stat = {"geprueft": 0, "korrigiert": 0}
    with con.cursor(row_factory=dict_row) as cur:
        zeilen = cur.execute("""
            SELECT id, grocy_product_id, rewe_product_id, menge, einheit, gramm, kcal, protein, fett, kh,
                   naehrwert_quelle, naehrwert_rang, naehrwert_verlauf_id, gramm_quelle, gramm_rang
            FROM verzehr
            WHERE NOT ignoriert AND quelle IN ('grocy', 'rezept') AND (grocy_product_id IS NOT NULL OR rewe_product_id IS NOT NULL)
            ORDER BY id""").fetchall()
    for z in zeilen:
        stat["geprueft"] += 1
        a = _aktuell(con, z["grocy_product_id"], z["rewe_product_id"])
        if not a or a["kcal_100"] is None:
            continue
        alt_rang = z["naehrwert_rang"] or 99
        quelle_besser = a["naehrwert_rang"] is not None and a["naehrwert_rang"] < alt_rang
        gramm = float(z["gramm"]) if z["gramm"] is not None else None
        gramm_besser = (z["einheit"] == "stk" and z["menge"] and a.get("gramm_pro_stk") and a.get("gramm_rang")
                        and a["gramm_rang"] < (z["gramm_rang"] or 99))
        if not (quelle_besser or gramm_besser):
            continue
        neu_gramm = float(z["menge"]) * float(a["gramm_pro_stk"]) if gramm_besser else gramm
        if not neu_gramm:
            continue
        if quelle_besser or z["kcal"] is None or not gramm:
            je100 = {k: a[s] for k, s in _MAKRO.items()}
            quelle, rang, verlauf = a["naehrwert_quelle"], a["naehrwert_rang"], a["naehrwert_verlauf_id"]
        else:
            # nur das Stückgewicht ist besser: die damals gültigen Werte pro 100 g behalten
            je100 = {k: (float(z[k]) / gramm * 100 if z[k] is not None else None) for k in _MAKRO}
            quelle, rang, verlauf = z["naehrwert_quelle"], z["naehrwert_rang"], z["naehrwert_verlauf_id"]
        neu = {k: (round(float(v) * neu_gramm / 100, 1) if v is not None else None) for k, v in je100.items()}
        g_quelle = a["gramm_quelle"] if gramm_besser else z["gramm_quelle"]
        g_rang = a["gramm_rang"] if gramm_besser else z["gramm_rang"]
        geschaetzt = (rang or 99) >= 5 or (z["einheit"] == "stk" and (g_rang or 4) >= 4)
        grund = " und ".join(x for x in (
            f"bessere Quelle ({z['naehrwert_quelle'] or 'unbekannt'} → {quelle})" if quelle_besser else "",
            f"besseres Stückgewicht ({z['gramm_quelle'] or 'unbekannt'} → {g_quelle})" if gramm_besser else "") if x)
        alt = {k: (float(z[k]) if z[k] is not None else None) for k in ("gramm", "kcal", "protein", "fett", "kh")}
        alt.update(naehrwert_quelle=z["naehrwert_quelle"], naehrwert_rang=z["naehrwert_rang"], gramm_quelle=z["gramm_quelle"])
        con.execute("""
            UPDATE verzehr SET gramm = %(gramm)s, kcal = %(kcal)s, protein = %(protein)s, fett = %(fett)s, kh = %(kh)s,
                   naehrwert_quelle = %(q)s, naehrwert_rang = %(r)s, naehrwert_verlauf_id = %(v)s,
                   gramm_quelle = %(gq)s, gramm_rang = %(gr)s, geschaetzt = %(g)s, korrigiert_at = now()
            WHERE id = %(id)s""", {"gramm": round(neu_gramm, 1), **neu, "q": quelle, "r": rang, "v": verlauf, "gq": g_quelle,
                                  "gr": g_rang, "g": geschaetzt, "id": z["id"]})
        con.execute("INSERT INTO verzehr_korrektur (verzehr_id, grund, alt, neu) VALUES (%s, %s, %s, %s)",
                    (z["id"], grund, Jsonb(alt), Jsonb({"gramm": round(neu_gramm, 1), **neu, "naehrwert_quelle": quelle,
                                                        "naehrwert_rang": rang, "gramm_quelle": g_quelle})))
        stat["korrigiert"] += 1
    return stat
