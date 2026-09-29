"""Fortsetzbarer Crawl der Lebensmittelkategorien eines REWE-Marktes.

Phase „liste“:   pro Kategorie alle Seiten der Listenansicht -> Upsert (Preis, Größe, last_seen) + Preisverlauf.
Phase „details“: Produkte ohne Details (neu oder Name/Größe geändert), danach die ältesten Details bis zur Grenze
                 REWE_DETAILS_ERNEUERN -> Marke, Beschreibung, Nährwerte (REWE, sonst Open Food Facts per EAN).
                 Nährwerte laufen immer über naehrwerte.rewe_speichern (Verlauf, leer überschreibt nie, Plausibilität).
Der Fortschritt (cursor) wird nach jeder Seite bzw. jedem Produkt gespeichert; ein abgebrochener Lauf
wird beim nächsten POST /crawl an derselben Stelle fortgesetzt.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

from . import db, naehrwerte, rewe
from .parse import ean_aus_article_id, finde_ean, grundpreis, parse_groesse, parse_naehrwerte

log = logging.getLogger("crawler")
KATEGORIEN_DATEI = os.environ.get("REWE_KATEGORIEN_DATEI", "/config/kategorien.yml")
PRO_SEITE = int(os.environ.get("REWE_PRO_SEITE", "60"))
MAX_FEHLER_IN_FOLGE = 3
# pro Lauf zusätzlich die ältesten Details erneuern (Nährwerte, Marke, EAN), damit nichts veraltet
DETAILS_ERNEUERN = int(os.environ.get("REWE_DETAILS_ERNEUERN", "1500"))


def kategorien_config() -> list[dict]:
    daten = yaml.safe_load(Path(KATEGORIEN_DATEI).read_text(encoding="utf-8")) or {}
    return daten.get("kategorien") or []


def _alle_kategorien(baum: list[dict], tiefe: int = 0):
    for k in baum or []:
        yield k, tiefe
        yield from _alle_kategorien(k.get("childCategories") or [], tiefe + 1)


def kategorien_aufloesen(shop: dict, auswahl: list[str] | None, con, run_id) -> list[dict]:
    """Config-Einträge (Namensteile oder Slugs) -> [{name, slug}] anhand der Shop-Kategorien des Marktes."""
    baum = list(_alle_kategorien(shop.get("productCategories") or []))
    ziele = []
    for eintrag in kategorien_config():
        if auswahl and eintrag["name"] not in auswahl:
            continue
        slugs = list(eintrag.get("slugs") or [])
        for teil in eintrag.get("treffer") or []:
            # ganze Wörter vergleichen, damit z.B. „reis“ nicht „Preis-Hits“ trifft
            muster = re.compile(r"(?<!\w)" + re.escape(teil) + r"(?!\w)", re.IGNORECASE)
            # oberste passende Ebene nehmen, Unterkategorien sind dann enthalten
            passend = [(k, t) for k, t in baum if muster.search(str(k.get("name", "")))]
            if passend:
                min_tiefe = min(t for _, t in passend)
                slugs += [k["slug"] for k, t in passend if t == min_tiefe]
        slugs = list(dict.fromkeys(slugs))
        if not slugs:
            db.log(con, run_id, "warn", f"Kategorie „{eintrag['name']}“ im Shop nicht gefunden (GET /categories zeigt die echten Namen)")
        ziele += [{"name": eintrag["name"], "slug": s} for s in slugs]
    # gleiche Slugs nur einmal crawlen
    gesehen, eindeutig = set(), []
    for z in ziele:
        if z["slug"] not in gesehen:
            gesehen.add(z["slug"])
            eindeutig.append(z)
    return eindeutig


def listen_produkt(p: dict, kategorie: str) -> dict:
    listing = p.get("listing") or {}
    attr = p.get("attributes") or {}
    preis = listing.get("currentRetailPrice")
    preis = round(preis / 100, 2) if isinstance(preis, (int, float)) else None
    groesse, einheit = parse_groesse(listing.get("grammage"))
    return {
        "id": str(p["productId"]), "article_id": p.get("articleId"), "ean": ean_aus_article_id(p.get("articleId")),
        "name": p.get("title") or "?",
        "category": kategorie, "grammage": listing.get("grammage"),
        "size_value": groesse, "size_unit": einheit,
        "price": preis, "price_per": grundpreis(preis, groesse, einheit),
        "bio": attr.get("isOrganic"), "vegan": attr.get("isVegan"), "vegetarisch": attr.get("isVegetarian"),
    }


def details_uebernehmen(con, pid: str, d: dict, run_id: int | None = None) -> dict:
    """Detailansicht eines Produkts übernehmen: Stammdaten + Nährwerte (REWE, sonst Open Food Facts per EAN).

    Open Food Facts nur, wenn das Produkt noch keine REWE-Werte hat (schlechter überschreibt nie besser).
    """
    ean = finde_ean(d) or ean_aus_article_id(d.get("articleId"))
    listing = d.get("listing") or {}
    groesse, einheit = parse_groesse(listing.get("grammage"))
    preis = listing.get("currentRetailPrice")
    preis = round(preis / 100, 2) if isinstance(preis, (int, float)) else None
    db.produkt_details(con, {
        "id": pid, "brand": d.get("brand") or None, "description": d.get("description") or d.get("regulatedProductName") or None,
        "ean": ean, "size_value": groesse, "size_unit": einheit, "price_per": grundpreis(preis, groesse, einheit),
    })
    meta = {"ean": ean, "marke": d.get("brand") or None}
    status = naehrwerte.rewe_speichern(con, pid, parse_naehrwerte(d.get("nutritionFacts")), "rewe", meta, run_id)
    stand = naehrwerte.rewe_werte(con, pid)
    if stand["quelle"] != "rewe" and ean and status in ("leer", "unplausibel"):
        try:
            off = rewe.openfoodfacts(ean)
        except rewe.OffLimit:
            off = None
            db.log(con, run_id, "warn", "Open Food Facts: Anfrage-Limit erreicht", {"rewe_product_id": pid, "ean": ean})
        if off:
            status = "off_" + naehrwerte.rewe_speichern(con, pid, off, "openfoodfacts", meta, run_id)
            stand = naehrwerte.rewe_werte(con, pid)
    return {"rewe_product_id": pid, "naehrwerte": status, "hat_naehrwerte": bool(stand["werte"]),
            "quelle": stand["quelle"], "werte": stand["werte"], "ean": ean}


class Crawler:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.run_id: int | None = None

    @property
    def laeuft(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def beim_start_aufraeumen(self) -> None:
        """Läufe, die beim letzten Beenden noch liefen, gelten als abgebrochen (fortsetzbar)."""
        with db.verbinden() as con:
            con.execute("UPDATE crawl_runs SET status = 'abgebrochen' WHERE status = 'laeuft'")

    def starten(self, params: dict, neu: bool = False) -> dict:
        if self.laeuft:
            return {"status": "laeuft_bereits", "run_id": self.run_id}
        rewe.markt_id()
        rewe.client()
        with db.verbinden() as con:
            offen = None if neu else con.execute(
                "SELECT id, params FROM crawl_runs WHERE status = 'abgebrochen' ORDER BY id DESC LIMIT 1").fetchone()
            if offen:
                run_id, params = offen[0], offen[1]
                con.execute("UPDATE crawl_runs SET status = 'laeuft' WHERE id = %s", (run_id,))
                fortgesetzt = True
            else:
                con.execute("UPDATE crawl_runs SET status = 'verworfen' WHERE status = 'abgebrochen'")
                run_id = con.execute("INSERT INTO crawl_runs (status, params) VALUES ('laeuft', %s) RETURNING id",
                                     (Jsonb(params),)).fetchone()[0]
                fortgesetzt = False
        self.run_id = run_id
        self._stop.clear()
        self._thread = threading.Thread(target=self._laufen, args=(run_id, params), daemon=True)
        self._thread.start()
        return {"status": "gestartet", "run_id": run_id, "fortgesetzt": fortgesetzt, "params": params}

    def stoppen(self) -> None:
        self._stop.set()

    # --- eigentlicher Lauf -------------------------------------------------------------------------

    def _laufen(self, run_id: int, params: dict) -> None:
        with db.verbinden() as con:
            cursor, stats = con.execute("SELECT cursor, stats FROM crawl_runs WHERE id = %s", (run_id,)).fetchone()
            stats = {"neu": 0, "aktualisiert": 0, "name_groesse_geaendert": 0, "details": 0, "erneuert": 0, "ohne_groesse": 0,
                     "ohne_naehrwerte": 0, "fehler": 0, **stats}
            status = "fertig"
            try:
                if cursor.get("phase", "liste") == "liste":
                    cursor = self._phase_liste(con, run_id, params, cursor, stats)
                if cursor.get("phase") == "details" and params.get("details", True) and not self._stop.is_set():
                    self._phase_details(con, run_id, params, cursor, stats)
                if self._stop.is_set():
                    status = "abgebrochen"
            except _Abbruch as e:
                status = "abgebrochen"
                db.log(con, run_id, "error", f"Crawl abgebrochen: {e}")
            except Exception as e:  # noqa: BLE001 - Lauf soll sauber als Fehler enden
                status = "abgebrochen"
                stats["fehler"] += 1
                db.log(con, run_id, "error", f"Unerwarteter Fehler: {e!r}")
                log.exception("Crawl-Fehler")
            con.execute("UPDATE crawl_runs SET status = %s, stats = %s, finished_at = CASE WHEN %s = 'fertig' THEN now() END "
                        "WHERE id = %s", (status, Jsonb(stats), status, run_id))

    def _speichern(self, con, run_id, cursor, stats):
        con.execute("UPDATE crawl_runs SET cursor = %s, stats = %s WHERE id = %s", (Jsonb(cursor), Jsonb(stats), run_id))

    def _mit_wiederholung(self, con, run_id, stats, fehler_in_folge, methode, *args, **kwargs):
        try:
            ergebnis = rewe.aufruf(methode, *args, **kwargs)
            fehler_in_folge[0] = 0
            return ergebnis
        except Exception as e:  # noqa: BLE001
            stats["fehler"] += 1
            fehler_in_folge[0] += 1
            db.log(con, run_id, "warn", f"{methode} fehlgeschlagen: {e}", {"args": [str(a) for a in args]})
            if fehler_in_folge[0] >= MAX_FEHLER_IN_FOLGE:
                raise _Abbruch(f"{MAX_FEHLER_IN_FOLGE} Fehler in Folge, zuletzt: {e}") from e
            time.sleep(30)
            return None

    def _phase_liste(self, con, run_id, params, cursor, stats) -> dict:
        fehler = [0]
        if "kategorien" not in cursor:
            shop = rewe.aufruf("shop_uebersicht")
            cursor = {"phase": "liste", "kategorien": kategorien_aufloesen(shop, params.get("kategorien"), con, run_id),
                      "k": 0, "seite": 1}
            self._speichern(con, run_id, cursor, stats)
        max_seiten = params.get("max_seiten")
        while cursor["k"] < len(cursor["kategorien"]) and not self._stop.is_set():
            kat = cursor["kategorien"][cursor["k"]]
            erg = self._mit_wiederholung(con, run_id, stats, fehler, "kategorie_produkte", kat["slug"],
                                         page=cursor["seite"], objects_per_page=PRO_SEITE)
            if erg is None:
                erg = self._mit_wiederholung(con, run_id, stats, fehler, "kategorie_produkte", kat["slug"],
                                             page=cursor["seite"], objects_per_page=PRO_SEITE)
            seiten = 0
            if erg is not None:
                for p in erg.get("products") or []:
                    daten = listen_produkt(p, kat["name"])
                    if daten["size_value"] is None:
                        stats["ohne_groesse"] += 1
                        db.log(con, run_id, "warn", "Größe nicht erkannt",
                               {"rewe_product_id": daten["id"], "name": daten["name"], "grammage": daten["grammage"]})
                    ergebnis = db.produkt_aus_liste(con, daten)
                    stats["neu" if ergebnis == "neu" else "aktualisiert"] += 1
                    if ergebnis == "geaendert":
                        stats["name_groesse_geaendert"] += 1
                        db.log(con, run_id, "info", "Name oder Größe geändert, Details werden neu geholt",
                               {"rewe_product_id": daten["id"], "name": daten["name"], "grammage": daten["grammage"]})
                seiten = int((erg.get("pagination") or {}).get("pageCount") or 0)
            letzte = cursor["seite"] >= seiten or (max_seiten and cursor["seite"] >= max_seiten)
            cursor = {**cursor, "k": cursor["k"] + 1, "seite": 1} if letzte else {**cursor, "seite": cursor["seite"] + 1}
            self._speichern(con, run_id, cursor, stats)
        if cursor["k"] >= len(cursor["kategorien"]):
            cursor = {**cursor, "phase": "details", "details_erledigt": 0}
            self._speichern(con, run_id, cursor, stats)
        return cursor

    def _naechstes_detail(self, con, run_id, params, cursor):
        """Reihenfolge: ohne Details (neu oder Name/Größe geändert), dann die ältesten Details bis zur Grenze.

        Alles, was in diesem Lauf schon geholt wurde, hat details_fetched_at > Laufbeginn und kommt nicht erneut.
        """
        grenze = params.get("max_erneuern")
        grenze = DETAILS_ERNEUERN if grenze is None else grenze
        return con.execute("""
            SELECT p.rewe_product_id, p.details_fetched_at IS NOT NULL
            FROM rewe_products p, crawl_runs r
            WHERE r.id = %(run)s
              AND (p.details_fetched_at IS NULL OR (%(erneuert)s < %(grenze)s AND p.details_fetched_at < r.started_at))
            ORDER BY p.details_fetched_at IS NOT NULL, p.details_fetched_at, p.first_seen, p.rewe_product_id
            LIMIT 1""", {"run": run_id, "erneuert": cursor.get("erneuert", 0), "grenze": grenze}).fetchone()

    def _phase_details(self, con, run_id, params, cursor, stats) -> None:
        fehler = [0]
        grenze = params.get("max_details")
        while not self._stop.is_set():
            if grenze is not None and cursor["details_erledigt"] >= grenze:
                break
            zeile = self._naechstes_detail(con, run_id, params, cursor)
            if not zeile:
                break
            pid, erneuerung = zeile
            if erneuerung:
                cursor["erneuert"] = cursor.get("erneuert", 0) + 1
                stats["erneuert"] += 1
            d = self._mit_wiederholung(con, run_id, stats, fehler, "produkt_detail", pid)
            if d is None:
                # nach einem Einzelfehler nicht endlos am selben Produkt hängen bleiben
                con.execute("UPDATE rewe_products SET details_fetched_at = now() WHERE rewe_product_id = %s", (pid,))
                self._speichern(con, run_id, cursor, stats)
                continue
            erg = details_uebernehmen(con, pid, d, run_id)
            if not erg["hat_naehrwerte"]:
                stats["ohne_naehrwerte"] += 1
            stats["details"] += 1
            cursor["details_erledigt"] += 1
            self._speichern(con, run_id, cursor, stats)


class _Abbruch(RuntimeError):
    pass
