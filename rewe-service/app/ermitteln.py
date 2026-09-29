"""Zentrale Nährwert-Ermittlung für eBon-Import und Bot: arbeitet die Rangfolge der Quellen ab.

REWE (Details notfalls sofort nachladen) → Open Food Facts per Barcode → Open Food Facts per Name (nur gleiche Marke)
→ BLS (Eintrag von der KI gewählt) → KI-Schätzung. Die KI wählt nur aus, gerechnet wird hier.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from . import naehrwerte as nw
from . import rewe, vorrat

log = logging.getLogger("ermitteln")
DETAILS_MAX_ALTER = timedelta(days=7)


def _norm(s) -> str:
    s = str(s or "").lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_GROESSE = re.compile(r"^\d+([.,]\d+)?(g|kg|ml|l|stuck|stk|er)?$")


def marke_passt(marke: str | None, off_marken: str | None) -> bool:
    m = _norm(marke)
    if not m:
        return False
    # exakt (OFF führt mehrere Marken durch Komma getrennt): „REWE“ ist nicht „REWE Bio“
    return any(_norm(x) == m for x in str(off_marken or "").split(","))


def off_name_treffer(name: str, marke: str, produkte: list[dict]) -> dict | None:
    """Bester Treffer der Namenssuche: Marke muss übereinstimmen, ≥ 60 % der Namenswörter im OFF-Namen."""
    marke_w = set(_norm(marke).split())
    woerter = [w for w in _norm(name).split() if len(w) > 2 and w not in marke_w and not _GROESSE.match(w)]
    bester, bester_wert = None, 0.0
    for p in produkte:
        if not marke_passt(marke, p.get("brands")):
            continue
        werte = rewe.off_werte(p.get("nutriments"))
        if not werte or not nw.plausibel(werte)[0]:
            continue
        pn = _norm(p.get("product_name"))
        anteil = sum(1 for w in woerter if w in pn) / len(woerter) if woerter else 0
        if anteil >= 0.6 and anteil > bester_wert:
            bester, bester_wert = {"werte": werte, "code": str(p.get("code") or ""), "name": p.get("product_name")}, anteil
    return bester


def _in_warteschlange(con, a: dict, art: str, fehler: str) -> None:
    if not a.get("grocy_product_id"):
        return
    con.execute("""
        INSERT INTO off_warteschlange (grocy_product_id, art, anfrage, letzter_fehler)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (grocy_product_id, art) WHERE erledigt_at IS NULL
        DO UPDATE SET anfrage = EXCLUDED.anfrage, letzter_fehler = EXCLUDED.letzter_fehler""",
                (int(a["grocy_product_id"]), art, Jsonb(a), fehler))


def ermitteln(con, a: dict) -> dict:
    """a: grocy_product_id?, name, marke?, rewe_product_id?, ean?, einheit?, kategorie?, bls_code?,
    ki_naehrwerte? {kcal, protein, fett, kh}, werte_quelle? (ki | manuell, für ki_naehrwerte),
    gramm_pro_stk?, gramm_quelle?, speichern? (nur mit grocy_product_id).

    Rückgabe: {quelle, rang, werte, detail, rewe_product_id, ean, warteschlange, schritte, [produkt, naehrwerte, gramm]}
    """
    schritte: list[str] = []
    warteschlange = False
    rid = str(a.get("rewe_product_id") or "").strip() or None
    ean = str(a.get("ean") or "").strip() or None
    marke = a.get("marke")
    kandidat = None  # (quelle, rang, werte, detail, von_rewe_produkt)

    # 1) REWE-Produkt: fehlende oder mehr als 7 Tage alte Details sofort nachladen
    if rid:
        stand = nw.rewe_werte(con, rid)
        alt = stand is None or not stand["werte"] or stand["details_fetched_at"] is None or \
            stand["details_fetched_at"] < datetime.now(timezone.utc) - DETAILS_MAX_ALTER
        if alt:
            from .crawler import produkt_aktualisieren
            try:
                erg = produkt_aktualisieren(con, rid)
                schritte.append(f"REWE-Details nachgeladen ({erg['naehrwerte']})")
            except Exception as e:  # noqa: BLE001 - dann mit dem vorhandenen Stand weiter
                schritte.append(f"REWE-Details nicht abrufbar: {e}")
            stand = nw.rewe_werte(con, rid)
        if stand is None:
            schritte.append(f"REWE-ID {rid} unbekannt")
            rid = None
        else:
            z = con.execute("SELECT ean, brand FROM rewe_products WHERE rewe_product_id = %s", (rid,)).fetchone()
            ean = ean or z[0]
            marke = marke or z[1]
            if stand["werte"] and nw.plausibel(stand["werte"])[0]:
                q = nw.REWE_QUELLE.get(stand["quelle"] or "")
                if q:
                    kandidat = (q, nw.RANG[q], stand["werte"], f"REWE {rid}", True)
                    schritte.append(f"{q}: Werte aus rewe_products")

    # 2) Open Food Facts per Barcode
    if (kandidat is None or kandidat[1] > nw.RANG["off_barcode"]) and ean:
        try:
            werte = rewe.openfoodfacts(ean)
            ok, grund = nw.plausibel(werte)
            if werte and ok:
                kandidat = ("off_barcode", nw.RANG["off_barcode"], werte, f"OFF {ean}", False)
                schritte.append("off_barcode: Treffer")
            elif werte:
                schritte.append(f"off_barcode unplausibel: {grund}")
                nw.melden(con, "unplausibel", f"{a.get('name')}: Open Food Facts {ean} unplausibel ({grund})",
                          {"ean": ean, "werte": werte})
            else:
                schritte.append("off_barcode: kein Treffer")
        except rewe.OffLimit as e:
            warteschlange = True
            _in_warteschlange(con, a, "barcode", str(e))
            schritte.append(f"off_barcode: Anfrage-Limit, in Warteschlange ({e})")

    # 3) Open Food Facts per Name, nur bei gleicher Marke
    if (kandidat is None or kandidat[1] > nw.RANG["off_name"]) and marke and a.get("name") and not warteschlange:
        try:
            suche = f"{marke} {re.sub(re.escape(str(marke)), '', str(a['name']), flags=re.I)}".strip()
            t = off_name_treffer(a["name"], marke, rewe.openfoodfacts_suche(suche))
            if t:
                kandidat = ("off_name", nw.RANG["off_name"], t["werte"], f"OFF {t['code']} {t['name']}", False)
                ean = ean or t["code"] or None
                schritte.append("off_name: Treffer mit gleicher Marke")
            else:
                schritte.append("off_name: kein Treffer mit gleicher Marke")
        except rewe.OffLimit as e:
            warteschlange = True
            _in_warteschlange(con, a, "name", str(e))
            schritte.append(f"off_name: Anfrage-Limit, in Warteschlange ({e})")

    # 4) BLS (die KI hat den Eintrag gewählt) – ab Paket 5
    bls_kandidaten = None
    if kandidat is None or kandidat[1] > nw.RANG["bls"]:
        from . import bls
        if a.get("bls_code"):
            e = bls.eintrag(con, a["bls_code"])
            if e and nw.plausibel(e["werte"])[0]:
                kandidat = ("bls", nw.RANG["bls"], e["werte"], f"BLS {e['code']} {e['name']}", False)
                schritte.append(f"bls: {e['code']} {e['name']}")
            else:
                schritte.append(f"bls: Code {a['bls_code']} unbekannt oder unplausibel")
        else:
            bls_kandidaten = bls.suche(con, a.get("bls_suche") or a.get("name") or "")

    # 5) KI-Schätzung bzw. vom Nutzer genannte Werte
    ki = nw.bereinigen(a.get("ki_naehrwerte"))
    q_ki = a.get("werte_quelle") if a.get("werte_quelle") in ("manuell", "ki") else "ki"
    if ki and (kandidat is None or kandidat[1] > nw.RANG[q_ki]):
        ok, grund = nw.plausibel(ki)
        if ok:
            kandidat = (q_ki, nw.RANG[q_ki], ki, "vom Nutzer" if q_ki == "manuell" else "KI-Schätzung", False)
            schritte.append(f"{q_ki}: übernommen")
        else:
            schritte.append(f"{q_ki} unplausibel: {grund}")

    erg = {"quelle": kandidat[0] if kandidat else None, "rang": kandidat[1] if kandidat else None,
           "werte": kandidat[2] if kandidat else None, "detail": kandidat[3] if kandidat else None,
           "rewe_product_id": rid, "ean": ean, "marke": marke, "warteschlange": warteschlange, "schritte": schritte,
           "bls_kandidaten": bls_kandidaten if (kandidat is None or kandidat[1] > nw.RANG["bls"]) else None}

    # Stückgewicht (Rangfolge ab Paket 5)
    from . import stueckgewicht
    gramm = stueckgewicht.bestimmen(con, a)
    erg["gramm"] = gramm

    if a.get("speichern") and a.get("grocy_product_id"):
        daten = {"name": a.get("name"), "einheit": a.get("einheit"), "kategorie": a.get("kategorie"),
                 "rewe_product_id": rid, "ean": ean}
        if kandidat:
            # Werte des verknüpften REWE-Produkts nicht kopieren: die View liest sie mit ihrer Quelle
            daten.update(naehrwerte=kandidat[2], naehrwert_quelle="rewe" if kandidat[4] else kandidat[0],
                         naehrwert_detail=kandidat[3])
        if gramm:
            daten.update(gramm_pro_stk=gramm["gramm"], gramm_quelle=gramm["quelle"], gramm_detail=gramm["detail"])
        gespeichert = vorrat.speichern(con, int(a["grocy_product_id"]), daten)
        erg.update(produkt=gespeichert["produkt"], naehrwerte_status=gespeichert["naehrwerte"],
                   gramm_status=gespeichert["gramm"], hinweise=gespeichert["hinweise"])
    return erg


def warteschlange_abarbeiten(con, max_anzahl: int = 50) -> dict:
    """Nachtjob: Anfragen, die am Open-Food-Facts-Limit gescheitert sind, erneut ermitteln (mit Speichern)."""
    offen = con.execute("""SELECT id, anfrage FROM off_warteschlange WHERE erledigt_at IS NULL
                           ORDER BY erstellt_at LIMIT %s""", (max_anzahl,)).fetchall()
    stat = {"offen": len(offen), "erledigt": 0, "wieder_limit": 0}
    for wid, anfrage in offen:
        erg = ermitteln(con, {**anfrage, "speichern": True, "bls_code": anfrage.get("bls_code")})
        if erg["warteschlange"]:
            con.execute("UPDATE off_warteschlange SET versuche = versuche + 1 WHERE id = %s", (wid,))
            stat["wieder_limit"] += 1
            break  # Limit greift noch: nicht weiter anfragen
        con.execute("UPDATE off_warteschlange SET erledigt_at = now(), versuche = versuche + 1 WHERE id = %s", (wid,))
        stat["erledigt"] += 1
    return stat
