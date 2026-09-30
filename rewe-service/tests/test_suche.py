"""Gemeinsame Normalisierung, Synonyme, Katalogsuche und Ranking der eBon-Zuordnung (Bon vom 30.09.2026, nachgebaut)."""

import pytest

from app import bls, bon, planer, text
from tests.test_bon import BON_0930


def test_normalisieren_beide_seiten_gleich():
    assert text.normalisieren("HAEHNCHENBRUST") == text.normalisieren("Hähnchenbrust") == "haehnchenbrust"
    assert text.normalisieren("Größe ÜBER Fuß") == "groesse ueber fuss"
    assert text.normalisieren("Crème brûlée") == "creme brulee"
    assert text.normalisieren("  ja! Broccoli-Röschen (1kg) ") == "ja broccoli roeschen 1kg"


def test_sql_und_python_normalisieren_gleich(test_db):
    proben = ["HAEHNCHENBRUST", "Hähnchenbrust", "Größe ÜBER Fuß", "Crème brûlée", "ja! Broccoli-Röschen (1kg)", "Ñandú Ýoghurt", ""]
    with test_db.verbinden() as con:
        for p in proben:
            assert con.execute("SELECT norm_text(%s)", (p,)).fetchone()[0] == text.normalisieren(p), p


KATALOG = [
    # id, name, marke, preis, größe, einheit, preis/kg, kategorie
    ("4001", "REWE Bio Kefir Natur 500g", "REWE Bio", 1.19, 500, "g", None, "Milchprodukte"),
    ("4002", "Bio Kefir Pfirsich 500g", "Andechser", 1.69, 500, "g", None, "Milchprodukte"),
    ("4003", "Kefir Drink Mango 250ml", "Ehrmann", 0.99, 250, "ml", None, "Milchprodukte"),
    ("4004", "Bio Kefir Zitrone 500g", "Bio-Molkerei", 1.79, 500, "g", None, "Milchprodukte"),
    ("4101", "Hähnchenbrustfilet 400g", "Wiesenhof", 4.49, 400, "g", 11.23, "Fleisch"),
    ("4102", "Hähnchen Brustfilet Bio 350g", None, 5.99, 350, "g", None, "Fleisch"),
    ("4201", "Ingwer 1kg", None, 4.99, 1000, "g", 4.99, "Obst & Gemüse"),
    ("4202", "Ingwer Shot Zitrone 60ml", "Frutania", 1.49, 60, "ml", None, "Getränke"),
    ("4203", "Ingwer Tee 20 Beutel", "Teekanne", 2.19, 40, "g", None, "Getränke"),
    ("4301", "Die Feinen Kartoffeln festkochend 2kg", None, 2.79, 2000, "g", 1.4, "Obst & Gemüse"),
    ("4302", "Pfanni Kartoffelknödel halb & halb 200g", "Pfanni", 1.79, 200, "g", None, "Grundnahrungsmittel"),
    ("4303", "Pfanni Kartoffelpüree 3 Portionen", "Pfanni", 1.29, 95, "g", None, "Grundnahrungsmittel"),
    ("4401", "Rheinfels Quelle Klassik 1l", "Rheinfels", 0.59, 1000, "ml", None, "Getränke"),
    ("4501", "Parmigiano Reggiano DOP 200g", None, 3.99, 200, "g", None, "Milchprodukte"),
    ("4502", "Reibekäse Parmesan 100g", "ja!", 1.29, 100, "g", None, "Milchprodukte"),
    ("4601", "ja! Broccoli Röschen tiefgefroren 1kg", "ja!", 2.29, 1000, "g", 2.29, "Tiefkühl"),
    ("4602", "Brokkoli-Cremesuppe 400ml", "Knorr", 1.59, 400, "ml", None, "Suppen"),
]


