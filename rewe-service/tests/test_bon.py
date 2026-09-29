"""eBon lesen und zuordnen – Artikelzeilen aus einem echten REWE-eBon (Markt 0430), ohne Zahlungsdaten."""

from datetime import date
from decimal import Decimal

import pytest

from app.bon import bon_lesen, normalisieren, textwert

BON = """ Catharina-Müller-Str. 4-8
 48159 Münster Nord
 UID Nr.: DE812706034
 EUR
HAHN.LYONER 2,19 B
EDELSALAMI 1,39 B
GOUDA SCHEIBEN 1,99 B
STEINOFENBROT 1,89 B
KIWI GOLD 0,89 B
AVOCADO VORGER. 2,38 B
 2 Stk x 1,19
BIO EIER HAHN 3,19 B
STREICHGUT UNGES 1,19 B
MINERALWASSER 0,89 A
PFAND 0,25 EURO 0,25 A *
BANANE 0,72 B
 0,524 kg x 1,39 EUR/kg
 --------------------------------------
 SUMME EUR 16,97
 Geg. EC-Cash EUR 16,97
Datum: 28.09.2026
 28.09.2026 19:14 Bon-Nr.:5404
 Markt:0430 Kasse:6 Bed.:432106
"""


def test_bon_lesen():
    b = bon_lesen(BON)
    assert b["datum"] == date(2026, 9, 28) and b["markt"] == "0430"
    zeilen = {z["bon_text"]: z for z in b["zeilen"]}
    assert list(zeilen)[:3] == ["HAHN.LYONER", "EDELSALAMI", "GOUDA SCHEIBEN"]
    assert zeilen["AVOCADO VORGER."]["anzahl"] == 2 and zeilen["AVOCADO VORGER."]["einzelpreis"] == Decimal("1.19")
    assert zeilen["BANANE"]["gewicht_kg"] == Decimal("0.524") and zeilen["BANANE"]["kilopreis"] == Decimal("1.39")
    assert zeilen["PFAND 0,25 EURO"]["ignorieren"] and zeilen["MINERALWASSER"]["ignorieren"]  # Wasser wird nie erfasst
    assert len(b["zeilen"]) == 11  # nichts nach SUMME


def test_textwert():
    assert normalisieren("Hähnchen-Lyoner") == "hahnchen lyoner"
    assert textwert("HAHN.LYONER", "Hähnchen-Lyoner 200g", "REWE Beste Wahl") == 1.0
    assert textwert("STREICHGUT UNGES", "Streichgut ungesalzen 250g", "ja!") == 1.0
    assert textwert("AVOCADO VORGER.", "Avocado vorgereift 1 Stück", None) == 1.0
    assert textwert("STEINOFENBROT", "Steinofen Brot 500g", "Harry") == 1.0
    assert textwert("GOUDA SCHEIBEN", "Gouda jung am Stück 400g", "ja!") == 0.5
    # Brot ist kein Brötchen – aber „HAHN.“ (mit Punkt abgekürzt) darf Hähnchen sein
    assert textwert("STEINOFENBROT", "Dinkel Steinofenbrötchen 300g", "Sinnack") == 0.0
    assert textwert("HAHN.LYONER", "Hähnchen-Lyoner 200g", None) == 1.0


