"""Zentrale Nährwert-Ermittlung: Rangfolge, sofortiges Nachladen fehlender REWE-Details, Marke bei OFF-Namenssuche."""

import pytest

from app import ermitteln, rewe
from tests.test_naehrwerte import DETAIL


@pytest.fixture()
def db(test_db, monkeypatch):
    # Streichgut ist gecrawlt, aber noch ohne Details (Lage beim eBon-Import am 28.09.)
    with test_db.verbinden() as con:
        con.execute("INSERT INTO rewe_products (rewe_product_id, name, brand, price) VALUES ('2662082', 'ja! Streichgut ungesalzen 250g', 'ja!', 1.19)")
    monkeypatch.setattr(rewe, "openfoodfacts", lambda ean: pytest.fail("OFF nicht nötig"))
    monkeypatch.setattr(rewe, "openfoodfacts_suche", lambda s: pytest.fail("OFF nicht nötig"))
    return test_db


KI = {"kcal": 720, "protein": 0.5, "fett": 80, "kh": 0.5}


def test_regression_rewe_details_fehlen(db, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(rewe, "aufruf", lambda methode, pid, **kw: aufrufe.append(pid) or DETAIL)
    with db.verbinden() as con:
        erg = ermitteln.ermitteln(con, {"grocy_product_id": 14, "name": "ja! Streichgut ungesalzen 250g", "einheit": "g",
                                        "rewe_product_id": "2662082", "ki_naehrwerte": KI, "speichern": True})
        assert aufrufe == ["2662082"], "fehlende Details werden sofort über /aktualisieren nachgeladen"
        assert (erg["quelle"], erg["rang"], erg["werte"]["kcal"]) == ("rewe", 2, 589)
        p = erg["produkt"]
        assert (p["naehrwert_quelle"], p["kcal_100"], p["kcal_pro_einheit"]) == ("rewe", 589, pytest.approx(5.89))
        # keine eigene Kopie der REWE-Werte, keine KI-Werte gespeichert
        assert con.execute("SELECT kcal_100, naehrwert_quelle FROM vorrat_produkte").fetchone() == (None, None)
        # frische Details (< 7 Tage) werden nicht erneut geholt
        ermitteln.ermitteln(con, {"grocy_product_id": 14, "name": "x", "rewe_product_id": "2662082"})
        assert aufrufe == ["2662082"]


def test_rangfolge_ohne_rewe(db, monkeypatch):
    monkeypatch.setattr(rewe, "openfoodfacts", lambda ean: None)
    treffer = [
        {"code": "1", "product_name": "Skyr Natur", "brands": "Arla", "nutriments": {"energy-kcal_100g": 63, "proteins_100g": 11, "fat_100g": 0.2, "carbohydrates_100g": 4}},
        {"code": "2", "product_name": "Skyr Natur", "brands": "Milbona", "nutriments": {"energy-kcal_100g": 62, "proteins_100g": 10.5, "fat_100g": 0.2, "carbohydrates_100g": 4.2}},
    ]
    monkeypatch.setattr(rewe, "openfoodfacts_suche", lambda s: treffer)
    with db.verbinden() as con:
        erg = ermitteln.ermitteln(con, {"name": "Milbona Skyr Natur 500g", "marke": "Milbona", "ean": "4056489000000", "ki_naehrwerte": KI})
        assert (erg["quelle"], erg["detail"].split()[1]) == ("off_name", "2")      # nur gleiche Marke
        erg = ermitteln.ermitteln(con, {"name": "Skyr Natur", "marke": "Ehrmann", "ki_naehrwerte": {"kcal": 65, "protein": 11, "fett": 0.2, "kh": 4}})
        assert erg["quelle"] == "ki"                                                 # andere Marke -> kein OFF-Treffer
        erg = ermitteln.ermitteln(con, {"name": "Banane", "ki_naehrwerte": {"kcal": 93, "protein": 1.2, "fett": 0.2, "kh": 20.4}})
        assert erg["quelle"] == "ki"                                                 # lose Ware ohne Marke: keine Namenssuche


def test_off_limit_warteschlange(db, monkeypatch):
    def limit(*a, **k):
        raise rewe.OffLimit("HTTP 429")
    monkeypatch.setattr(rewe, "openfoodfacts", limit)
    with db.verbinden() as con:
        a = {"grocy_product_id": 20, "name": "Milbona Skyr", "marke": "Milbona", "ean": "4056489000000", "ki_naehrwerte": KI, "speichern": True}
        erg = ermitteln.ermitteln(con, a)
        assert erg["warteschlange"] and erg["quelle"] == "ki"
        ermitteln.ermitteln(con, a)   # kein Duplikat
        assert con.execute("SELECT count(*) FROM off_warteschlange WHERE erledigt_at IS NULL").fetchone()[0] == 1
        # Nachtjob: jetzt klappt der Barcode -> besserer Rang wird gespeichert
        monkeypatch.setattr(rewe, "openfoodfacts", lambda ean: {"kcal": 62, "protein": 10.5, "fett": 0.2, "kh": 4.2})
        assert ermitteln.warteschlange_abarbeiten(con)["erledigt"] == 1
        p = con.execute("SELECT naehrwert_quelle, kcal_100::float8 FROM vorrat_produkte WHERE grocy_product_id = 20").fetchone()
        assert p == ("off_barcode", 62)


def test_marke_passt():
    assert ermitteln.marke_passt("ja!", "Ja!, REWE")
    assert ermitteln.marke_passt("REWE Bio", "REWE Bio")
    assert not ermitteln.marke_passt("REWE", "Rewe Bio")  # andere Linie
    assert not ermitteln.marke_passt(None, "Arla")
    assert ermitteln.marke_passt("ja!", ["Ja!"])            # Such-API liefert Listen
