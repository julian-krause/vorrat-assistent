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


def schema_anlegen() -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with verbinden() as con:
        con.execute(schema)
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


def log(con: psycopg.Connection, run_id: int | None, level: str, message: str, payload: dict | None = None) -> None:
    con.execute("INSERT INTO crawl_log (run_id, level, message, payload) VALUES (%s, %s, %s, %s)",
                (run_id, level, message, Jsonb(payload) if payload is not None else None))


def produkt_aus_liste(con: psycopg.Connection, p: dict) -> bool:
    """Upsert aus der Listenansicht (Preis, Größe, last_seen) + Preisverlauf. True = neues Produkt."""
    zeile = con.execute("""
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
            last_seen = now()
        RETURNING (xmax = 0) AS neu""", p).fetchone()
    if p.get("price") is not None:
        con.execute("INSERT INTO rewe_price_history (rewe_product_id, price) VALUES (%s, %s)", (p["id"], p["price"]))
    return bool(zeile and zeile[0])


def produkt_details(con: psycopg.Connection, d: dict) -> None:
    con.execute("""
        UPDATE rewe_products SET
            brand = %(brand)s, description = %(description)s, ean = coalesce(%(ean)s, ean),
            size_value = coalesce(size_value, %(size_value)s), size_unit = coalesce(size_unit, %(size_unit)s),
            price_per_kg_or_l = coalesce(price_per_kg_or_l, %(price_per)s),
            kcal_100 = %(kcal)s, protein_100 = %(protein)s, kh_100 = %(kh)s, fett_100 = %(fett)s,
            naehrwerte_quelle = %(quelle)s, details_fetched_at = now()
        WHERE rewe_product_id = %(id)s""", d)
