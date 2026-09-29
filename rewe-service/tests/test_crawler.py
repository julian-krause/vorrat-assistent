"""Crawler gegen eine nachgebaute REWE-API: Upsert, Preisverlauf, Details, Fortsetzen nach Abbruch."""

import pytest

SHOP = {"productCategories": [
    {"name": "Preis-Hits", "slug": "preis-hits", "childCategories": []},
    {"name": "Obst & Gemüse", "slug": "obst-gemuese", "childCategories": [
        {"name": "Obst", "slug": "obst", "childCategories": []}]},
    {"name": "Nudeln & Reis", "slug": "nudeln-reis", "childCategories": []},
]}


def produkt(pid, titel, preis_cent, grammage, article_id=None):
    return {"productId": pid, "articleId": article_id or "A" + pid, "title": titel, "attributes": {"isOrganic": False},
            "listing": {"currentRetailPrice": preis_cent, "grammage": grammage}}


SEITEN = {
    ("obst-gemuese", 1): [produkt("1000001", "Bananen", 139, "1kg"), produkt("1000002", "Äpfel Elstar", 249, "ca. Schale")],
    ("obst-gemuese", 2): [produkt("1000003", "Zucchini", 99, "1 Stück")],
    ("nudeln-reis", 1): [produkt("2000001", "Barilla Spaghetti", 179, "500g (1 kg = 3,58 €)", "8076800195057")],
}
DETAILS = {
    "1000001": {"brand": "REWE", "nutritionFacts": [{"preparationState": "Unzubereitet", "nutrientInformation": [
        {"nutrientType": "Energie", "quantityContained": {"value": 93, "uomShortText": "kcal"}},
        {"nutrientType": "Eiweiß", "quantityContained": {"value": 1.2, "uomShortText": "g"}},
        {"nutrientType": "Fett", "quantityContained": {"value": 0.2, "uomShortText": "g"}},
        {"nutrientType": "Kohlenhydrate", "quantityContained": {"value": 20.4, "uomShortText": "g"}}]}]},
    "1000002": {"brand": None, "packaging": {"weightPerPiece": 750.0}},
    "1000003": {"brand": None},
    "2000001": {"brand": "Barilla", "description": "Hartweizengrieß"},
}


class FakeRewe:
    def __init__(self, fehler_bei=None):
        self.aufrufe = []
        self.fehler_bei = fehler_bei

    def __call__(self, methode, *args, drosseln=True, **kwargs):
        self.aufrufe.append((methode, args, kwargs))
        if methode == "shop_uebersicht":
            return SHOP
        if methode == "kategorie_produkte":
            slug, seite = args[0], kwargs["page"]
            if self.fehler_bei == (slug, seite):
                raise RuntimeError("HTTP 403 cloudflare")
            anzahl = 2 if slug == "obst-gemuese" else 1
            return {"products": SEITEN.get((slug, seite), []), "pagination": {"pageCount": anzahl}}
        if methode == "produkt_detail":
            return DETAILS[args[0]]
        raise AssertionError(methode)


@pytest.fixture()
def umgebung(test_db, monkeypatch, tmp_path):
    from app import crawler, rewe
    cfg = tmp_path / "kategorien.yml"
    cfg.write_text("kategorien:\n  - name: Obst & Gemüse\n    treffer: ['obst & gemüse']\n"
                   "  - name: Grundnahrungsmittel\n    treffer: ['reis']\n", encoding="utf-8")
    monkeypatch.setattr(crawler, "KATEGORIEN_DATEI", str(cfg))
    monkeypatch.setattr(rewe, "MARKET_ID", "123456")
    monkeypatch.setattr(rewe, "client", lambda: object())
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    return crawler, rewe, test_db


def laufen(crawler, params, neu=False):
    c = crawler.Crawler()
    c.starten(params, neu=neu)
    c._thread.join(timeout=30)
    return c


