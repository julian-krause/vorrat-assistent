"""HTTP-Schnittstelle des REWE-Dienstes für n8n (nur im Docker-Netz erreichbar)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from . import bon, db, planer, rewe
from .crawler import Crawler, details_uebernehmen, kategorien_config, listen_produkt
from .parse import ean_aus_article_id, finde_ean, parse_naehrwerte

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
crawler = Crawler()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.schema_anlegen()
    crawler.beim_start_aufraeumen()
    yield
    crawler.stoppen()


app = FastAPI(title="REWE-Dienst (rewerse)", lifespan=lifespan)


@app.exception_handler(rewe.NichtBereit)
async def nicht_bereit(_req, exc: rewe.NichtBereit):
    return JSONResponse(status_code=503, content={"fehler": str(exc)})


def _live(methode: str, *args, **kwargs):
    try:
        return rewe.aufruf(methode, *args, drosseln=False, **kwargs)
    except rewe.NichtBereit:
        raise
    except Exception as e:  # noqa: BLE001 - Fehler der REWE-API an n8n durchreichen
        raise HTTPException(status_code=502, detail=f"REWE-API: {e}") from e


@app.get("/health")
def health():
    with db.verbinden() as con:
        produkte = con.execute("SELECT count(*) FROM rewe_products").fetchone()[0]
    return {"ok": True, "zertifikate": rewe.zertifikate_vorhanden(), "market_id": rewe.MARKET_ID or None,
            "angebote_market_id": rewe.ANGEBOTE_MARKET_ID or None,
            "produkte": produkte, "crawl_laeuft": crawler.laeuft}


@app.get("/markets/search")
def markets_search(q: str = Query(..., description="PLZ, Ort oder Straße")):
    maerkte = _live("maerkte_suchen", q)
    return [{"market_id": m.get("wwIdent") or m.get("id"), "name": m.get("name"), "strasse": m.get("street"),
             "plz": m.get("zipCode"), "ort": m.get("city")} for m in maerkte or []]


@app.get("/categories")
def categories():
    shop = _live("shop_uebersicht")

    def baum(ks):
        return [{"name": k.get("name"), "slug": k.get("slug"), "produkte": k.get("productCount"),
                 "unterkategorien": baum(k.get("childCategories") or [])} for k in ks or []]
    return {"service_type": rewe.service_type(), "konfiguriert": kategorien_config(), "shop": baum(shop.get("productCategories"))}


@app.get("/products/search")
def products_search(q: str, seite: int = 1, pro_seite: int = Query(20, le=60)):
    """Live-Suche im REWE-Shop des Marktes (für Tests/Debugging; der Agent sucht in der lokalen Tabelle)."""
    erg = _live("produkte_suchen", q, page=seite, objects_per_page=pro_seite)
    return {"treffer": (erg.get("pagination") or {}).get("objectCount"),
            "produkte": [listen_produkt(p, "") for p in erg.get("products") or []]}


@app.get("/products/{product_id}")
def product_detail(product_id: str):
    d = _live("produkt_detail", product_id)
    return {"rewe_product_id": product_id, "name": d.get("title"), "brand": d.get("brand"),
            "grammage": (d.get("listing") or {}).get("grammage"), "naehrwerte_100": parse_naehrwerte(d.get("nutritionFacts")),
            "ean": finde_ean(d) or ean_aus_article_id(d.get("articleId"))}


def produkt_aktualisieren(con, product_id: str) -> dict:
    """Details eines Produkts live holen und speichern (fehlt es in der Tabelle, wird es angelegt)."""
    d = _live("produkt_detail", product_id)
    if not con.execute("SELECT 1 FROM rewe_products WHERE rewe_product_id = %s", (product_id,)).fetchone():
        db.produkt_aus_liste(con, listen_produkt({**d, "productId": product_id}, None))
    return details_uebernehmen(con, product_id, d)


@app.post("/products/{product_id}/aktualisieren")
def product_aktualisieren(product_id: str):
    """Details live holen und in rewe_products schreiben (Verlauf, leer überschreibt nie, Plausibilität, 20-%-Meldung)."""
    with db.verbinden() as con:
        return produkt_aktualisieren(con, product_id)


@app.get("/debug/raw/product/{product_id}")
def debug_raw_product(product_id: str):
    """Ungefilterte API-Antwort + gefundene Barcode-Felder (Prüfung, ob REWE eine EAN/GTIN liefert)."""
    roh = _live("produkt_roh", product_id)
    return {"ean_feld": finde_ean(roh), "ean_aus_article_id": ean_aus_article_id(
        (((roh.get("data") or {}).get("product") or [{}])[0]).get("articleId")), "roh": roh}


@app.get("/discounts")
def discounts():
    """Angebote des Marktes, flach: rewe_product_id (= nan/articleNo), Titel, Angebotspreis, gültig bis."""
    d = _live("angebote")
    bis = str(d.get("validUntil") or d.get("ValidUntil") or "")[:10] or None
    angebote = []
    for kat in d.get("categories") or []:
        for o in kat.get("offers") or []:
            if not o.get("articleNo") or o.get("priceParseFail") or not o.get("price"):
                continue
            angebote.append({"rewe_product_id": str(o["articleNo"]), "titel": o.get("title"),
                             "angebotspreis": o.get("price"), "angebot_bis": bis, "kategorie": kat.get("title")})
    return {"gueltig_bis": bis, "abgerufen": date.today().isoformat(), "anzahl": len(angebote), "angebote": angebote}


@app.get("/stats")
def stats():
    """Zahlen für die Live-Seite: Bestand der Tabelle, Kategorien, zuletzt verarbeitete Produkte, Tempo."""
    with db.verbinden() as con:
        z = con.execute("""
            SELECT count(*), count(ean), count(details_fetched_at), count(kcal_100),
                   count(*) FILTER (WHERE details_fetched_at IS NULL),
                   count(*) FILTER (WHERE angebot_bis >= current_date AND angebotspreis IS NOT NULL),
                   count(*) FILTER (WHERE details_fetched_at > now() - interval '5 minutes')
            FROM rewe_products""").fetchone()
        kategorien = con.execute("""
            SELECT category, count(*), count(details_fetched_at), count(kcal_100)
            FROM rewe_products GROUP BY category ORDER BY category""").fetchall()
        zuletzt = con.execute("""
            SELECT name, brand, price, size_value, size_unit, kcal_100, protein_100, ean, details_fetched_at
            FROM rewe_products WHERE details_fetched_at IS NOT NULL
            ORDER BY details_fetched_at DESC LIMIT 12""").fetchall()
        neu_gelistet = con.execute("""
            SELECT name, price, size_value, size_unit, last_seen FROM rewe_products
            ORDER BY last_seen DESC LIMIT 12""").fetchall()
    return {
        "produkte": z[0], "mit_ean": z[1], "mit_details": z[2], "mit_naehrwerten": z[3], "details_offen": z[4],
        "mit_angebot": z[5], "details_pro_minute": round(z[6] / 5, 1),
        "kategorien": [{"name": k[0], "produkte": k[1], "details": k[2], "naehrwerte": k[3]} for k in kategorien],
        "zuletzt_details": [{"name": r[0], "marke": r[1], "preis": r[2], "groesse": r[3], "einheit": r[4], "kcal": r[5],
                             "protein": r[6], "ean": r[7], "zeit": r[8]} for r in zuletzt],
        "zuletzt_gelistet": [{"name": r[0], "preis": r[1], "groesse": r[2], "einheit": r[3], "zeit": r[4]} for r in neu_gelistet],
    }


@app.get("/", response_class=HTMLResponse)
def live_seite():
    return (Path(__file__).parent / "live.html").read_text(encoding="utf-8")


@app.post("/bon/zuordnen")
def bon_zuordnen(
    text: str = Body(..., description="PDF-Text des eBons"),
    bon_id: str = Body(..., description="eindeutige ID, z.B. Message-ID der Mail"),
    artikel_texte: list[str] | None = Body(None, description="Kassentexte der KI-Artikel, Ergebnis kommt in derselben Reihenfolge"),
    kaufdatum: str | None = Body(None),
):
    """Ordnet die Zeilen eines eBons den REWE-Produkten zu (sicher / unsicher mit Kandidaten / keine)."""
    with db.verbinden() as con:
        return bon.zuordnen(con, text, bon_id, artikel_texte, kaufdatum)


@app.post("/bon/antwort")
def bon_antwort(zeile_id: int = Body(...), rewe_product_id: str | None = Body(None, description="leer = keins davon")):
    """Antwort auf eine Rückfrage: Zuordnung lernen und Produktdaten zurückgeben."""
    with db.verbinden() as con:
        return bon.antwort_speichern(con, zeile_id, rewe_product_id or None)


@app.post("/planer/kandidaten")
def planer_kandidaten(namen: list[str] = Body(..., embed=True, description="Zutatennamen aus dem Wochenplan")):
    """Bis zu 8 REWE-Kandidaten je Zutat (Nährwerte, Packungsgröße, aktueller Preis inkl. Angebot), bester zuerst."""
    with db.verbinden() as con:
        return {"kandidaten": planer.zutaten_kandidaten(con, namen)}


@app.post("/crawl", status_code=202)
def crawl(
    kategorien: list[str] | None = Body(None, description="Namen aus kategorien.yml; leer = alle"),
    max_seiten: int | None = Body(None, description="Seiten pro Kategorie begrenzen (Mini-Crawl)"),
    details: bool = Body(True),
    max_details: int | None = Body(None, description="Detailabrufe begrenzen (Mini-Crawl)"),
    neu: bool = Body(False, description="true = nicht fortsetzen, neuen Lauf beginnen"),
):
    params = {"kategorien": kategorien, "max_seiten": max_seiten, "details": details, "max_details": max_details}
    return crawler.starten(params, neu=neu)


@app.post("/crawl/stop")
def crawl_stop():
    crawler.stoppen()
    return {"status": "stop angefordert"}


@app.get("/crawl/status")
def crawl_status():
    with db.verbinden() as con:
        run = con.execute("SELECT id, status, started_at, finished_at, params, cursor, stats FROM crawl_runs "
                          "ORDER BY id DESC LIMIT 1").fetchone()
        logs = con.execute("SELECT level, message, payload, created_at FROM crawl_log ORDER BY id DESC LIMIT 20").fetchall()
    if not run:
        return {"laeuft": crawler.laeuft, "letzter_lauf": None}
    cursor = run[5] or {}
    return {
        "laeuft": crawler.laeuft,
        "letzter_lauf": {"id": run[0], "status": run[1], "start": run[2], "ende": run[3], "params": run[4],
                         "phase": cursor.get("phase"), "kategorie": cursor.get("k"),
                         "kategorien": len(cursor.get("kategorien") or []), "seite": cursor.get("seite"), "stats": run[6]},
        "log": [{"level": l[0], "text": l[1], "daten": l[2], "zeit": l[3]} for l in logs],
    }
