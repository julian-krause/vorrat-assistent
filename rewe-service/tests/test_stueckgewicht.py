"""BLS und Stückgewichte: Import, Suche, Gewichtsklasse, Referenz, Rangfolge, gewogenes Gesamtgewicht."""

import pytest

from app import bls, ermitteln, rewe, stueckgewicht, vorrat


def test_bls_geladen_und_suche(test_db):
    with test_db.verbinden() as con:
        assert con.execute("SELECT count(*) FROM bls").fetchone()[0] > 7000
        treffer = bls.suche(con, "Banane")
        assert treffer[0]["name"] == "Banane roh" and treffer[0]["werte"]["kcal"] == 79
        assert bls.eintrag(con, "F502100")["name"] == "Avocado roh"


@pytest.mark.parametrize("name, gramm, quelle", [
    ("Bio-Eier Größe M 10 Stück", 51, "packung"),
    ("Freilandeier L", 60, "packung"),
    ("Eier M/L 6 Stück", 55.5, "packung"),
    ("Althüs Eier Bio 6 Stück", 51, "referenz"),          # keine Klasse -> Referenz M
    ("Kiwi Gold 1 Stück", 81, "referenz"),
    ("Avocado Hass vorgereift 1 Stück", 136, "referenz"),
    ("Cherry-Tomaten", None, None),
])
def test_bestimmen(test_db, name, gramm, quelle):
    with test_db.verbinden() as con:
        b = stueckgewicht.bestimmen(con, {"einheit": "stk", "name": name, "gramm_pro_stk": 200 if not gramm else None})
        if gramm is None:
            assert b["quelle"] == "ki"
        else:
            assert (b["gramm"], b["quelle"]) == (gramm, quelle)


def test_gewogen(test_db):
    with test_db.verbinden() as con:
        assert stueckgewicht.aus_gewogen(con, "Avocado Hass", 142, True)["gramm"] == pytest.approx(95.1)
        assert stueckgewicht.aus_gewogen(con, "Avocado Hass", 95, False)["gramm"] == 95
        with pytest.raises(ValueError):
            stueckgewicht.aus_gewogen(con, "Drachenfrucht", 300, True)


def test_ki_werte_ersetzen_und_manuell_bleibt(test_db):
    with test_db.verbinden() as con:
        vorrat.speichern(con, 17, {"name": "Avocado Hass vorgereift 1 Stück", "einheit": "stk", "gramm_pro_stk": 200, "gramm_quelle": "ki"})
        vorrat.speichern(con, 7, {"name": "Eier", "einheit": "stk", "gramm_pro_stk": 58, "gramm_quelle": "manuell"})
        geaendert = stueckgewicht.alle_aktualisieren(con)
        assert [(g["grocy_product_id"], g["vorher"], g["gramm"]) for g in geaendert] == [(17, 200, 136)]
        assert vorrat.lesen(con, 7)["gramm_pro_stk"] == 58   # vom Nutzer gewogen bleibt


def test_bls_in_ermitteln(test_db, monkeypatch):
    monkeypatch.setattr(rewe, "openfoodfacts_suche", lambda s: [])
    with test_db.verbinden() as con:
        erg = ermitteln.ermitteln(con, {"name": "Banane", "einheit": "stk", "ki_naehrwerte": {"kcal": 89, "protein": 1.1, "fett": 0.3, "kh": 22.8}})
        assert erg["quelle"] == "ki" and erg["bls_kandidaten"][0]["code"] == "F503100"
        erg = ermitteln.ermitteln(con, {"grocy_product_id": 30, "name": "Banane", "einheit": "stk", "bls_code": "F503100",
                                        "ki_naehrwerte": {"kcal": 89, "protein": 1.1, "fett": 0.3, "kh": 22.8}, "speichern": True})
        assert (erg["quelle"], erg["rang"], erg["werte"]["kcal"]) == ("bls", 5, 79) and erg["bls_kandidaten"] is None
        p = erg["produkt"]
        assert (p["gramm_pro_stk"], p["gramm_quelle"], p["kcal_pro_einheit"]) == (118, "referenz", pytest.approx(93.2))
        assert p["geschaetzt"] is True   # BLS (Rang 5) gilt als Schätzung


def test_bls_suche_mit_marke_und_zusaetzen(test_db):
    with test_db.verbinden() as con:
        assert bls.suche(con, "Althüs Eier Bio 6 Stück")[0]["name"] == "Hühnerei roh"
        assert bls.suche(con, "Avocado Hass vorgereift 1 Stück")[0]["name"] == "Avocado roh"
        assert bls.suche(con, "Kiwi Gold 1 Stück")[0]["name"] == "Kiwi roh"
