"""Vorratsprodukte: Rangregel, View mit bestem Wert, Übernahme aus der n8n-Datentabelle."""

import pytest

from app import naehrwerte as nw
from app import vorrat

BUTTER_REWE = {"kcal": 589, "protein": 0.4, "fett": 65, "kh": 0.5}
BUTTER_KI = {"kcal": 720, "protein": 0.5, "fett": 80, "kh": 0.5}


@pytest.fixture()
def db(test_db):
    with test_db.verbinden() as con:
        for pid, name in [("2662082", "ja! Streichgut ungesalzen 250g"), ("151854", "Avocado Hass vorgereift 1 Stück"),
                          ("22241", "Kiwi Gold 1 Stück")]:
            con.execute("INSERT INTO rewe_products (rewe_product_id, name) VALUES (%s, %s)", (pid, name))
        nw.rewe_speichern(con, "2662082", BUTTER_REWE, "rewe")
        nw.rewe_speichern(con, "22241", {"kcal": 54, "protein": 0.9, "fett": 0.5, "kh": 13}, "openfoodfacts")
    return test_db


def test_rangregel(db):
    with db.verbinden() as con:
        erg = vorrat.speichern(con, 17, {"name": "Avocado", "einheit": "stk", "rewe_product_id": "151854",
                                         "naehrwerte": {"kcal": 160, "protein": 2, "fett": 15, "kh": 1.9}, "naehrwert_quelle": "ki",
                                         "gramm_pro_stk": 200, "gramm_quelle": "ki"})
        assert erg["naehrwerte"] == "gespeichert" and erg["produkt"]["naehrwert_rang"] == 6 and erg["produkt"]["geschaetzt"]
        # BLS (5) ist besser als KI (6) -> ersetzt
        erg = vorrat.speichern(con, 17, {"naehrwerte": {"kcal": 160, "protein": 1.9, "fett": 14.7, "kh": 3.8},
                                         "naehrwert_quelle": "bls", "gramm_pro_stk": 136, "gramm_quelle": "referenz"})
        assert erg["naehrwerte"] == "gespeichert" and erg["produkt"]["naehrwert_quelle"] == "bls"
        assert erg["produkt"]["gramm_pro_stk"] == 136 and erg["produkt"]["geschaetzt"] is True  # Rang 5 bleibt geschätzt
        # schlechter überschreibt nie besser, leer überschreibt nie
        erg = vorrat.speichern(con, 17, {"naehrwerte": {"kcal": 250, "protein": 2, "fett": 25, "kh": 3}, "naehrwert_quelle": "ki",
                                         "gramm_pro_stk": 250, "gramm_quelle": "ki", "name": ""})
        assert (erg["naehrwerte"], erg["gramm"]) == ("schlechter", "schlechter")
        p = erg["produkt"]
        assert (p["kcal_100"], p["gramm_pro_stk"], p["name"]) == (160, 136, "Avocado")
        # Stückware: kcal pro Stück für Grocy
        assert p["kcal_pro_einheit"] == pytest.approx(160 * 1.36)
        # unplausibel -> nicht gespeichert, gemeldet
        erg = vorrat.speichern(con, 17, {"naehrwerte": {"kcal": 16, "protein": 1.9, "fett": 14.7, "kh": 3.8}, "naehrwert_quelle": "manuell"})
        assert erg["naehrwerte"] == "unplausibel" and con.execute("SELECT count(*) FROM meldungen").fetchone()[0] == 1
        # Nutzerkorrektur (Rang 1) schlägt alles
        erg = vorrat.speichern(con, 17, {"naehrwerte": {"kcal": 170, "protein": 2, "fett": 15.5, "kh": 4}, "naehrwert_quelle": "manuell"})
        assert erg["produkt"]["naehrwert_quelle"] == "manuell" and erg["produkt"]["naehrwert_rang"] == 1


def test_view_rewe_vor_eigenem(db):
    with db.verbinden() as con:
        # KI-Schätzung ist schlechter als das verknüpfte REWE-Produkt -> keine eigene Kopie
        erg = vorrat.speichern(con, 14, {"name": "ja! Streichgut", "rewe_product_id": "2662082", "naehrwerte": BUTTER_KI,
                                         "naehrwert_quelle": "ki"})
        assert erg["naehrwerte"] == "schlechter"
        p = erg["produkt"]
        assert (p["kcal_100"], p["naehrwert_quelle"], p["naehrwert_rang"]) == (589, "rewe", 2) and not p["geschaetzt"]
        assert p["naehrwert_verlauf_id"] is not None and p["kcal_pro_einheit"] == pytest.approx(5.89)
        # REWE-Wert wird unplausibel (z. B. Crawl-Fehler direkt in der DB) -> View fällt auf den nächsten Wert zurück
        con.execute("UPDATE vorrat_produkte SET kcal_100 = 720, protein_100 = 0.5, fett_100 = 80, kh_100 = 0.5, "
                    "naehrwert_quelle = 'ki', naehrwert_rang = 6 WHERE grocy_product_id = 14")
        con.execute("UPDATE rewe_products SET kcal_100 = 58.9 WHERE rewe_product_id = '2662082'")
        assert vorrat.lesen(con, 14)["naehrwert_quelle"] == "ki"


def test_migration(db):
    zeilen = [
        {"grocy_product_id": 1.0, "name": "Skyr Natur", "einheit": "g", "kategorie": "Milchprodukte", "kcal_100": 63, "protein_100": 11,
         "fett_100": 0.2, "kh_100": 3.9, "gramm_pro_stk": 0.0, "quelle": "nutzer", "beschreibung": "Milbona · 500 g · 1,29 €"},
        {"grocy_product_id": 14.0, "name": "ja! Streichgut ungesalzen 250g", "einheit": "g", "kcal_100": 720, "protein_100": 0.5,
         "fett_100": 80, "kh_100": 0.5, "quelle": "ki-schaetzung", "beschreibung": "REWE · 1,19 € · REWE-ID 2662082 · Nährwerte geschätzt"},
        {"grocy_product_id": 12.0, "name": "Kiwi Gold 1 Stück", "einheit": "stk", "kcal_100": 54, "protein_100": 0.9, "fett_100": 0.5,
         "kh_100": 13, "gramm_pro_stk": 120, "off_code": "20022242", "quelle": "rewe", "beschreibung": "REWE · 0,89 € · REWE-ID 22241"},
        {"grocy_product_id": 13.0, "name": "Salami", "einheit": "g", "kcal_100": 350, "protein_100": 20, "fett_100": 28, "kh_100": 1,
         "gramm_pro_stk": 150, "quelle": "ki-schaetzung", "beschreibung": "REWE-ID 999999"},
    ]
    with db.verbinden() as con:
        b = {z["grocy_product_id"]: z for z in vorrat.migrieren(con, zeilen)}
    assert (b[1]["quelle"], b[1]["rang"], b[1]["rewe_product_id"]) == ("manuell", 1, None)
    assert (b[14]["quelle"], b[14]["kcal_100"], b[14]["rewe_product_id"]) == ("rewe", 589, "2662082")
    assert (b[12]["quelle"], b[12]["rang"], b[12]["gramm_quelle"]) == ("off_barcode", 3, "ki")   # REWE-Tabelle: Open Food Facts
    assert b[13]["rewe_product_id"] is None and b[13]["hinweise"] and b[13]["gramm_pro_stk"] is None
