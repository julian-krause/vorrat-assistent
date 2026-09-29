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
