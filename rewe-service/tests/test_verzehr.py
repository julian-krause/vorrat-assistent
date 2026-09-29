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
