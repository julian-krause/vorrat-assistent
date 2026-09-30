"""Offene Rückfragen: Freitext wird zuerst als Antwort ausgewertet, Menge ersetzt statt zu addieren."""

import pytest

from app import rueckfragen


@pytest.fixture()
def produkte_mit_groesse(test_db):
    with test_db.verbinden() as con:
        con.execute("""INSERT INTO rewe_products (rewe_product_id, name, brand, price, size_value, size_unit) VALUES
            ('3001', 'Bio Kefir Fruchtjoghurt Pfirsich 500g', 'Andechser', 1.49, 500, 'g'),
            ('3002', 'REWE Bio Kefir Natur 500g', 'REWE Bio', 1.19, 500, 'g'),
            ('3003', 'Bio Kefir mild', 'Molkerei', 1.39, NULL, NULL)""")
    return test_db


def _menge_frage(con, text="BIO KEFIR", name="Kefir", einheit="g", gramm_pro_stk=None, zeile=1):
    return rueckfragen.anlegen(con, "42", "menge", zeile, text, payload={"name": name, "einheit": einheit, "product_id": 7,
                                                                        "gramm_pro_stk": gramm_pro_stk, "mhd": "2026-10-10"})


def test_parse_menge():
    assert rueckfragen.parse_menge("ca. 500 g Kefir") == (500.0, "g", "ca kefir")
    assert rueckfragen.parse_menge("1,5 kg") == (1500.0, "g", "")
    assert rueckfragen.parse_menge("2 Stück Avocado")[:2] == (2.0, "stk")
    assert rueckfragen.parse_menge("1 l Milch")[:2] == (1000.0, "ml")
    assert rueckfragen.parse_menge("Kefir") is None
    assert rueckfragen.parse_menge("2 kg und 3 kg") is None


def test_menge_beantwortet(test_db):
    with test_db.verbinden() as con:
        assert rueckfragen.auswerten(con, "42", "500 g")["treffer"] is False     # nichts offen -> Agent
        rid = _menge_frage(con)
        erg = rueckfragen.auswerten(con, "42", "500 g Kefir")
        assert erg["aktion"] == "menge_buchen" and erg["menge"] == 500 and erg["einheit"] == "g" and erg["payload"]["product_id"] == 7
        assert rueckfragen.offene(con, "42") == []                                # beantwortet
        assert rueckfragen.auswerten(con, "42", "500 g")["treffer"] is False
        assert rid


def test_kein_treffer_geht_an_den_agenten(test_db):
    with test_db.verbinden() as con:
        _menge_frage(con)
        assert rueckfragen.auswerten(con, "42", "Was habe ich heute gegessen?")["treffer"] is False
        assert rueckfragen.auswerten(con, "42", "Ich habe heute 2 Eier mit Speck und Brot zum Frühstück gegessen")["treffer"] is False
        assert rueckfragen.auswerten(con, "99", "500 g")["treffer"] is False     # anderer Chat
        assert len(rueckfragen.offene(con, "42")) == 1


def test_abbrechen(test_db):
    with test_db.verbinden() as con:
        _menge_frage(con)
        _menge_frage(con, "INGWER", "Ingwer", zeile=2)
        erg = rueckfragen.auswerten(con, "42", "abbrechen")
        assert erg["aktion"] == "abbrechen" and erg["anzahl"] == 2 and rueckfragen.offene(con, "42") == []


def test_mehrere_offen(test_db):
    with test_db.verbinden() as con:
        _menge_frage(con)
        _menge_frage(con, "HAEHNCHENBRUST", "Hähnchenbrust", zeile=2)
        assert rueckfragen.auswerten(con, "42", "500 g")["aktion"] == "nachfragen"
        erg = rueckfragen.auswerten(con, "42", "Hähnchen 450 g")
        assert erg["aktion"] == "menge_buchen" and erg["bon_text"] == "HAEHNCHENBRUST" and erg["menge"] == 450
        assert len(rueckfragen.offene(con, "42")) == 1


def test_einheit_umrechnen(test_db):
    with test_db.verbinden() as con:
        _menge_frage(con, "AVOCADO", "Avocado", einheit="stk", gramm_pro_stk=200)
        assert rueckfragen.auswerten(con, "42", "300 g")["menge"] == 2      # g -> Stück
        _menge_frage(con, "REIS", "Reis", einheit="g", zeile=3)
        assert rueckfragen.auswerten(con, "42", "2 Stück")["aktion"] == "nachfragen"   # Stück ohne Gramm/Stück nicht ableitbar


def test_menge_ersetzt_bei_produktwahl(test_db):
    with test_db.verbinden() as con:
        rueckfragen.anlegen(con, "42", "produkt", 5, "BIO KEFIR", kandidaten=[{"rewe_product_id": "1"}],
                            payload={"name": "Bio Kefir", "einheit": "g", "grocy_id": 7, "gebucht": 445})
        erg = rueckfragen.auswerten(con, "42", "Kefir 500 g")
        assert erg["aktion"] == "menge_ersetzen" and erg["menge"] == 500 and erg["payload"]["gebucht"] == 445


def test_abgelaufen(test_db):
    with test_db.verbinden() as con:
        rid = _menge_frage(con)
        con.execute("UPDATE offene_rueckfragen SET laeuft_ab_at = now() - interval '1 hour' WHERE id = %s", (rid,))
        assert rueckfragen.offene(con, "42") == []