def test_kompletter_lauf(umgebung, monkeypatch):
    crawler, rewe, db = umgebung
    fake = FakeRewe()
    monkeypatch.setattr(rewe, "aufruf", fake)
    laufen(crawler, {"kategorien": None, "max_seiten": None, "details": True, "max_details": None})
    with db.verbinden() as con:
        status, stats, cursor = con.execute("SELECT status, stats, cursor FROM crawl_runs").fetchone()
        assert status == "fertig"
        # „reis“ trifft „Nudeln & Reis“, aber nicht „Preis-Hits“
        assert [k["slug"] for k in cursor["kategorien"]] == ["obst-gemuese", "nudeln-reis"]
        assert stats["neu"] == 4 and stats["details"] == 4 and stats["ohne_groesse"] == 1
        zeilen = {r[0]: r[1:] for r in con.execute(
            "SELECT rewe_product_id, size_value::float8, size_unit, price::float8, price_per_kg_or_l::float8, brand, kcal_100::float8, protein_100::float8 "
            "FROM rewe_products")}
        assert zeilen["2000001"][:5] == (500, "g", pytest.approx(1.79), pytest.approx(3.58), "Barilla")
        eans = dict(con.execute("SELECT rewe_product_id, ean FROM rewe_products"))
        assert eans["2000001"] == "8076800195057" and eans["1000001"] is None
        assert zeilen["1000001"][5:] == (93, pytest.approx(1.2))
        # packaging.weightPerPiece ist keine Grammangabe -> Größe bleibt unbekannt
        assert zeilen["1000002"][:2] == (None, None)
        assert con.execute("SELECT count(*) FROM rewe_price_history").fetchone()[0] == 4
        assert con.execute("SELECT count(*) FROM crawl_log WHERE message = 'Größe nicht erkannt'").fetchone()[0] == 1

    # Folge-Crawl ohne Erneuerung: Preis ändert sich, keine erneuten Detailabrufe, Verlauf wird angehängt
    SEITEN[("nudeln-reis", 1)][0]["listing"]["currentRetailPrice"] = 149
    fake2 = FakeRewe()
    monkeypatch.setattr(rewe, "aufruf", fake2)
    laufen(crawler, {"kategorien": None, "max_seiten": None, "details": True, "max_details": None, "max_erneuern": 0}, neu=True)
    assert not [a for a in fake2.aufrufe if a[0] == "produkt_detail"]
    with db.verbinden() as con:
        assert con.execute("SELECT price::float8 FROM rewe_products WHERE rewe_product_id = '2000001'").fetchone()[0] == pytest.approx(1.49)
        verlauf = [r[0] for r in con.execute(
            "SELECT price::float8 FROM rewe_price_history WHERE rewe_product_id = '2000001' ORDER BY id")]
        assert verlauf == [pytest.approx(1.79), pytest.approx(1.49)]
        assert con.execute("SELECT count(*) FROM produkt_suche('spaghetti barilla')").fetchone()[0] == 1
    SEITEN[("nudeln-reis", 1)][0]["listing"]["currentRetailPrice"] = 179


def test_fortsetzen_nach_abbruch(umgebung, monkeypatch):
    crawler, rewe, db = umgebung
    # Seite 2 von Obst & Gemüse schlägt dauerhaft fehl -> 3 Fehler in Folge -> Abbruch
    monkeypatch.setattr(rewe, "aufruf", FakeRewe(fehler_bei=("obst-gemuese", 2)))
    monkeypatch.setattr(crawler, "MAX_FEHLER_IN_FOLGE", 2)
    laufen(crawler, {"kategorien": None, "max_seiten": None, "details": True, "max_details": None})
    with db.verbinden() as con:
        status, cursor = con.execute("SELECT status, cursor FROM crawl_runs ORDER BY id DESC").fetchone()
        assert status == "abgebrochen" and cursor["k"] == 0 and cursor["seite"] == 2

    fake = FakeRewe()
    monkeypatch.setattr(rewe, "aufruf", fake)
    c = laufen(crawler, {"egal": True})
    listen = [(a[1][0], a[2]["page"]) for a in fake.aufrufe if a[0] == "kategorie_produkte"]
    assert listen[0] == ("obst-gemuese", 2), "setzt an der abgebrochenen Seite fort"
    assert not [a for a in fake.aufrufe if a[0] == "shop_uebersicht"]
    with db.verbinden() as con:
        runs = con.execute("SELECT id, status FROM crawl_runs ORDER BY id").fetchall()
        assert len(runs) == 1 and runs[0][1] == "fertig" and c.run_id == runs[0][0]


