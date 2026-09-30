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
    assert normalisieren("Hähnchen-Lyoner") == "haehnchen lyoner"
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


def test_wasser_ueber_rewe_produkt(test_db):
    """Kassentext ohne „Wasser“: erkannt über Kategorie + Beschreibung des zugeordneten REWE-Produkts."""
    from app import bon
    with test_db.verbinden() as con:
        con.execute("""INSERT INTO rewe_products (rewe_product_id, name, category, description, price) VALUES
            ('6200095', 'Rheinfels Quelle Klassik 1l', 'Getränke', 'Natürliches Mineralwasser mit Kohlensäure versetzt', 0.59),
            ('7814109', 'ja! Kichererbsen 265g', 'Vorratsküche', 'Kichererbsen in Wasser, Salz', 0.79)""")
        text = "EUR\nRHEINFELS KLASSI 0,59 A\nKICHERERBSEN 0,79 B\n SUMME EUR 1,38\nDatum: 30.09.2026\n"
        erg = bon.zuordnen(con, text, "bon-w", ["RHEINFELS KLASSI", "KICHERERBSEN"])
        assert erg["artikel"][0] == {"bon_text": "RHEINFELS KLASSI", "ignorieren": True, "grund": "Wasser"}
        assert erg["artikel"][1]["produkt"]["rewe_product_id"] == "7814109"     # „in Wasser“ in der Beschreibung zählt nicht
        assert [z["bon_text"] for z in erg["zeilen"]] == ["KICHERERBSEN"]


# --- Mengen (Punkt 1) --------------------------------------------------------------------------------------------
# Echter eBon vom 30.09.2026 (eBon/REWE-ebon-1.pdf; 13 Lebensmittelpositionen, Summe 22,45 € inkl. Pfand/Leergut), ohne Zahlungsdaten
BON_0930 = """ EUR
HAEHNCHENBRUST 4,45 B
PARMIGIANO REG. 1,99 B
KIWI GOLD 1,78 B
 2 Stk x 0,89
INGWER BIO 0,17 B
 0,034 kg x 4,90 EUR/kg
DIE FEINEN KART. 2,79 B
ZWIEBEL BRAVOS 1,19 B
CHERRYROMATOMATE 1,19 B
PAPRIKA ROT SP. 2,49 B
BIO EIER HAHN 3,19 B
BIO KEFIR 1,49 B
BIO KOKOSMILCH 1,59 B
KICHERERBSEN 0,59 B
RHEINFELS KLASSI 0,79 A
PFAND 0,25 EURO 0,25 A *
LEERGUT EINWEG -0,25 A *
LEERGUT EINWEG -1,25 A *
 5 Stk x 0,25
 --------------------------------------
 SUMME EUR 22,45
Datum: 30.09.2026
 Markt:0430 Kasse:6 Bed.:432106
"""