@pytest.fixture()
def katalog(test_db):
    with test_db.verbinden() as con:
        for pid, name, marke, preis, gr, einh, pkg, kat in KATALOG:
            con.execute("""INSERT INTO rewe_products (rewe_product_id, name, brand, price, size_value, size_unit, price_per_kg_or_l, category,
                                                       description)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (pid, name, marke, preis, gr, einh if einh in ("g", "ml") else None, pkg, kat,
                         "Natürliches Mineralwasser mit Kohlensäure versetzt" if pid == "4401" else None))
    return test_db


def _ids(liste):
    return [p["rewe_product_id"] for p in liste]


def test_synonyme_variante(katalog):
    with katalog.verbinden() as con:
        v = text.varianten(con, "Brokkoli Röschen")
        assert "broccoli roeschen" in v and "brokkoli roeschen" in v
        assert "huhnbrust" in text.varianten(con, "Hähnchenbrust")
        assert "parmigiano reggiano" in text.varianten(con, "Parmesan")
        assert "eier" in text.varianten(con, "Ei") and text.varianten(con, "Eis") == ["eis"]        # kurze Begriffe nur als ganzes Wort


def test_katalogsuche_brokkoli_findet_broccoli(katalog):
    with katalog.verbinden() as con:
        treffer = _ids(text.suche(con, "Brokkoli Röschen"))
        assert treffer[0] == "4601"                                   # „ja! Broccoli Röschen tiefgefroren 1kg“
        assert "4602" not in _ids(text.suche(con, "Brokkoli Röschen", 0.6))   # Suppe unter der Mindestschwelle
        assert _ids(text.suche(con, "Parmesan"))[:2] == ["4502", "4501"] or "4501" in _ids(text.suche(con, "Parmesan"))
        assert "4501" in _ids(text.suche(con, "Parmigiano")) and text.suche(con, "xyzabc") == []
        # Agenten-Werkzeug (SQL-Funktion produkt_suche) nutzt dieselbe Suche
        namen = [r[1] for r in con.execute("SELECT * FROM produkt_suche('Brokkoli Röschen', 5)")]
        assert namen[0] == "ja! Broccoli Röschen tiefgefroren 1kg"


def test_planer_kandidaten_brokkoli(katalog):
    with katalog.verbinden() as con:
        con.execute("UPDATE rewe_products SET last_seen = now()")
        assert planer.kandidaten(con, "Brokkoli Röschen")[0]["rewe_product_id"] == "4601"
        assert "4501" in _ids(planer.kandidaten(con, "Parmesan"))


def test_bls_synonyme(test_db):
    with test_db.verbinden() as con:
        namen = [e["name"].lower() for e in bls.suche(con, "Broccoli")]
        assert namen and any("brokkoli" in n or "broccoli" in n for n in namen)
        assert bls.suchwoerter("Hähnchen Brust") == ["haehnchen", "brust"]


def _zeile(bon_text, preis, kilopreis=None, gewicht=None):
    from decimal import Decimal
    return {"bon_text": bon_text, "anzahl": 1, "einzelpreis": Decimal(str(preis)) if kilopreis is None else None,
            "betrag": Decimal(str(preis)), "gewicht_kg": Decimal(str(gewicht)) if gewicht else None,
            "kilopreis": Decimal(str(kilopreis)) if kilopreis else None, "mwst": "B", "ignorieren": False}


def test_bon_0930_zuordnung(katalog):
    from datetime import date
    with katalog.verbinden() as con:
        # BIO KEFIR: Ladenpreis 1,29 gibt es im Katalog nicht -> Rückfrage, „REWE Bio Kefir Natur 500g“ unter den Top 3, vor den Geschmacksrichtungen
        kefir = bon.zeile_zuordnen(con, _zeile("BIO KEFIR", "1.49"), date(2026, 9, 30))
        assert kefir["status"] == "unsicher"
        ids = _ids(kefir["kandidaten"])
        assert "4001" in ids and ids[0] == "4001"
        assert not {"4002", "4003", "4004"} & set(ids[:1])

        # HAEHNCHENBRUST: mindestens ein passender Kandidat (früher: kein Treffer wegen ä/ae)
        h = bon.zeile_zuordnen(con, _zeile("HAEHNCHENBRUST", "4.45"), date(2026, 9, 30))
        assert h["status"] == "unsicher" and {"4101", "4102"} & set(_ids(h["kandidaten"]))

        # Ingwer (Gewichtsware, Preis pro kg weicht ab) -> loser Ingwer, nicht Shot/Tee
        ing = bon.zeile_zuordnen(con, _zeile("INGWER BIO", "0.17", kilopreis="4.90", gewicht="0.034"), date(2026, 9, 30))
        assert _ids(ing["kandidaten"])[0] == "4201" and not {"4202", "4203"} & set(_ids(ing["kandidaten"]))

        # Kartoffeln: nie Pfanni
        kar = bon.zeile_zuordnen(con, _zeile("DIE FEINEN KART.", "2.79"), date(2026, 9, 30))
        assert "4302" not in _ids(kar["kandidaten"]) and "4303" not in _ids(kar["kandidaten"])
        assert kar["status"] == "sicher" and kar["produkt"]["rewe_product_id"] == "4301"   # Preis 2,79 € und Text eindeutig
        # Frischware-Bonzeile ohne Frischware im Katalog schlägt kein Fertiggericht vor
        con.execute("DELETE FROM rewe_products WHERE rewe_product_id = '4301'")
        kar2 = bon.zeile_zuordnen(con, _zeile("DIE FEINEN KART.", "2.79"), date(2026, 9, 30))
        assert kar2["status"] == "keine" and kar2["kandidaten"] == []      # lieber „nichts gefunden“ als Pfanni-Püree

        # Parmesan findet Parmigiano
        par = bon.zeile_zuordnen(con, _zeile("PARMIGIANO REG.", "1.99"), date(2026, 9, 30))
        assert "4501" in _ids(par["kandidaten"])


def test_bon_0930_rheinfels_wird_nicht_gebucht(katalog):
    with katalog.verbinden() as con:
        erg = bon.zuordnen(con, "EUR\nRHEINFELS KLASSI 0,79 A\nBIO KEFIR 1,49 B\n SUMME EUR 2,28\nDatum: 30.09.2026\n",
                           "b-0930", ["RHEINFELS KLASSI", "BIO KEFIR"])
        assert erg["artikel"][0] == {"bon_text": "RHEINFELS KLASSI", "ignorieren": True, "grund": "Wasser"}
        assert [z["bon_text"] for z in erg["zeilen"]] == ["BIO KEFIR"]
        # auch ohne Wassermarke im Kassentext: alle Kandidaten sind Mineralwasser
        erg2 = bon.zuordnen(con, "EUR\nQUELLE KLASSIK 0,89 A\n SUMME EUR 0,89\nDatum: 30.09.2026\n", "b-0930b", ["QUELLE KLASSIK"])
        assert erg2["artikel"][0]["ignorieren"] and erg2["zeilen"] == []


def test_bonpreis_pro_markt_greift_beim_naechsten_einkauf(katalog):
    from datetime import date
    with katalog.verbinden() as con:
        erg = bon.zuordnen(con, "EUR\nKEFIR MILD 1,29 B\n SUMME EUR 1,29\nDatum: 30.09.2026\n Markt:0430 Kasse:1\n", "b-1")
        z = erg["zeilen"][0]
        bon.antwort_speichern(con, z["zeile_id"], "4001")
        p = con.execute("SELECT preis FROM bon_preise WHERE rewe_product_id = '4001' AND markt = '0430'").fetchone()
        assert p and float(p[0]) == 1.29
        # anderer Kassentext, gleicher Ladenpreis im selben Markt -> Preistreffer über den gemerkten Bonpreis
        treffer = bon._preis_kandidaten(con, __import__("decimal").Decimal("1.29"), date(2026, 10, 30), False, "0430")
        assert "4001" in _ids(treffer)
        assert "4001" not in _ids(bon._preis_kandidaten(con, __import__("decimal").Decimal("1.29"), date(2026, 10, 30), False, "9999"))


def test_rueckfrage_anzeige():
    from decimal import Decimal
    z = _zeile("INGWER BIO", "0.17", kilopreis="4.90", gewicht="0.034")
    assert bon.zeile_text(z) == "0,034 kg × 4,90 €/kg = 0,17 €" and "()" not in bon.zeile_text(z)
    assert bon.zeile_text(_zeile("BIO KEFIR", "1.49")) == "1,49 €"
    assert bon.zeile_text(dict(_zeile("AVOCADO", "2.38"), anzahl=2, einzelpreis=Decimal("1.19"))) == "2 Stk × 1,19 €"
    p = {"name": "Ingwer 1kg", "price": 4.99, "price_per_kg_or_l": 4.99, "size_value": 1000, "size_unit": "g"}
    assert bon.produkt_anzeige(p) == "Ingwer 1kg · 4,99 € · 4,99 €/kg · 1 kg"
    assert bon.produkt_anzeige({"name": "Bio Kefir", "price": None, "price_per_kg_or_l": None, "size_value": None, "size_unit": None}) == "Bio Kefir"


def test_zuordnen_liefert_anzeige_und_zeilentext(katalog):
    with katalog.verbinden() as con:
        erg = bon.zuordnen(con, BON_0930, "b-anzeige")
        z = {e["bon_text"]: e for e in erg["zeilen"]}
        assert z["INGWER BIO"]["zeile_text"] == "0,034 kg × 4,90 €/kg = 0,17 €"
        assert z["BIO KEFIR"]["kandidaten"][0]["anzeige"].startswith("REWE Bio Kefir Natur 500g · 1,19 € ·")
        assert all("()" not in e["zeile_text"] for e in erg["zeilen"])


def test_bls_zerlegt_zusammengesetzte_woerter(test_db):
    with test_db.verbinden() as con:
        assert bls.suche(con, "Cherry Romatomaten"), "Romatomaten -> Tomate"
        namen = [e["name"].lower() for e in bls.suche(con, "Cherry Romatomaten")]
        assert any("tomate" in n for n in namen), namen
        assert bls._wort_teile("romatomaten")[0].startswith("tomat") or "tomat" in "".join(bls._wort_teile("romatomaten"))
