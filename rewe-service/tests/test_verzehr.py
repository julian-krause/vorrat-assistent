"""Ist-Verbrauch: Auswertung pro Kalendertag, geschätzte Anteile, ignorierte Einträge."""


def test_auswertung_september(test_db):
    with test_db.verbinden() as con:
        eintraege = [
            ("2026-09-01 08:00+02", "grocy", "Haferflocken", 100, 372, 13.5, 7, 58.7, False, False),
            ("2026-09-01 19:30+02", "manuell", "Döner", 350, 700, 35, 30, 70, True, False),
            ("2026-09-15 12:00+02", "rezept", "Hähnchenbrustfilet", 200, 220, 46, 3, 0, False, False),
            ("2026-09-15 13:00+02", "manuell", "falsch eingetragen", 100, 1000, 0, 0, 0, True, True),
            ("2026-08-31 23:30+02", "grocy", "August", 100, 999, 0, 0, 0, False, False),
            ("2026-09-30 23:30+02", "grocy", "Skyr", 500, 315, 55, 1, 19.5, False, False),
        ]
        for z, q, n, g, kcal, p, f, kh, gesch, ign in eintraege:
            con.execute("""INSERT INTO verzehr (zeitpunkt, quelle, name, gramm, kcal, protein, fett, kh, geschaetzt, ignoriert)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (z, q, n, g, kcal, p, f, kh, gesch, ign))
        a = con.execute("SELECT verzehr_auswertung('2026-09-01', '2026-09-30')").fetchone()[0]
    # der Test läuft nach dem 30.09.2026 bzw. davor: „bis“ wird auf heute begrenzt
    assert a["summe"]["kcal"] in (372 + 700 + 220 + 315, 372 + 700 + 220)
    assert a["eintraege"] >= 3 and a["tage_mit_eintraegen"] >= 2
    assert a["durchschnitt_pro_kalendertag"]["kcal"] == round(a["summe"]["kcal"] / a["kalendertage"])
    assert a["top_lebensmittel"][0]["name"] == "Döner"
    assert "falsch eingetragen" not in [t["name"] for t in a["top_lebensmittel"]]
    assert "August" not in [t["name"] for t in a["top_lebensmittel"]]


def test_korrektur_job(test_db):
    """Bessere Quelle -> neu berechnen; nur neuer REWE-Stand -> nicht; besseres Stückgewicht -> Gramm neu."""
    from app import naehrwerte as nw
    from app import verzehr, vorrat
    with test_db.verbinden() as con:
        con.execute("INSERT INTO rewe_products (rewe_product_id, name, grammage_raw) VALUES ('2662082', 'Streichgut', '250g'), ('8243243', 'Salami', '150g')")
        nw.rewe_speichern(con, "8243243", {"kcal": 378, "protein": 22, "fett": 32, "kh": 0.5}, "rewe")
        vorrat.speichern(con, 14, {"name": "Streichgut", "rewe_product_id": "2662082", "naehrwerte": {"kcal": 720, "protein": 0.5, "fett": 80, "kh": 0.5},
                                   "naehrwert_quelle": "ki"})
        vorrat.speichern(con, 13, {"name": "Salami", "rewe_product_id": "8243243"})
        vorrat.speichern(con, 17, {"name": "Avocado", "einheit": "stk", "naehrwerte": {"kcal": 132, "protein": 1.4, "fett": 12.5, "kh": 1.4},
                                   "naehrwert_quelle": "bls", "gramm_pro_stk": 200, "gramm_quelle": "ki"})
        salami_vid = vorrat.lesen(con, 13)["naehrwert_verlauf_id"]
        ein = """INSERT INTO verzehr (zeitpunkt, quelle, grocy_product_id, name, menge, einheit, gramm, kcal, protein, fett, kh,
                                      naehrwert_quelle, naehrwert_rang, naehrwert_verlauf_id, gramm_quelle, gramm_rang, geschaetzt)
                 VALUES (now(), 'grocy', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"""
        butter = con.execute(ein, (14, "Streichgut", 20, "g", 20, 144, 0.1, 16, 0.1, "ki", 6, None, None, None, True)).fetchone()[0]
        salami = con.execute(ein, (13, "Salami", 30, "g", 30, 113.4, 6.6, 9.6, 0.2, "rewe", 2, salami_vid, None, None, False)).fetchone()[0]
        avocado = con.execute(ein, (17, "Avocado", 1, "stk", 200, 264, 2.8, 25, 2.8, "bls", 5, None, "ki", 4, True)).fetchone()[0]
        auswaerts = con.execute("INSERT INTO verzehr (zeitpunkt, quelle, name, gramm, kcal, geschaetzt) VALUES (now(), 'manuell', 'Döner', 350, 700, true) RETURNING id").fetchone()[0]

        # REWE liefert jetzt die Streichgut-Werte (Rang 2 statt KI 6); die Salami bekommt eine neue Rezeptur (gleicher Rang)
        nw.rewe_speichern(con, "2662082", {"kcal": 589, "protein": 0.4, "fett": 65, "kh": 0.5}, "rewe")
        nw.rewe_speichern(con, "8243243", {"kcal": 300, "protein": 25, "fett": 22, "kh": 0.5}, "rewe")
        # Avocado: Stückgewicht aus der Referenz (Rang 3 statt KI 4)
        vorrat.speichern(con, 17, {"gramm_pro_stk": 136, "gramm_quelle": "referenz"})

        stat = verzehr.korrigieren(con)
        assert stat["korrigiert"] == 2
        z = lambda i: con.execute("SELECT gramm::float8, kcal::float8, naehrwert_quelle, gramm_quelle, geschaetzt, korrigiert_at IS NOT NULL "
                                  "FROM verzehr WHERE id = %s", (i,)).fetchone()
        assert z(butter) == (20, 117.8, "rewe", None, False, True)
        assert z(salami) == (30, 113.4, "rewe", None, False, False)          # damaliger Stand bleibt
        assert z(avocado) == (136, 179.5, "bls", "referenz", True, True)     # Gramm neu, Werte pro 100 g wie damals
        assert z(auswaerts)[1] == 700
        assert con.execute("SELECT count(*) FROM verzehr_korrektur").fetchone()[0] == 2
        assert verzehr.korrigieren(con)["korrigiert"] == 0                    # idempotent