def test_produktwahl_bucht_nach_mit_packungsgroesse(produkte_mit_groesse):
    """Unsichere, noch nicht gebuchte Zeile: nach der Bestätigung greift die Packungsgröße des gewählten Produkts."""
    from app import bon
    with produkte_mit_groesse.verbinden() as con:
        erg = bon.zuordnen(con, "EUR\nBIO KEFIR 1,29 B\n SUMME EUR 1,29\nDatum: 30.09.2026\n", "b1")
        z = erg["zeilen"][0]
        assert z["status"] == "unsicher" and z["menge_info"]["offen"]
        rueckfragen.anlegen(con, "42", "produkt", z["zeile_id"], z["bon_text"], kandidaten=z["kandidaten"],
                            payload={"unbucht": True, "name": "Kefir", "einheit": "g", "product_id": 7})
        antwort = bon.antwort_speichern(con, z["zeile_id"], "3002")
        assert antwort["nachbuchen"]["menge"] == 500 and antwort["nachbuchen"]["einheit"] == "g"
        assert rueckfragen.offene(con, "42") == []


def test_produktwahl_ohne_packungsgroesse_fragt_menge(produkte_mit_groesse):
    from app import bon
    with produkte_mit_groesse.verbinden() as con:
        erg = bon.zuordnen(con, "EUR\nBIO KEFIR 1,29 B\n SUMME EUR 1,29\nDatum: 30.09.2026\n", "b2")
        z = erg["zeilen"][0]
        rueckfragen.anlegen(con, "42", "produkt", z["zeile_id"], z["bon_text"], kandidaten=z["kandidaten"],
                            payload={"unbucht": True, "name": "Kefir", "einheit": "g", "product_id": 7})
        antwort = bon.antwort_speichern(con, z["zeile_id"], "3003")       # Produkt ohne Größenangabe
        assert antwort.get("menge_nachfragen") and "nachbuchen" not in antwort
        assert [r["art"] for r in rueckfragen.offene(con, "42")] == ["menge"]


def _frage_mit_kandidaten(con, unbucht=False):
    ks = [{"rewe_product_id": "3002", "name": "REWE Bio Kefir Natur 500g"}, {"rewe_product_id": "3001", "name": "Bio Kefir Pfirsich 500g"}]
    return rueckfragen.anlegen(con, "42", "produkt", 9, "BIO KEFIR", kandidaten=ks,
                               payload={"name": "Kefir", "einheit": "g", "product_id": 7, "unbucht": unbucht, "gebucht": 0 if unbucht else 445})


def test_produktwahl_per_nummer_und_keins(produkte_mit_groesse):
    with produkte_mit_groesse.verbinden() as con:
        _frage_mit_kandidaten(con)
        erg = rueckfragen.auswerten(con, "42", "2")
        assert erg["aktion"] == "produkt_waehlen" and erg["rewe_product_id"] == "3001" and erg["bon_zeile_id"] == 9
        assert rueckfragen.auswerten(con, "42", "keins")["rewe_product_id"] is None
        assert rueckfragen.auswerten(con, "42", "5")["aktion"] == "nachfragen"


def test_produktwahl_katalogsuche_per_freitext(produkte_mit_groesse):
    with produkte_mit_groesse.verbinden() as con:
        _frage_mit_kandidaten(con)
        erg = rueckfragen.auswerten(con, "42", "Bio Kefir mild")
        assert erg["aktion"] == "kandidaten" and erg["kandidaten"][0]["rewe_product_id"] == "3003" and "1)" in erg["text"]
        assert rueckfragen.auswerten(con, "42", "1")["rewe_product_id"] == "3003"          # Nummer bezieht sich auf die neue Liste
        # Fragen und lange Sätze gehören dem Agenten
        _frage_mit_kandidaten(con)
        assert rueckfragen.auswerten(con, "42", "Wie viel Kefir habe ich noch?")["treffer"] is False
        assert rueckfragen.auswerten(con, "42", "Erzähl mir doch bitte was über die Vorteile von Kefir im Alltag")["treffer"] is False
        assert rueckfragen.auswerten(con, "42", "Xyzzy")["treffer"] is False               # nichts im Katalog: Agent


def test_menge_bei_unbuchter_produktwahl_fragt_produkt(produkte_mit_groesse):
    with produkte_mit_groesse.verbinden() as con:
        _frage_mit_kandidaten(con, unbucht=True)
        erg = rueckfragen.auswerten(con, "42", "500 g Kefir")           # beide Vorschläge heißen Kefir: Auswahl zeigen, Menge merken
        assert erg["aktion"] == "kandidaten" and erg["kandidaten"]
        wahl = rueckfragen.auswerten(con, "42", "2")
        assert wahl["aktion"] == "produkt_waehlen" and wahl["menge"] == 500 and wahl["einheit"] == "g"


def test_anderes_produkt_suchen_button(produkte_mit_groesse):
    from app import bon
    with produkte_mit_groesse.verbinden() as con:
        z = con.execute("INSERT INTO bon_zeilen (bon_id, kaufdatum, bon_text, bon_text_norm, status) VALUES ('b', current_date, 'BIO KEFIR', 'bio kefir', 'unsicher') RETURNING id").fetchone()[0]
        rueckfragen.anlegen(con, "42", "produkt", z, "BIO KEFIR", kandidaten=[], payload={"name": "Kefir", "einheit": "g"})
        antwort = bon.antwort_speichern(con, z, "s")
        assert antwort["suche"] and "Produktnamen" in antwort["text"]
        assert rueckfragen.offene(con, "42")[0]["payload"]["suche"] is True
        erg = rueckfragen.auswerten(con, "42", "Xyzzy")                                     # im Suchmodus wird auch „nichts gefunden“ beantwortet
        assert erg["treffer"] and erg["aktion"] == "nachfragen"
