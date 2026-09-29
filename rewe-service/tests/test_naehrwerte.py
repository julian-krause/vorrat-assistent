"""Nährwert-Regeln: Plausibilität, leer überschreibt nie, Rangfolge, Verlauf, 20-%-Meldung, Einzelabruf."""

import pytest

from app import naehrwerte as nw

BUTTER = {"kcal": 589, "protein": 0.4, "fett": 65, "kh": 0.5}


@pytest.mark.parametrize("werte, ok", [
    (BUTTER, True),
    ({"kcal": 720, "protein": 0.5, "fett": 80, "kh": 0.5}, True),        # KI-Schätzung Streichgut: in sich stimmig
    ({"kcal": 220, "protein": 7.1, "fett": 1.5, "kh": 42, "ballaststoffe": 6}, True),
    ({"kcal": 12, "protein": 0.6, "fett": 0.1, "kh": 1.8}, True),         # Gurke: Rundung, Mindesttoleranz
    ({"kcal": 58.9, "protein": 0.4, "fett": 65, "kh": 0.5}, False),       # kcal pro Portion statt pro 100 g
    ({"kcal": 400, "protein": 60, "fett": 20, "kh": 30}, False),          # über 100 g
    ({"kcal": 589, "protein": 0.4, "fett": 65}, False),                   # unvollständig
    (None, False),
])
def test_plausibel(werte, ok):
    assert nw.plausibel(werte)[0] is ok


def test_plausibel_sql_wie_python(test_db):
    faelle = [BUTTER, {"kcal": 58.9, "protein": 0.4, "fett": 65, "kh": 0.5}, {"kcal": 12, "protein": 0.6, "fett": 0.1, "kh": 1.8},
              {"kcal": 400, "protein": 60, "fett": 20, "kh": 30}, {"kcal": 220, "protein": 7.1, "fett": 1.5, "kh": 42, "ballaststoffe": 6}]
    with test_db.verbinden() as con:
        for w in faelle:
            sql = con.execute("SELECT naehrwerte_plausibel(%s::numeric, %s::numeric, %s::numeric, %s::numeric, %s::numeric)",
                              (w["kcal"], w["protein"], w["fett"], w["kh"], w.get("ballaststoffe"))).fetchone()[0]
            assert sql is nw.plausibel(w)[0], w


def test_abweichungen():
    assert nw.abweichungen(BUTTER, {**BUTTER, "kcal": 720, "fett": 80}) == {"kcal": (589, 720), "fett": (65, 80)}
    assert nw.abweichungen({"kcal": 50, "protein": 0.5, "fett": 0.5, "kh": 10}, {"kcal": 52, "protein": 0.7, "fett": 0.4, "kh": 10}) == {}


@pytest.fixture()
def produkt(test_db):
    with test_db.verbinden() as con:
        con.execute("INSERT INTO rewe_products (rewe_product_id, name, grammage_raw) VALUES ('2662082', 'ja! Streichgut ungesalzen 250g', '250g')")
    return test_db


def _verlauf(con):
    return con.execute("SELECT kcal_100::float8, quelle FROM rewe_naehrwert_verlauf ORDER BY id").fetchall()


def test_rewe_speichern(produkt):
    with produkt.verbinden() as con:
        assert nw.rewe_speichern(con, "2662082", {**BUTTER, "salz": 0.02}, "rewe") == "neu"
        assert nw.rewe_speichern(con, "2662082", {**BUTTER}, "rewe") == "unveraendert"      # Salz fehlt: bleibt, kein neuer Verlauf
        assert nw.rewe_werte(con, "2662082")["werte"]["salz"] == pytest.approx(0.02)
        # leer überschreibt nie
        assert nw.rewe_speichern(con, "2662082", None, "rewe") == "leer"
        assert nw.rewe_speichern(con, "2662082", {"kcal": None, "fett": ""}, "rewe") == "leer"
        # schlechtere Quelle (Open Food Facts) überschreibt REWE nie
        assert nw.rewe_speichern(con, "2662082", {"kcal": 700, "protein": 1, "fett": 77, "kh": 0.5}, "openfoodfacts") == "schlechter"
        # unplausibel: nicht übernommen, gemeldet
        assert nw.rewe_speichern(con, "2662082", {**BUTTER, "kcal": 58.9}, "rewe") == "unplausibel"
        assert nw.rewe_werte(con, "2662082")["werte"]["kcal"] == 589
        assert _verlauf(con) == [(589, "rewe")]
        assert con.execute("SELECT art FROM meldungen").fetchall() == [("unplausibel",)]


