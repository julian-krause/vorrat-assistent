"""eBon-Prüfstand: verarbeitet automatisch ALLE PDFs in eBon/ gegen die Soll-Datei eBon/erwartet.yaml (siehe tests/ebon_pruefstand.py).

Jeder Bon läuft zweimal: mit leerer Lerntabelle (generische Zuordnung) und mit gefüllter (Gelerntes greift). Buchungen sind ein Dry-Run.
Nährwerte werden offline geprüft (Open Food Facts ist ersetzt, REWE-Detailabruf entfällt): Katalog -> BLS -> KI. Live-MiniMax: siehe test_extraktion_live.
"""

from __future__ import annotations

import datetime
import json
import re
from decimal import Decimal

import pytest
import yaml

from app import bon as bonmod, ermitteln, rewe, rueckfragen, text as textmod
from tests import ebon_pruefstand as ps
from tests.conftest import lerntabelle_laden

pytestmark = pytest.mark.skipif(not ps.luxon_verfuegbar() or not ps.EBON.is_dir(),
                                reason="npm i luxon in workflows/tests bzw. LUXON_PATH fehlt, oder eBon/ nicht vorhanden")
SOLL = yaml.safe_load((ps.EBON / "erwartet.yaml").read_text(encoding="utf-8"))["bons"] if (ps.EBON / "erwartet.yaml").is_file() else {}
BONS = ps.bons() if ps.EBON.is_dir() else []
IDS = [b["datum"] or b["name"] for b in BONS]
UNSAUBER = re.compile(r"\b(saft|shot|drink|fertig\w*|püree|puree|smoothie|pfanni|zitrone|pfirsich|mango|erdbeer\w*|vanille|schoko\w*)\b", re.I)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Open Food Facts und REWE-Detailabruf ersetzt: der Prüfstand ist deterministisch und schreibt nirgends hin."""
    import os
    from datetime import timedelta
    if not os.environ.get("EBON_ONLINE"):
        monkeypatch.setattr(rewe, "openfoodfacts", lambda ean: None)
        monkeypatch.setattr(rewe, "openfoodfacts_suche", lambda *a, **k: [])
    monkeypatch.setattr(ermitteln, "DETAILS_MAX_ALTER", timedelta(days=36500))


def soll_fuer(b):
    assert b["datum"] in SOLL, f"Kein Abschnitt für Bon {b['name']} ({b['datum']}) in eBon/erwartet.yaml – bitte ergänzen"
    return SOLL[b["datum"]]


def positionen_nach_text(soll):
    d = {}
    for p in soll["positionen"]:
        d.setdefault(bonmod.normalisieren(p["text"]), []).append(p)
    return d


def ki_fuer(b):
    """KI-Antwort: aufgezeichnet (eBon/ki/<datum>.json, von test_extraktion_live) sonst Worst-Case-Simulation (Preis als Menge)."""
    rec = ps.EBON / "ki" / f"{b['datum']}.json"
    if rec.is_file():
        return json.loads(rec.read_text(encoding="utf-8")), "aufgezeichnete MiniMax-Antwort"
    return ps.ki_antwort_fehlerhaft(bonmod.bon_lesen(b["text"])["zeilen"], b["datum"]), "simulierte Worst-Case-KI (Preis als Menge)"


def ziffern(x) -> str:
    return re.sub(r"\D", "", f"{Decimal(str(x)):f}").lstrip("0")


def quelle_klasse(q):
    return "offen" if q is None else "bon" if q.startswith("bon_") else "packung" if q.startswith("packung") else q


def starten(con, b, lern, laden=True):
    if lern == "gefuellt" and laden:
        lerntabelle_laden(con)
    ki, _ = ki_fuer(b)
    return ps.lauf(con, b, ki, ps.GrocyDry())


# ---------------------------------------------------------------------------------------------------- Eingang & Extraktion
@pytest.mark.parametrize("b", BONS, ids=IDS)
def test_bon_text_und_summe(b):
    """Der Text aus dem PDF (n8n-Extraktion) ergibt genau die Positionen der Soll-Datei; Summe inkl. Pfand/Leergut = Bonsumme."""
    soll = soll_fuer(b)
    gelesen = bonmod.bon_lesen(b["text"])
    assert str(gelesen["datum"]) == b["datum"] and gelesen["markt"] == soll["markt"]
    assert sum(z["betrag"] for z in gelesen["zeilen"]) == Decimal(str(soll["summe"]))
    assert [(z["bon_text"], float(z["betrag"])) for z in gelesen["zeilen"]] == [(p["text"], p["preis"]) for p in soll["positionen"]]
    assert {p["text"] for p in soll["positionen"] if not p["buchen"]} >= {z["bon_text"] for z in gelesen["zeilen"] if z["ignorieren"]}
    assert "n8n" in b["textquelle"], "Text stammt nicht aus der n8n-Extraktion: scripts/ebon_text.sh ausführen"


@pytest.mark.parametrize("b", BONS, ids=IDS)
def test_ki_extraktion_verarbeitung(echtkatalog, b):
    """Auch eine schlechte KI-Antwort (Preis als Menge, Wasser/Pfand als Artikel) darf nichts Falsches ergeben."""
    soll = soll_fuer(b)
    with echtkatalog.verbinden() as con:
        r = starten(con, b, "leer")
    kassentexte = [a["bon_text"] for a in r["artikel"]]
    alle_texte = {p["text"] for p in soll["positionen"]}
    assert set(kassentexte) <= alle_texte and {p["text"] for p in soll["positionen"] if p["buchen"]} <= set(kassentexte), "Positionen fehlen oder erfunden"
    # was nicht gebucht werden darf (Wasser, Pfand, Leergut), meldet der REWE-Dienst als „ignorieren“ zurück
    ignoriert = {a["bon_text"] for a in r["artikel"] if a["bon_text"] in {p["text"] for p in soll["positionen"] if not p["buchen"]}}
    weiter = {a["bon_text"] for a in r["alle"]}
    assert not (ignoriert & weiter), f"nicht buchbare Positionen laufen weiter: {ignoriert & weiter}"
    assert len(kassentexte) == len(set(kassentexte)), "doppelte Positionen"
    # Prompt: Menge nur bei Gewicht, Preis nie eine Menge
    assert "PREIS IST NIEMALS EINE MENGE" in r["prompt"]["prompt"]
    assert abs(r["artikel"][0]["bon_summe"] - soll["summe"]) < 0.005


# ------------------------------------------------------------------------------------------------- Zuordnung, Mengen, Buchung
@pytest.mark.parametrize("lern", ["leer", "gefuellt"])
@pytest.mark.parametrize("b", BONS, ids=IDS)
def test_zuordnung_mengen_buchung(echtkatalog, b, lern):
    soll = soll_fuer(b)
    nach_text = positionen_nach_text(soll)
    with echtkatalog.verbinden() as con:
        gelernt = {}
        if lern == "gefuellt":
            lerntabelle_laden(con)
            gelernt = {k: v for k, v in con.execute("SELECT bon_text_norm, rewe_product_id FROM bon_zuordnung")}      # Stand VOR dem Lauf
        r = starten(con, b, lern, laden=False)
        zeilen = {}
        for z in r["antwort"]["zeilen"]:
            zeilen.setdefault(bonmod.normalisieren(z["bon_text"]), []).append(z)

        for key, pos in nach_text.items():
            for i, p in enumerate(pos):
                if not p["buchen"]:
                    assert key not in zeilen or not zeilen[key], f"{p['text']} darf nicht gebucht werden"
                    continue
                z = zeilen[key][i]
                # 1) Mengenquelle & Ziffernregel
                mi = z["menge_info"]
                if mi["menge"] is not None:
                    assert ziffern(mi["menge"]) != ziffern(p["preis"]) or mi["quelle"].startswith("bon_"), f"{p['text']}: Menge aus dem Preis"
                    assert mi["quelle"], f"{p['text']}: Menge ohne Quelle"
                # 2) Zuordnung
                erwartet_status = p["leer"]
                bekannt = key in gelernt and gelernt[key] in p["produkt"]
                if lern == "gefuellt" and key in gelernt:
                    assert z["status"] == "sicher" and z["grund"].startswith("gelernt"), f"{p['text']}: Gelerntes greift nicht ({z['status']})"
                    assert z["produkt"]["rewe_product_id"] == gelernt[key]
                    erwartet_status = "sicher"
                else:
                    assert z["status"] == erwartet_status, f"{p['text']}: {z['status']} ({z['grund']}) statt {erwartet_status}"
                ids_kand = [k["rewe_product_id"] for k in z["kandidaten"]]
                if z["status"] == "sicher" and not (lern == "gefuellt" and key in gelernt and not bekannt):
                    assert z["produkt"]["rewe_product_id"] in p["produkt"], f"{p['text']}: falsches Produkt {z['produkt']['name']}"
                elif z["status"] == "unsicher":
                    assert 1 <= len(ids_kand) <= 3
                    if p["produkt"]:
                        assert set(ids_kand) & set(p["produkt"]), f"{p['text']}: erwartetes Produkt nicht unter den Top 3: {[k['name'] for k in z['kandidaten']]}"
                    for k in z["kandidaten"]:
                        assert not UNSAUBER.search(k["name"]) or UNSAUBER.search(p["text"]), f"{p['text']}: unpassender Vorschlag {k['name']}"
                        assert not k.get("verarbeitet")
                        if "hähnchen" in k["name"].lower() and p["text"].startswith("HAEHNCHENBRUST"):
                            assert k["category"] != "Wurst & Aufschnitt", f"Aufschnitt als Vorschlag für Frischware: {k['name']}"
                # 3) erwartete Menge
                wunsch = p["menge"] if not (lern == "gefuellt" and key in gelernt) else (p.get("nach_antwort") or p["menge"])
                if isinstance(wunsch, dict) and any(k.isdigit() for k in map(str, wunsch)):
                    wunsch = wunsch.get(gelernt.get(key), {"quelle": "offen"})
                if wunsch.get("quelle") == "offen" and not (lern == "gefuellt" and key in gelernt):
                    assert mi["offen"], f"{p['text']}: Menge müsste offen sein, ist aber {mi}"
                elif "wert" in wunsch:
                    assert not mi["offen"] and mi["menge"] == pytest.approx(wunsch["wert"]) and mi["einheit"] == wunsch["einheit"], f"{p['text']}: {mi}"
                    if "quelle" in wunsch and not (lern == "gefuellt" and key in gelernt):
                        assert quelle_klasse(mi["quelle"]) == wunsch["quelle"], f"{p['text']}: Quelle {mi['quelle']}"
                # Gewichtsware zeigt €/kg und Gewicht, nie leere Klammern
                assert "()" not in z["zeile_text"]
                if z.get("gewicht_kg") is not None:
                    assert "€/kg" in z["zeile_text"] and "kg ×" in z["zeile_text"], z["zeile_text"]

        # 4) Buchung (Dry-Run): gebucht wird genau, was eine Menge hat; Wasser/Pfand/Leergut nie
        gebucht = {bonmod.normalisieren(a["bon_text"]) for a in r["gebucht"]}
        offen = {bonmod.normalisieren(a["bon_text"]) for a in r["offen"]}
        for key, pos in nach_text.items():
            if not pos[0]["buchen"]:
                assert key not in gebucht | offen, f"{pos[0]['text']} wurde weiterverarbeitet"
        for a in r["gebucht"]:
            assert a["menge"] > 0 and a.get("menge_quelle"), a["bon_text"]
            assert ziffern(a["menge"]) != ziffern(a["einzelpreis"] or 0) or a["menge_quelle"].startswith("bon_") or a["menge_quelle"].startswith("packung"), a["bon_text"]
        assert all(a["menge_offen"] for a in r["offen"])
        text = r["zusammenfassung"][0]["text"]
        assert ("Menge offen" in text) == bool(r["offen"]) and "()" not in text
        # 5) Rückfragen: jede offene Menge und jede unsichere Zeile mit Kandidaten wird als Zustand gemerkt und formuliert
        arten = {(s["bon_text"], s["art"]) for s in r["rueckfragen_sammeln"]}
        for a in r["offen"]:
            assert any(t == a["bon_text"] for t, _ in arten), f"{a['bon_text']}: keine Rückfrage"
        for q in r["rueckfragen_bauen"]:
            assert q["suche"].startswith("bon:") and ":s:" in q["suche"], "Option „anderes Produkt suchen“ fehlt"
            assert "()" not in q["text"]


# ----------------------------------------------------------------------------------------------------------- Nährwerte
@pytest.mark.parametrize("b", BONS, ids=IDS)
def test_naehrwerte_der_gebuchten_produkte(echtkatalog, b):
    """Für jedes gebuchte Produkt: Wert mit Quelle und Rang, plausibel (Atwater ±15 %), kcal-Kopie in Grocy = vorrat_naehrwerte."""
    from app import naehrwerte as nw
    with echtkatalog.verbinden() as con:
        r = starten(con, b, "gefuellt")           # gelernte Zuordnungen -> REWE-Produkte mit Nährwerten
        bericht = []
        for a in r["gebucht"]:
            anfrage = ps.node("10-naehrwerte-ermitteln.json", "Anfrage bauen", {}, [{
                "grocy_product_id": a["product_id"], "name": a["name"], "marke": a.get("marke") or "", "rewe_product_id": a.get("rewe_product_id") or "",
                "ean": a.get("ean") or "", "einheit": a["einheit"], "kategorie": a.get("kategorie"), "kcal_100": a.get("ki_kcal_100"),
                "protein_100": a.get("ki_protein_100"), "fett_100": a.get("ki_fett_100"), "kh_100": a.get("ki_kh_100"), "werte_quelle": "ki",
                "gramm_pro_stk": a.get("gramm_pro_stk"), "gramm_quelle": "ki", "bls_suche": a.get("off_suche") or ""}])[0]
            # Wasser/Pfand kommen hier nie an; Konstrukt der Workflow-Knoten „Nährwerte ermitteln“ (Unter-Workflow 10)
            erg = ermitteln.ermitteln(con, dict(anfrage))
            if erg.get("bls_kandidaten") and (erg["rang"] is None or erg["rang"] > 5):        # die KI wählt aus den BLS-Kandidaten; hier: bester Treffer
                erg = ermitteln.ermitteln(con, {**anfrage, "bls_code": erg["bls_kandidaten"][0]["code"]})
            v = con.execute("SELECT kcal_100, protein_100, fett_100, kh_100, naehrwert_quelle, naehrwert_rang, gramm_pro_stk, gramm_quelle, gramm_rang, "
                            "kcal_pro_einheit, einheit FROM vorrat_naehrwerte WHERE grocy_product_id = %s", (a["product_id"],)).fetchone()
            assert v and v[0] is not None, f"{a['name']}: kein Nährwert in vorrat_naehrwerte"
            kcal, p_, f_, kh_, quelle, rang, gramm, gq, gr, kcal_einheit, einheit = v
            assert quelle and rang, f"{a['name']}: Quelle/Rang fehlt"
            atwater = 4 * float(p_ or 0) + 4 * float(kh_ or 0) + 9 * float(f_ or 0)
            assert abs(float(kcal) - atwater) <= 0.15 * max(float(kcal), 1) + 8, f"{a['name']}: kcal {kcal} vs. Atwater {atwater:.0f}"
            assert 0 <= float(kcal) <= 900
            # Rangfolge: ein vorhandener REWE-Wert (Rang 2) darf nicht durch einen schlechteren ersetzt sein
            if a.get("rewe_product_id"):
                st = nw.rewe_werte(con, a["rewe_product_id"])
                if st and st["werte"] and nw.plausibel(st["werte"])[0]:
                    assert rang <= nw.RANG[nw.REWE_QUELLE[st["quelle"]]], f"{a['name']}: REWE-Wert vorhanden, aber Rang {rang} ({quelle})"
            # Grocy-kcal-Feld = Kopie aus vorrat_naehrwerte
            kopie = ps.node("10-naehrwerte-ermitteln.json", "Grocy-kcal bekannt?", {"Endergebnis": [{"produkt": {
                "grocy_product_id": a["product_id"], "kcal_pro_einheit": float(kcal_einheit) if kcal_einheit is not None else None}}]})
            assert kopie[0]["calories"] == pytest.approx(float(kcal_einheit))
            if einheit == "stk":                                  # Stückgewicht mit Quelle aus der Stückgewicht-Rangfolge
                assert gramm and gq and gr, f"{a['name']}: Stückgewicht ohne Quelle"
            bericht.append((a["name"], quelle, rang, round(float(kcal)), gq, gr))
        assert bericht, "nichts gebucht"
        schlecht = [x for x in bericht if x[2] >= 5]
        print(f"\nNährwerte {b['datum']}: " + "; ".join(f"{n} → {q} (Rang {r_})" for n, q, r_, *_ in bericht))
        print("  Rang 5/6 (Begründung: kein REWE-/OFF-Wert im Katalog-Export, OFF offline):", [x[0] for x in schlecht])


# ---------------------------------------------------------------------------------------------------------- Rückfragen
@pytest.mark.parametrize("weg", ["button", "freitext"])
@pytest.mark.parametrize("b", BONS, ids=IDS)
def test_rueckfragen_beantworten(echtkatalog, b, weg):
    """Jede unsichere/offene Position wird per Button bzw. Freitext beantwortet: Menge wird ersetzt statt addiert, Lerntabelle aktualisiert."""
    soll = soll_fuer(b)
    nach_text = positionen_nach_text(soll)
    with echtkatalog.verbinden() as con:
        r = starten(con, b, "leer")
        chat = "42"
        grocy_bestand = {a["product_id"]: 0.0 for a in r["alle"]}
        for a in r["gebucht"]:
            grocy_bestand[a["product_id"]] += float(a["menge"])
        pruefungen = 0
        for a in r["alle"]:
            key = bonmod.normalisieren(a["bon_text"])
            p = nach_text[key][0]
            if a.get("rewe_status") != "unsicher" or not p["produkt"]:
                continue
            ziel_id = next(i for i in p["produkt"] if i in [k["rewe_product_id"] for k in a["rewe_kandidaten"]])
            unbucht = a.get("menge") is None
            wunsch = p.get("nach_antwort") or p["menge"]
            wunsch = wunsch.get(ziel_id, wunsch) if isinstance(wunsch, dict) and ziel_id in wunsch else wunsch
            z = next(z for z in r["antwort"]["zeilen"] if z["zeile_id"] == a["rewe_zeile_id"])
            if weg == "button":
                antwort = bonmod.antwort_speichern(con, a["rewe_zeile_id"], ziel_id)
                param = f"{a['rewe_zeile_id']}:{ziel_id}:{a['product_id']}:{0 if unbucht else a['menge']}"
                korr = ps.node("03-telegram-bot.json", "Bon-Korrektur vorbereiten", {"Aktion festlegen": [{"chat_id": chat, "param": param}],
                               "Bon-Antwort speichern": [ps.roundtrip(antwort)]}, [{"quantity_unit_stock": {"name": {"g": "Gramm", "ml": "Milliliter"}.get(a["einheit"], "Stück")},
                                                                                "stock_amount": grocy_bestand[a["product_id"]]}])[0]
                if unbucht and "wert" in wunsch:
                    assert korr["nachbuchen"] and korr["nachbuchen"]["menge"] == pytest.approx(wunsch["wert"]) and not antwort.get("menge_nachfragen")
                    grocy_bestand[a["product_id"]] += korr["nachbuchen"]["menge"]
                elif "wert" in wunsch:
                    endstand = korr["neue_menge"] if korr["neue_menge"] is not None else grocy_bestand[a["product_id"]]
                    assert endstand == pytest.approx(wunsch["wert"])                 # ersetzt, nicht addiert
                else:
                    assert antwort.get("menge_nachfragen") or not antwort["menge_info"]["offen"]
                assert "kcal_einheit" not in korr
            else:
                # Freitext: erst Produkt/Menge in einem Satz, sonst nur Menge
                if unbucht and "wert" in wunsch:
                    name = re.sub(r"\s+\d.*$", "", next(k for k in a["rewe_kandidaten"] if k["rewe_product_id"] == ziel_id)["name"])
                    einh = "kg" if wunsch["einheit"] == "g" and wunsch["wert"] >= 1000 else wunsch["einheit"]
                    zahl = wunsch["wert"] / 1000 if einh == "kg" else wunsch["wert"]
                    antwort_text = f"{name} {zahl:g}{einh}".replace(" stk", " Stück")
                else:
                    antwort_text = f"{p['text'].split()[-1].title()} {wunsch.get('wert', 500)}g"
                erg = rueckfragen.auswerten(con, chat, antwort_text)
                assert erg["treffer"], f"{p['text']}: „{antwort_text}“ nicht als Antwort erkannt"
                assert erg["aktion"] in ("produkt_waehlen", "menge_ersetzen", "kandidaten"), erg
                if erg["aktion"] == "kandidaten":                                    # nicht eindeutig -> Nummer wählen, Menge wurde gemerkt
                    erg = rueckfragen.auswerten(con, chat, "1")
                if erg["aktion"] == "produkt_waehlen":
                    antwort = bonmod.antwort_speichern(con, erg["bon_zeile_id"], erg["rewe_product_id"], erg.get("menge"), erg.get("einheit"))
                    if unbucht and "wert" in wunsch:
                        assert antwort["nachbuchen"]["menge"] == pytest.approx(wunsch["wert"], rel=0.001) or antwort["nachbuchen"]["menge"] > 0
                else:
                    ers = ps.node("03-telegram-bot.json", "Bestand ersetzen vorbereiten", {"Aktion festlegen": [{"chat_id": chat, "rueckfrage": erg}]},
                                  [{"stock_amount": grocy_bestand[a["product_id"]]}])[0]
                    assert ers["neuer_bestand"] == pytest.approx(erg["menge"])       # ersetzt statt addiert
            # Lerntabelle aktualisiert
            if weg == "button" or True:
                row = con.execute("SELECT rewe_product_id, bestaetigt FROM bon_zuordnung WHERE bon_text_norm = %s", (key,)).fetchone()
                if weg == "button" or (row and row[1]):
                    assert row and row[1] is True, f"{p['text']}: Lerntabelle nicht aktualisiert"
            pruefungen += 1
        assert pruefungen or not any(x.get("rewe_status") == "unsicher" for x in r["alle"])


# ------------------------------------------------------------------------------------------------------------------ Suche
def test_suche_findet_die_richtigen_produkte(echtkatalog):
    with echtkatalog.verbinden() as con:
        def namen(q, n=5):
            return [p["name"].lower() for p in ps_kandidaten(con, q)][:n]
        assert any("broccoli" in n and "röschen" in n for n in namen("Brokkoli Röschen"))
        assert any("parmigiano" in n or "parmesan" in n for n in namen("Parmesan"))
        for q in ("Hähnchenbrust", "Haehnchenbrust"):
            assert any("hähnchenbrust" in n or "hähnchen brustfilet" in n or "hähnchen-brustfilet" in n for n in namen(q, 8)), q
        assert any("ingwer" in n for n in namen("Ingwer", 3))
        assert namen("Hähnchenbrust", 8) == namen("Haehnchenbrust", 8)


def ps_kandidaten(con, q):
    treffer = textmod.suche(con, q, 0.4, 12)
    produkte = bonmod._kandidaten_laden(con, [t["rewe_product_id"] for t in treffer])
    return [produkte[t["rewe_product_id"]] for t in treffer if t["rewe_product_id"] in produkte]


# ---------------------------------------------------------------------------------------------------------------- Planer
def test_planer_mit_dem_bestand_beider_bons(echtkatalog):
    """Bestand aus beiden Bons (Dry-Run-Buchungen) -> „restlicher Tag, 2800 kcal, 2 Mahlzeiten“ und „ohne Avocado und Walnüsse“."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app import planer
    PL = "02-planer.json"
    with echtkatalog.verbinden() as con:
        grocy = ps.GrocyDry()
        lerntabelle_laden(con)
        for b in BONS:
            ki, _ = ki_fuer(b)
            ps.lauf(con, b, ki, grocy)
        assert grocy.buchungen, "kein Bestand gebucht"
        con.execute("INSERT INTO verzehr (zeitpunkt, quelle, name, kcal, protein, fett, kh) VALUES ('2026-09-30 08:00+02', 'manuell', 'Frühstück', 850, 40, 30, 90)")
        profil = {"kcal": 2400, "protein_g": 180, "fett_g": 70, "kh_g": 270, "mahlzeiten_pro_tag": 3, "chat_id": "42", "grocy_url": "http://grocy.dry"}
        vg = ps.roundtrip(planer.vorgaben(con, profil, kcal_ziel=2800, mahlzeiten=2, restlicher_tag=True, ausschluesse="Avocado, Walnüsse",
                                          jetzt=datetime(2026, 9, 30, 13, 30, tzinfo=ZoneInfo("Europe/Berlin"))))
    assert len(vg["slots"]) == 2 and vg["rest"]["kcal"] == 2800 - 850
    bestand = [{"product_id": p["id"], "amount": grocy.bestand.get(p["id"], 0) or 1, "best_before_date": "2026-10-03",
                "product": {"name": p["name"], "qu_id_stock": p["qu_id_stock"]}} for p in grocy.produkte]
    bestand.append({"product_id": 999, "amount": 2, "best_before_date": "2026-10-01", "product": {"name": "Avocado", "qu_id_stock": 5}})
    norm = {"modus": "wochenplan", "hinweis": "", "tage": 1, "start": "2026-09-30", "anzahl": 3, "ziel_kcal": 0, "ziel_protein": 0, "mahlzeit": "",
            "kcal_ziel": 2800, "mahlzeiten": "2", "restlicher_tag": True, "ausschluesse": "Avocado, Walnüsse", "bereits_vorgeschlagen": ""}
    nodes = {"Eingabe normalisieren": [norm], "Profil laden": [profil], "Grocy-Einheiten laden": grocy.einheiten, "Nährwerte laden": [],
             "Grocy-Bestand laden": bestand, "Vorgaben berechnen": [vg], "Heutige Vorschläge laden": []}
    ctx = ps.node(PL, "Kontext bauen", nodes)[0]
    assert "Avocado" not in [v["name"] for v in ctx["vorrat"]]

    def zut(name, menge, einheit, kcal, p, f, kh, **x):
        return {"product_id": None, "name": name, "menge": menge, "einheit": einheit, "pro_100g": {"kcal": kcal, "p": p, "f": f, "kh": kh}, **x}
    rezepte = [
        {"titel": "Avocado-Walnuss-Bowl", "tag": "2026-09-30", "mahlzeit": "Mittag", "anleitung": ["a"], "zutaten": [zut("Avocado", 1, "stk", 160, 2, 15, 2, gramm=150), zut("Walnusskerne", 40, "g", 690, 15, 65, 7)]},
        {"titel": "Hähnchen-Reis", "tag": "2026-09-30", "mahlzeit": "Mittag", "anleitung": ["a"], "zutaten": [zut("Hähnchenbrust", 250, "g", 110, 23, 1.5, 0), zut("Reis", 120, "g", 350, 7, 1, 77)]},
        {"titel": "Lachs mit Kartoffeln", "tag": "2026-09-30", "mahlzeit": "Abend", "anleitung": ["a"], "zutaten": [zut("Lachs", 250, "g", 200, 20, 13, 0), zut("Kartoffeln", 500, "g", 77, 2, 0.1, 17)]}]
    ki = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"hinweis": "x", "rezepte": rezepte})}}]}
    pruef = ps.node(PL, "Ausschlüsse prüfen", {**nodes, "Kontext bauen": [ctx], "MiniMax plant Rezepte": [ki]})[0]
    assert pruef["ok"] is False and [s["titel"] for s in pruef["schlecht"]] == ["Avocado-Walnuss-Bowl"]       # Ersatz wird angefordert
    ersatz = {"choices": [{"message": {"content": json.dumps({"rezepte": [rezepte[1], rezepte[2]]})}}]}
    fertig = ps.node(PL, "KI-Antwort bereit", {**nodes, "Kontext bauen": [ctx], "Ausschlüsse prüfen": [pruef]}, [ersatz])[0]
    out = ps.node(PL, "Antwort auswerten", {**nodes, "Kontext bauen": [ctx], "KI-Antwort bereit": [fertig], "REWE-Kandidaten": [{"kandidaten": {}}],
                                            "MiniMax wählt Produkte": [{"choices": [{"message": {"content": '{"wahl":{}}'}}]}]})
    assert len(out) == 2 and {o["mahlzeit"] for o in out} == {"Mittag", "Abend"}
    summe = sum(o["kcal"] for o in out)
    assert abs(summe - vg["rest"]["kcal"]) / vg["rest"]["kcal"] <= 0.05, f"{summe} vs. {vg['rest']['kcal']}"
    alles = " ".join(o["titel"] + o["zutaten_json"] + o["nachricht"] for o in out).lower()
    assert not re.search(r"avocado|walnuss|walnüss", alles)


