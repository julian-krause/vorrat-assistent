"""Planer-Vorgaben: Tagesziel, Mahlzeiten, „restlicher Tag“ (mit noch nicht übernommenen Grocy-Ausbuchungen) und Ausschlüsse."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app import planer

PROFIL = {"kcal": 2400, "protein_g": 180, "fett_g": 70, "kh_g": 270, "mahlzeiten_pro_tag": 3}
BERLIN = ZoneInfo("Europe/Berlin")


def um(stunde, minute=0):
    return datetime(2026, 9, 30, stunde, minute, tzinfo=BERLIN)


@pytest.fixture()
def db(test_db):
    with test_db.verbinden() as con:
        con.execute("""INSERT INTO vorrat_produkte (grocy_product_id, name, einheit, kcal_100, protein_100, fett_100, kh_100, naehrwert_quelle, naehrwert_rang)
                       VALUES (7, 'Haferflocken', 'g', 370, 13, 7, 59, 'rewe', 2), (8, 'Ei', 'stk', 140, 12, 10, 1, 'rewe', 2)""")
        con.execute("UPDATE vorrat_produkte SET gramm_pro_stk = 60 WHERE grocy_product_id = 8")
    return test_db


def _gegessen(con, kcal, protein=0, zeit="2026-09-30 08:00+02"):
    con.execute("INSERT INTO verzehr (zeitpunkt, quelle, name, kcal, protein, fett, kh) VALUES (%s, 'manuell', 'Frühstück', %s, %s, 0, 0)",
                (zeit, kcal, protein))


def test_ohne_vorgaben_kommt_alles_aus_dem_profil(db):
    with db.verbinden() as con:
        v = planer.vorgaben(con, PROFIL, jetzt=um(9))
    assert v["ziel"] == {"kcal": 2400, "p": 180, "f": 70, "kh": 270}
    assert [s["name"] for s in v["slots"]] == ["Frühstück", "Mittag", "Abend"]
    assert sum(s["kcal"] for s in v["slots"]) == 2400 and v["bereits"]["kcal"] == 0


def test_uebergebene_werte_gewinnen(db):
    with db.verbinden() as con:
        v = planer.vorgaben(con, PROFIL, kcal_ziel=3000, mahlzeiten=["Mittag", "Abend"], ziel_protein=200, jetzt=um(9))
    assert v["ziel"]["kcal"] == 3000 and v["ziel"]["p"] == 200
    assert v["ziel"]["f"] == round(70 * 3000 / 2400) and [s["name"] for s in v["slots"]] == ["Mittag", "Abend"]
    assert sum(s["kcal"] for s in v["slots"]) == 3000


def test_restlicher_tag_2800_kcal_2_mahlzeiten(db):
    """„Restlicher Tag, am Ende etwa 2800 kcal, 2 Mahlzeiten“ bei X kcal schon gegessen -> 2 Mahlzeiten, Summe = 2800 − X."""
    with db.verbinden() as con:
        _gegessen(con, 900, 40)
        # zusätzlich: Ausbuchung in Grocy, die der 5-Minuten-Abgleich noch nicht übernommen hat (2 Eier à 60 g = 168 kcal)
        log = [{"id": 501, "product_id": 8, "amount": 2, "transaction_type": "consume", "undone": 0, "spoiled": 0,
                "row_created_timestamp": "2026-09-30 12:58:00"},
               {"id": 502, "product_id": 8, "amount": 5, "transaction_type": "consume", "undone": 0, "spoiled": 1,   # weggeworfen: zählt nicht
                "row_created_timestamp": "2026-09-30 12:59:00"},
               {"id": 503, "product_id": 7, "amount": 100, "transaction_type": "inventory-correction", "undone": 0, "spoiled": 0,   # Korrektur: zählt nicht
                "row_created_timestamp": "2026-09-30 12:59:00"},
               {"id": 504, "product_id": 7, "amount": 100, "transaction_type": "consume", "undone": 1, "spoiled": 0,      # rückgängig: zählt nicht
                "row_created_timestamp": "2026-09-30 12:59:00"}]
        con.execute("INSERT INTO verzehr (zeitpunkt, quelle, grocy_log_id, name, kcal) VALUES ('2026-09-30 12:00+02', 'grocy', 500, 'schon übernommen', 300)")
        v = planer.vorgaben(con, PROFIL, kcal_ziel=2800, mahlzeiten=2, restlicher_tag=True, jetzt=um(13), grocy_verbrauch=log)
    gegessen = 900 + 300 + 2 * 60 * 140 / 100                      # Protokoll + Grocy-Ausbuchung (500 ist schon im Protokoll)
    assert v["bereits"]["kcal"] == pytest.approx(gegessen) and v["bereits"]["grocy_offen"] == 1
    assert [s["name"] for s in v["slots"]] == ["Mittag", "Abend"]           # 13 Uhr: Frühstück ist vorbei, Mittag steht noch an
    assert sum(s["kcal"] for s in v["slots"]) == round(2800 - gegessen)
    assert "Frühstück" not in [s["name"] for s in v["slots"]] and v["rest"]["kcal"] == round(2800 - gegessen)


def test_vergangene_mahlzeiten_entfallen(db):
    with db.verbinden() as con:
        v = planer.vorgaben(con, PROFIL, restlicher_tag=True, jetzt=um(15))          # 15 Uhr: Frühstück und Mittag vorbei
        assert [s["name"] for s in v["slots"]] == ["Abend"] and v["hinweise"]
        v = planer.vorgaben(con, PROFIL, mahlzeiten="Mittag, Abend", restlicher_tag=True, jetzt=um(15))
        assert [s["name"] for s in v["slots"]] == ["Abend"]
        v = planer.vorgaben(con, PROFIL, restlicher_tag=True, jetzt=um(23))
        assert v["slots"] == []


def test_ziel_schon_erreicht(db):
    with db.verbinden() as con:
        _gegessen(con, 2500)
        v = planer.vorgaben(con, PROFIL, restlicher_tag=True, jetzt=um(18))
    assert v["slots"] == [] and v["rest"]["kcal"] == 0 and v["hinweise"]


def test_ignorierte_verzehreintraege_zaehlen_nicht(db):
    with db.verbinden() as con:
        _gegessen(con, 500)
        con.execute("INSERT INTO verzehr (zeitpunkt, quelle, name, kcal, ignoriert) VALUES ('2026-09-30 09:00+02', 'manuell', 'x', 700, true)")
        assert planer.bereits_gegessen(con, date(2026, 9, 30))["kcal"] == 500


@pytest.mark.parametrize("zutat, trifft", [
    ("Avocado", True), ("Avocados (reif)", True), ("Bio Avocado 2 Stück", True), ("Walnusskerne", True), ("Walnüsse gehackt", True),
    ("Mandeln", False), ("Haferflocken", False), ("Magerquark", False), ("Erdnussbutter", False),
])
def test_ausschluss_avocado_walnuesse(db, zutat, trifft):
    with db.verbinden() as con:
        b = planer.ausschluss_begriffe(con, "Avocado, Walnüsse")
    assert bool(planer.ausschluss_treffer(b, zutat)) == trifft, (zutat, b)


def test_ausschluss_oberbegriffe(db):
    with db.verbinden() as con:
        nuesse = planer.ausschluss_begriffe(con, ["Nüsse"])
        milch = planer.ausschluss_begriffe(con, "Milchprodukte")
    for z in ("Mandeln", "Haselnussmus", "Erdnussbutter", "Cashewkerne", "Walnusskerne"):
        assert planer.ausschluss_treffer(nuesse, z), z
    assert not planer.ausschluss_treffer(nuesse, "Haferflocken")
    for z in ("Magerquark", "Skyr Natur", "Gouda", "Vollmilch", "Butter", "Mozzarella"):
        assert planer.ausschluss_treffer(milch, z), z
    for z in ("Hafermilch", "Sojajoghurt", "Kokosmilch", "Mandeldrink", "Haferflocken"):
        assert not planer.ausschluss_treffer(milch, z), z


def test_ausschluss_kurze_begriffe_nur_als_ganzes_wort(db):
    with db.verbinden() as con:
        b = planer.ausschluss_begriffe(con, "Ei")
    assert planer.ausschluss_treffer(b, "Eier") and planer.ausschluss_treffer(b, "2 Ei")
    assert not planer.ausschluss_treffer(b, "Eisbergsalat") and not planer.ausschluss_treffer(b, "Reis")


def test_api_endpunkte(db):
    from fastapi.testclient import TestClient
    from app import main
    c = TestClient(main.app)
    r = c.post("/planer/vorgaben", json={"profil": PROFIL, "kcal_ziel": 2800, "mahlzeiten": 2, "restlicher_tag": True,
                                         "ausschluesse": "Avocado, Walnüsse", "jetzt": "2026-09-30T13:00:00+02:00"})
    assert r.status_code == 200, r.text
    assert len(r.json()["slots"]) == 2 and "avocado" in r.json()["ausschluesse"]
    r = c.post("/planer/ausschluss", json={"ausschluesse": "Avocado, Walnüsse", "zutaten": ["Avocado", "Haferflocken", "Walnusskerne"]})
    assert r.json()["treffer"]["Avocado"] and not r.json()["treffer"]["Haferflocken"] and r.json()["treffer"]["Walnusskerne"]
    assert c.post("/synonyme", json={"gruppe": "kuerbis", "begriffe": ["Hokkaido", "Kürbis"]}).json()["neu"] == 2
    assert "kuerbis" in c.get("/synonyme").json()
