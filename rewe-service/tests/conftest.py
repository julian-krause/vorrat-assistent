"""Crawler-Tests laufen gegen eine eigene Datenbank rewe_test auf demselben Postgres-Server."""

import os

import psycopg
import pytest

_BASIS = os.environ.get("DATABASE_URL", "")
if _BASIS:
    _TEST_URL = _BASIS.rsplit("/", 1)[0] + "/rewe_test"
    os.environ["DATABASE_URL"] = _TEST_URL


@pytest.fixture()
def test_db():
    if not _BASIS:
        pytest.skip("DATABASE_URL nicht gesetzt (Test läuft im rewe-service-Container)")
    with psycopg.connect(_BASIS, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS rewe_test WITH (FORCE)")
        admin.execute("CREATE DATABASE rewe_test")
    from app import db
    db.DATABASE_URL = _TEST_URL
    db.schema_anlegen()
    yield db
    with psycopg.connect(_BASIS, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS rewe_test WITH (FORCE)")


# --- Echter Katalog für die eBon-Prüfstände -----------------------------------------------------------------------------
# tests/daten/*.csv.gz sind ein Read-only-Export der Produktiv-Tabellen (Katalog, Preisverlauf, Lerntabelle, Vorratsprodukte).
DATEN = os.path.join(os.path.dirname(__file__), "daten")


def _csv_laden(con, tabelle):
    import gzip
    with gzip.open(os.path.join(DATEN, tabelle + ".csv.gz"), "rt", encoding="utf-8") as f:
        kopf = f.readline().strip()
        with con.cursor().copy(f"COPY {tabelle} ({kopf}) FROM STDIN WITH CSV") as cp:
            while chunk := f.read(1 << 16):
                cp.write(chunk)


@pytest.fixture()
def echtkatalog(test_db):
    """Test-DB mit dem echten Katalog. Die Lerntabelle bleibt leer (lerntabelle_laden füllt sie)."""
    with test_db.verbinden() as con:
        _csv_laden(con, "rewe_products")
        _csv_laden(con, "rewe_price_history")
        con.execute("UPDATE rewe_products SET last_seen = now()")
    return test_db


def lerntabelle_laden(con):
    _csv_laden(con, "bon_zuordnung")