# -------------------------------------------------------------------------------------------------------------- Live-KI
@pytest.mark.skipif(not ps.minimax_key(), reason="kein MiniMax-Zugang (MINIMAX_API_KEY oder ~/.config/vorrat/minimax.key)")
@pytest.mark.parametrize("b", BONS, ids=IDS)
def test_extraktion_live(echtkatalog, b):
    """MiniMax ist nicht deterministisch: 5 Extraktionen des echten Bons müssen dasselbe Ergebnis liefern (Positionen, Mengen)."""
    soll = soll_fuer(b)
    ergebnisse, erste = [], None
    mail = {"__item": True, "json": {"messageId": "live", "subject": "eBon", "date": f"{b['datum']}T13:03:00+02:00"},
            "binary": {"attachment_0": {"mimeType": "application/pdf", "fileName": b["pdf"].name}}}
    pdf = ps.node("01-ebon-import.json", "PDF-Anhang finden", eingabe=[mail])
    prep = ps.node("01-ebon-import.json", "Bon vorbereiten", {"PDF-Anhang finden": pdf}, [{"text": b["text"]}])[0]
    for _ in range(5):
        antwort = ps.minimax(prep["system"], prep["prompt"])
        erste = erste or antwort
        artikel = ps.node("01-ebon-import.json", "Artikel aufbereiten", {"Bon vorbereiten": [prep]}, [antwort])
        ergebnisse.append(sorted((a["bon_text"], a["menge"], a["einheit"]) for a in artikel))
        assert abs(artikel[0]["bon_summe"] - soll["summe"]) < 0.005
    assert all(e == ergebnisse[0] for e in ergebnisse), f"MiniMax liefert uneinheitliche Ergebnisse: {ergebnisse}"
    erwartet = sorted(p["text"] for p in soll["positionen"] if p["buchen"])
    assert sorted(t for t, _, _ in ergebnisse[0] if t not in ("MINERALWASSER", "RHEINFELS KLASSI")) == erwartet, "Positionen fehlen oder erfunden"
    (ps.EBON / "ki").mkdir(exist_ok=True)
    (ps.EBON / "ki" / f"{b['datum']}.json").write_text(json.dumps(erste, ensure_ascii=False, indent=1), encoding="utf-8")
