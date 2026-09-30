"""Postgres-Zugriff: Schema anlegen, n8n-Rolle einrichten, Produkte upserten."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ["DATABASE_URL"]


def verbinden() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _normalisierung_migrieren(con) -> None:
    """Gelernte Kassentexte mit der gemeinsamen Normalisierung (ä -> ae statt ä -> a) neu schlüsseln; idempotent."""
    con.execute("""UPDATE bon_zuordnung z SET bon_text_norm = norm_text(z.bon_text)
                   WHERE z.bon_text_norm <> norm_text(z.bon_text)
                     AND NOT EXISTS (SELECT 1 FROM bon_zuordnung o WHERE o.bon_text_norm = norm_text(z.bon_text))""")
    con.execute("""UPDATE bon_zeilen z SET bon_text_norm = norm_text(z.bon_text)
                   WHERE z.bon_text_norm <> norm_text(z.bon_text)
                     AND NOT EXISTS (SELECT 1 FROM bon_zeilen o WHERE o.bon_id = z.bon_id AND o.bon_text_norm = norm_text(z.bon_text))""")


def schema_anlegen() -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    from . import bls, stueckgewicht, text
    with verbinden() as con:
        con.execute(schema)
        text.synonyme_laden(con)
        text.oberbegriffe_laden(con)
        _normalisierung_migrieren(con)
        bls.laden(con)
        stueckgewicht.referenz_laden(con)
        n8n_passwort = os.environ.get("REWE_DB_N8N_PASSWORD")
        if n8n_passwort:
            # Eigene Rolle für n8n: darf lesen und nur die Angebotsfelder ändern.
            con.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n') THEN CREATE ROLE n8n LOGIN; END IF;
                END $$""")
            con.execute(sql.SQL("ALTER ROLE n8n PASSWORD {}").format(sql.Literal(n8n_passwort)))
            con.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO n8n")
            con.execute("GRANT UPDATE (angebotspreis, angebot_bis) ON rewe_products TO n8n")
            con.execute("GRANT EXECUTE ON FUNCTION produkt_suche(text, integer) TO n8n")
            # Ist-Verbrauch: n8n trägt ein (Abgleich, Rezepte, Agent) und markiert Korrekturen als ignoriert
            con.execute("GRANT SELECT, INSERT, UPDATE ON verzehr TO n8n")
            con.execute("GRANT USAGE ON SEQUENCE verzehr_id_seq TO n8n")
            con.execute("GRANT EXECUTE ON FUNCTION verzehr_auswertung(date, date) TO n8n")
            # Vorratsprodukte: n8n darf lesen und schreiben (die Workflows schreiben über den rewe-service, der die
            # Rangregel prüft); sonst keine weiteren Schreibrechte auf Produktdaten
            con.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON vorrat_produkte TO n8n")
            # Nachtjob verschickt Meldungen per Telegram und markiert sie als gesendet
            con.execute("GRANT UPDATE (gesendet_at) ON meldungen TO n8n")
            # Chat-Gedächtnis des Telegram-Agenten (n8n „Postgres Chat Memory“ legt seine Tabelle selbst an):
            # eigenes Schema, das n8n gehört – so braucht n8n keine Schreibrechte auf die Produktdaten
            con.execute("CREATE SCHEMA IF NOT EXISTS chat AUTHORIZATION n8n")
            con.execute("ALTER ROLE n8n SET search_path = chat, public")


def log(con: psycopg.Connection, run_id: int | None, level: str, message: str, payload: dict | None = None) -> None:
    con.execute("INSERT INTO crawl_log (run_id, level, message, payload) VALUES (%s, %s, %s, %s)",
                (run_id, level, message, Jsonb(payload) if payload is not None else None))


def produkt_aus_liste(con: psycopg.Connection, p: dict) -> str:
    """Upsert aus der Listenansicht (Preis, Größe, last_seen) + Preisverlauf.

    Rückgabe: neu | geaendert (Name oder Größenangabe anders -> Details werden im selben Lauf neu geholt) | gleich.
    """
    alt = con.execute("SELECT name, grammage_raw, details_fetched_at FROM rewe_products WHERE rewe_product_id = %s",
                      (p["id"],)).fetchone()
    con.execute("""
        INSERT INTO rewe_products (rewe_product_id, article_id, ean, name, category, size_value, size_unit, grammage_raw,
                                   price, price_per_kg_or_l, is_organic, is_vegan, is_vegetarian)
        VALUES (%(id)s, %(article_id)s, %(ean)s, %(name)s, %(category)s, %(size_value)s, %(size_unit)s, %(grammage)s,
                %(price)s, %(price_per)s, %(bio)s, %(vegan)s, %(vegetarisch)s)
        ON CONFLICT (rewe_product_id) DO UPDATE SET
            article_id = EXCLUDED.article_id, ean = coalesce(EXCLUDED.ean, rewe_products.ean), name = EXCLUDED.name,
            category = coalesce(rewe_products.category, EXCLUDED.category),
            size_value = coalesce(EXCLUDED.size_value, rewe_products.size_value),
            size_unit = coalesce(EXCLUDED.size_unit, rewe_products.size_unit),
            grammage_raw = EXCLUDED.grammage_raw, price = EXCLUDED.price,
            price_per_kg_or_l = coalesce(EXCLUDED.price_per_kg_or_l, rewe_products.price_per_kg_or_l),
            is_organic = EXCLUDED.is_organic, is_vegan = EXCLUDED.is_vegan, is_vegetarian = EXCLUDED.is_vegetarian,
            last_seen = now()""", p)
    if p.get("price") is not None:
        con.execute("INSERT INTO rewe_price_history (rewe_product_id, price) VALUES (%s, %s)", (p["id"], p["price"]))
    if alt is None:
        return "neu"
    if (alt[0], alt[1]) != (p["name"], p.get("grammage")):
        if alt[2] is not None:
            con.execute("UPDATE rewe_products SET details_fetched_at = NULL WHERE rewe_product_id = %s", (p["id"],))
        return "geaendert"
    return "gleich"


def produkt_details(con: psycopg.Connection, d: dict) -> None:
    """Stammdaten aus der Detailansicht; Nährwerte schreibt nur naehrwerte.rewe_speichern. Leeres überschreibt nie."""
    con.execute("""
        UPDATE rewe_products SET
            brand = coalesce(%(brand)s, brand), description = coalesce(%(description)s, description), ean = coalesce(%(ean)s, ean),
            size_value = coalesce(size_value, %(size_value)s), size_unit = coalesce(size_unit, %(size_unit)s),
            price_per_kg_or_l = coalesce(price_per_kg_or_l, %(price_per)s), details_fetched_at = now()
        WHERE rewe_product_id = %(id)s""", d)