@pytest.fixture()
def produkte(test_db):
    rows = [
        ("1001", "Hähnchen-Lyoner 200g", "REWE Beste Wahl", 2.19),
        ("1002", "Geflügel-Wiener 400g", "ja!", 2.19),
        ("1003", "Edelsalami 100g", "ja!", 1.39),
        ("1004", "Edel-Salami geschnitten 80g", "Gut & Günstig", 1.39),
        ("1005", "Gouda Scheiben 400g", "ja!", 3.49),
        ("1006", "Gouda jung in Scheiben 150g", "Hochland", 1.99),
        ("1007", "Avocado vorgereift 1 Stück", None, 1.19),
        ("1008", "Bananen 1kg", None, 1.39),
    ]
    with test_db.verbinden() as con:
        for pid, name, marke, preis in rows:
            con.execute("""INSERT INTO rewe_products (rewe_product_id, name, brand, price, size_value, size_unit, price_per_kg_or_l)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (pid, name, marke, preis, 1000 if pid == "1008" else None, "g" if pid == "1008" else None,
                         preis if pid == "1008" else None))
    return test_db


def test_zuordnen(produkte):
    from app import bon
    with produkte.verbinden() as con:
        erg = bon.zuordnen(con, BON, "bon-1", ["HAHN.LYONER", "Edelsalami", "AVOCADO VORGER.", "BANANE", "UNBEKANNT"])
        z = {e["bon_text"]: e for e in erg["zeilen"]}
        assert z["HAHN.LYONER"]["status"] == "sicher" and z["HAHN.LYONER"]["produkt"]["rewe_product_id"] == "1001"
        assert z["EDELSALAMI"]["status"] == "unsicher"
        assert {k["rewe_product_id"] for k in z["EDELSALAMI"]["kandidaten"]} == {"1003", "1004"}
        assert z["GOUDA SCHEIBEN"]["status"] == "sicher" and z["GOUDA SCHEIBEN"]["produkt"]["rewe_product_id"] == "1006"
        assert z["AVOCADO VORGER."]["produkt"]["rewe_product_id"] == "1007"
        assert z["BANANE"]["produkt"]["rewe_product_id"] == "1008"  # über den Kilopreis
        assert "MINERALWASSER" not in z
        # Reihenfolge der KI-Artikel, Groß-/Kleinschreibung egal, unbekannte -> None
        assert [a and a["bon_text"] for a in erg["artikel"]] == ["HAHN.LYONER", "EDELSALAMI", "AVOCADO VORGER.", "BANANE", None]

        # Rückfrage beantworten -> beim nächsten Bon sofort sicher
        antwort = bon.antwort_speichern(con, z["EDELSALAMI"]["zeile_id"], "1004")
        assert antwort["ok"] and antwort["produkt"]["brand"] == "Gut & Günstig" and antwort["anzahl"] == 1
        erg2 = bon.zuordnen(con, BON, "bon-2")
        z2 = {e["bon_text"]: e for e in erg2["zeilen"]}
        assert z2["EDELSALAMI"]["status"] == "sicher" and z2["EDELSALAMI"]["grund"] == "gelernt (bestätigt)"
        assert z2["EDELSALAMI"]["produkt"]["rewe_product_id"] == "1004"
        assert z2["HAHN.LYONER"]["grund"].startswith("gelernt")


def test_getrennte_zeilen():
    b = bon_lesen("EUR\nHAHN.LYONER\n2,19 B\nAVOCADO VORGER.\n2,38 B\n 2 Stk x 1,19\nPFAND 0,25 EURO\n0,25 A *\n SUMME EUR 4,82\n")
    assert [(z["bon_text"], str(z["einzelpreis"]), z["anzahl"]) for z in b["zeilen"]] == [
        ("HAHN.LYONER", "2.19", 1), ("AVOCADO VORGER.", "1.19", 2), ("PFAND 0,25 EURO", "0.25", 1)]


def test_planer_zutaten(test_db):
    from app import planer
    rows = [
        ("2001", "Arla Skyr Natur 450g", "Arla", 1.99, 450, "g"),
        ("2002", "Arla Skyr Erdbeere 450g", "Arla", 1.49, 450, "g"),
        ("2003", "ja! Skyr 500g", "ja!", 1.49, 500, "g"),
        ("2004", "Kölln Haferflocken Blütenzart 500g", "Kölln", 1.79, 500, "g"),
        ("2005", "ja! Haferflocken zart 500g", "ja!", 0.79, 500, "g"),
        ("2006", "Haferflocken-Riegel Schoko 4x25g", None, 1.29, 100, "g"),
    ]
    with test_db.verbinden() as con:
        for pid, name, marke, preis, groesse, einheit in rows:
            con.execute("INSERT INTO rewe_products (rewe_product_id, name, brand, price, size_value, size_unit) VALUES (%s,%s,%s,%s,%s,%s)",
                        (pid, name, marke, preis, groesse, einheit))
        con.execute("UPDATE rewe_products SET angebotspreis = 1.29, angebot_bis = current_date + 3 WHERE rewe_product_id = '2001'")
        erg = planer.zutaten_kandidaten(con, ["Skyr", "Haferflocken", "Drachenfrucht"])
    skyr = [p["rewe_product_id"] for p in erg["Skyr"]]
    assert skyr[0] == "2001" and erg["Skyr"][0]["im_angebot"]  # Angebot 1,29 € / 450 g schlägt ja! 1,49 € / 500 g
    assert "2002" not in skyr  # Erdbeere ist eine Variante
    assert erg["Haferflocken"][0]["rewe_product_id"] == "2005"  # günstigste schlichte Variante
    assert "2006" not in [p["rewe_product_id"] for p in erg["Haferflocken"]]  # kein Riegel
    assert erg["Drachenfrucht"] == []


def test_suchbegriffe():
    from app.planer import _suchbegriffe
    assert "eier" in _suchbegriffe("Ei")
    assert _suchbegriffe("Eis") == ["Eis"]  # „ei“ nur als ganzes Wort
    assert "vollkorn penne" in _suchbegriffe("Vollkornnudeln")
    assert "naturreis" in _suchbegriffe("Vollkornreis")


def test_wasser():
    from app.bon import ist_wasser
    for t in ["MINERALWASSER", "GEROLST.SPRUDEL", "Volvic Tafelwasser", "HEILWASSER STILL"]:
        assert ist_wasser(t), t
    for t in ["WASSERMELONE", "Kokoswasser", "HAHN.LYONER"]:
        assert not ist_wasser(t), t