def test_abweichung_20_prozent(produkt):
    with produkt.verbinden() as con:
        nw.rewe_speichern(con, "2662082", BUTTER, "rewe")
        # gleicher Name, gleiche Größe, +22 % kcal -> speichern und melden
        assert nw.rewe_speichern(con, "2662082", {"kcal": 720, "protein": 0.5, "fett": 80, "kh": 0.5}, "rewe") == "geaendert"
        assert nw.rewe_werte(con, "2662082")["werte"]["kcal"] == 720
        meldung = con.execute("SELECT art, text FROM meldungen").fetchone()
        assert meldung[0] == "abweichung" and "kcal 589 → 720" in meldung[1]
        # neue Rezeptur mit neuem Namen/Größe: keine Meldung
        con.execute("UPDATE rewe_products SET name = 'ja! Streichgut ungesalzen 200g', grammage_raw = '200g'")
        assert nw.rewe_speichern(con, "2662082", BUTTER, "rewe") == "geaendert"
        assert con.execute("SELECT count(*) FROM meldungen").fetchone()[0] == 1
        assert [k for k, _ in _verlauf(con)] == [589, 720, 589]
        vid = con.execute("SELECT naehrwert_verlauf_id FROM rewe_products").fetchone()[0]
        assert vid == con.execute("SELECT max(id) FROM rewe_naehrwert_verlauf").fetchone()[0]


DETAIL = {"productId": "2662082", "title": "ja! Streichgut ungesalzen 250g", "brand": "ja!", "articleId": "4337256383158",
          "listing": {"currentRetailPrice": 119, "grammage": "250g (1 kg = 4,76 €)"},
          "nutritionFacts": [{"servingSize": {"value": 100.0, "uomShortText": "g"}, "nutrientInformation": [
              {"nutrientType": "Energie", "quantityContained": {"value": 589.0, "uomShortText": "kcal"}},
              {"nutrientType": "Fett", "quantityContained": {"value": 65.0, "uomShortText": "g"}},
              {"nutrientType": "Kohlenhydrate", "quantityContained": {"value": 0.5, "uomShortText": "g"}},
              {"nutrientType": "Eiweiß", "quantityContained": {"value": 0.4, "uomShortText": "g"}}]}]}


def test_einzelprodukt_aktualisieren(test_db, monkeypatch):
    from app import crawler, rewe
    monkeypatch.setattr(rewe, "aufruf", lambda methode, pid, **kw: DETAIL)
    with test_db.verbinden() as con:
        erg = crawler.produkt_aktualisieren(con, "2662082")   # noch nicht in der Tabelle -> wird angelegt
        assert erg["naehrwerte"] == "neu" and erg["quelle"] == "rewe" and erg["werte"]["kcal"] == 589
        z = con.execute("SELECT name, brand, size_value::float8, ean, details_fetched_at IS NOT NULL FROM rewe_products").fetchone()
        assert z == ("ja! Streichgut ungesalzen 250g", "ja!", 250, "4337256383158", True)
        # REWE liefert plötzlich keine Nährwerte mehr: alte Werte bleiben, kein OFF-Aufruf nötig
        monkeypatch.setattr(rewe, "aufruf", lambda methode, pid, **kw: {**DETAIL, "nutritionFacts": None, "brand": None})
        monkeypatch.setattr(rewe, "openfoodfacts", lambda ean: pytest.fail("OFF darf REWE-Werte nicht ersetzen"))
        erg = crawler.produkt_aktualisieren(con, "2662082")
        assert erg["naehrwerte"] == "leer" and erg["werte"]["kcal"] == 589
        assert con.execute("SELECT brand FROM rewe_products").fetchone()[0] == "ja!"


def test_openfoodfacts_nur_ohne_rewe(test_db, monkeypatch):
    from app import crawler, rewe
    monkeypatch.setattr(rewe, "aufruf", lambda methode, pid, **kw: {**DETAIL, "nutritionFacts": None})
    monkeypatch.setattr(rewe, "openfoodfacts", lambda ean: {"kcal": 590, "protein": 0.5, "fett": 65, "kh": 0.6})
    with test_db.verbinden() as con:
        erg = crawler.produkt_aktualisieren(con, "2662082")
        assert erg["quelle"] == "openfoodfacts" and erg["naehrwerte"] == "off_neu"