def test_mini_crawl(umgebung, monkeypatch):
    crawler, rewe, db = umgebung
    fake = FakeRewe()
    monkeypatch.setattr(rewe, "aufruf", fake)
    laufen(crawler, {"kategorien": ["Obst & Gemüse"], "max_seiten": 1, "details": True, "max_details": 1}, neu=True)
    listen = [(a[1][0], a[2]["page"]) for a in fake.aufrufe if a[0] == "kategorie_produkte"]
    assert listen == [("obst-gemuese", 1)]
    assert len([a for a in fake.aufrufe if a[0] == "produkt_detail"]) == 1


def test_details_aktuell_halten(umgebung, monkeypatch):
    crawler, rewe, db = umgebung
    monkeypatch.setattr(rewe, "aufruf", FakeRewe())
    laufen(crawler, {"kategorien": None, "max_seiten": None, "details": True, "max_details": None})
    with db.verbinden() as con:
        # Details künstlich altern lassen: Zucchini am ältesten, dann Bananen
        con.execute("UPDATE rewe_products SET details_fetched_at = now() - interval '30 days'")
        con.execute("UPDATE rewe_products SET details_fetched_at = now() - interval '90 days' WHERE rewe_product_id = '1000003'")
        con.execute("UPDATE rewe_products SET details_fetched_at = now() - interval '60 days' WHERE rewe_product_id = '1000001'")

    # Spaghetti bekommt eine neue Größe -> Details im selben Lauf neu; zusätzlich die 2 ältesten erneuern
    SEITEN[("nudeln-reis", 1)][0]["listing"]["grammage"] = "400g (1 kg = 4,48 €)"
    fake = FakeRewe()
    monkeypatch.setattr(rewe, "aufruf", fake)
    laufen(crawler, {"kategorien": None, "max_seiten": None, "details": True, "max_details": None, "max_erneuern": 2}, neu=True)
    SEITEN[("nudeln-reis", 1)][0]["listing"]["grammage"] = "500g (1 kg = 3,58 €)"
    details = [a[1][0] for a in fake.aufrufe if a[0] == "produkt_detail"]
    assert details == ["2000001", "1000003", "1000001"]
    with db.verbinden() as con:
        stats = con.execute("SELECT stats FROM crawl_runs ORDER BY id DESC").fetchone()[0]
        assert stats["name_groesse_geaendert"] == 1 and stats["erneuert"] == 2
        # Nährwerte der Bananen unverändert -> kein zweiter Verlaufseintrag
        assert con.execute("SELECT count(*) FROM rewe_naehrwert_verlauf WHERE rewe_product_id = '1000001'").fetchone()[0] == 1


def test_vorratsprodukte_zuerst(umgebung, monkeypatch):
    crawler, rewe, db = umgebung
    monkeypatch.setattr(rewe, "aufruf", FakeRewe())
    laufen(crawler, {"kategorien": None, "max_seiten": None, "details": True, "max_details": None})
    with db.verbinden() as con:
        con.execute("INSERT INTO vorrat_produkte (grocy_product_id, name, rewe_product_id) VALUES (4, 'Spaghetti', '2000001')")
    fake = FakeRewe()
    monkeypatch.setattr(rewe, "aufruf", fake)
    # auch ohne Erneuerungs-Kontingent werden verknüpfte Vorratsprodukte in jedem Lauf zuerst erneuert
    laufen(crawler, {"kategorien": None, "max_seiten": None, "details": True, "max_details": None, "max_erneuern": 0}, neu=True)
    assert [a[1][0] for a in fake.aufrufe if a[0] == "produkt_detail"] == ["2000001"]