def test_bon_0930_mengen_nie_aus_dem_preis():
    from app.bon import ki_menge_pruefen, menge_bestimmen
    b = bon_lesen(BON_0930)
    assert sum(z["betrag"] for z in b["zeilen"]) == Decimal("22.45")
    essen = [z for z in b["zeilen"] if not z["ignorieren"]]
    assert len(essen) == 13 and len(b["zeilen"]) == 16          # 13 Positionen + Pfand + 2× Leergut
    for z in essen:
        info = menge_bestimmen(z)  # ohne Produkttreffer
        preis = str(z["betrag"]).replace(".", "").lstrip("0")
        if z["gewicht_kg"] is None and z["anzahl"] == 1:
            assert info["offen"] and info["menge"] is None, z["bon_text"]  # nicht raten
        else:
            assert not info["offen"] and str(int(info["menge"])) != preis, z["bon_text"]
    z = {x["bon_text"]: x for x in essen}
    assert menge_bestimmen(z["INGWER BIO"])["menge"] == 34 and menge_bestimmen(z["INGWER BIO"])["quelle"] == "bon_gewicht"
    assert menge_bestimmen(z["KIWI GOLD"]) == {"menge": 2.0, "einheit": "stk", "quelle": "bon_stueck", "offen": False}
    # KI sagt 445 g bei 4,45 € und ohne Gewicht auf dem Bon -> verworfen
    assert ki_menge_pruefen(z["HAEHNCHENBRUST"], 445, "g") == (None, "Ziffern entsprechen dem Preis")
    assert ki_menge_pruefen(z["HAEHNCHENBRUST"], 500, "g") == (None, "kein Gewicht auf dem Bon")
    assert ki_menge_pruefen(z["BIO KEFIR"], 149, "g")[0] is None and ki_menge_pruefen(z["BIO KEFIR"], 500, "g")[0] is None
    assert ki_menge_pruefen(z["INGWER BIO"], 17, "g") == (None, "Ziffern entsprechen dem Preis")   # 0,17 €
    assert ki_menge_pruefen(z["INGWER BIO"], 34, "g") == (34.0, "ok")


def test_menge_rangfolge():
    from app.bon import menge_bestimmen
    packung = {"size_value": 500.0, "size_unit": "g"}
    zeile = {"bon_text": "BIO KEFIR", "anzahl": 2, "einzelpreis": Decimal("1.29"), "betrag": Decimal("2.58"), "gewicht_kg": None, "kilopreis": None}
    assert menge_bestimmen(zeile, packung, "sicher") == {"menge": 1000.0, "einheit": "g", "quelle": "packung_sicher", "offen": False}
    assert menge_bestimmen(zeile, packung, "bestaetigt")["quelle"] == "packung_bestaetigt"  # greift auch nach der Rückfrage
    assert menge_bestimmen(zeile, {"size_value": 1, "size_unit": "Stück"})["einheit"] == "stk"
    gewogen = dict(zeile, anzahl=1, gewicht_kg=Decimal("0.106"), kilopreis=Decimal("3.99"))
    assert menge_bestimmen(gewogen, packung)["menge"] == 106  # Gewicht vom Bon schlägt Packungsgröße
    assert menge_bestimmen(dict(zeile, bon_text="MILCH 1L", anzahl=1))["menge"] == 1000  # explizite Angabe im Kassentext
    assert menge_bestimmen(zeile) == {"menge": 2.0, "einheit": "stk", "quelle": "bon_stueck", "offen": False}
    assert menge_bestimmen(dict(zeile, anzahl=1))["offen"]


def test_menge_info_im_ergebnis(produkte):
    from app import bon
    with produkte.verbinden() as con:
        con.execute("UPDATE rewe_products SET size_value = 200, size_unit = 'g' WHERE rewe_product_id = '1001'")
        con.execute("UPDATE rewe_products SET size_value = 100, size_unit = 'g' WHERE rewe_product_id = '1003'")
        erg = bon.zuordnen(con, BON, "bon-m")
        z = {e["bon_text"]: e for e in erg["zeilen"]}
        assert z["HAHN.LYONER"]["menge_info"]["quelle"] == "packung_sicher" and z["HAHN.LYONER"]["menge_info"]["menge"] == 200
        assert z["EDELSALAMI"]["status"] == "unsicher" and z["EDELSALAMI"]["menge_info"]["offen"]  # nicht raten
        assert z["BANANE"]["menge_info"] == {"menge": 524.0, "einheit": "g", "quelle": "bon_gewicht", "offen": False}
        antwort = bon.antwort_speichern(con, z["EDELSALAMI"]["zeile_id"], "1003")
        assert antwort["menge_info"]["quelle"] == "packung_bestaetigt" and antwort["menge_info"]["menge"] == 100
        assert bon.zuordnen(con, BON, "bon-m2")["zeilen"][1]["menge_info"]["quelle"] == "packung_gelernt"
