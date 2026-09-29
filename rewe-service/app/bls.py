"""Bundeslebensmittelschlüssel (BLS) 4.0: Import und Suche.

Quelle: Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 — Deutsche Nährstoffdatenbank.
Karlsruhe. DOI: 10.25826/Data20251217-134202-0. Lizenz CC BY 4.0.
"""

from __future__ import annotations

import csv
import gzip
import logging
from pathlib import Path

log = logging.getLogger("bls")
DATEI = Path(__file__).parent.parent / "daten" / "bls_4_0.csv.gz"
QUELLE = "Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0"
_FELDER = ("kcal", "protein", "fett", "kh", "zucker", "ballaststoffe", "salz")


def laden(con) -> int:
    """BLS-Tabelle aus der CSV füllen, wenn sie fehlt oder unvollständig ist."""
    if not DATEI.is_file():
        log.warning("BLS-Datei fehlt: %s", DATEI)
        return 0
    with gzip.open(DATEI, "rt", encoding="utf-8") as f:
        zeilen = list(csv.DictReader(f))
    if con.execute("SELECT count(*) FROM bls").fetchone()[0] == len(zeilen):
        return 0
    con.execute("TRUNCATE bls")
    with con.cursor().copy("COPY bls (code, name, name_en, kcal, protein, fett, kh, zucker, ballaststoffe, salz) FROM STDIN") as cp:
        for z in zeilen:
            cp.write_row([z["code"], z["name"], z["name_en"]] + [z[k] or None for k in _FELDER])
    log.info("BLS geladen: %s Einträge", len(zeilen))
    return len(zeilen)


def _eintrag(z) -> dict:
    return {"code": z[0], "name": z[1], "werte": {k: float(v) for k, v in zip(_FELDER, z[2:]) if v is not None}}


def eintrag(con, code: str) -> dict | None:
    z = con.execute(f"SELECT code, name, {', '.join(_FELDER)} FROM bls WHERE code = %s", (str(code).strip(),)).fetchone()
    return _eintrag(z) if z else None


_STOPP = {"stück", "stueck", "stk", "bio", "frisch", "vorgereift", "reif", "lose", "packung", "beutel", "schale", "netz",
          "klasse", "größe", "groesse", "gramm", "ca", "und", "mit", "ohne", "der", "die", "das", "rewe", "ja", "beste", "wahl"}
_SYNONYME = {"eier": "hühnerei", "ei": "hühnerei", "möhren": "möhre", "karotte": "möhre", "karotten": "möhre",
             "kartoffeln": "kartoffel", "tomaten": "tomate", "zwiebeln": "zwiebel", "äpfel": "apfel", "bananen": "banane",
             "birnen": "birne", "zitronen": "zitrone", "orangen": "orange", "gurken": "gurke", "pflaumen": "pflaume",
             "freilandeier": "hühnerei", "bioeier": "hühnerei"}


def suchwoerter(begriff: str) -> list[str]:
    import re
    woerter = []
    for w in re.findall(r"[a-zäöüß]+", str(begriff or "").lower()):
        w = _SYNONYME.get(w, w)
        if len(w) >= 3 and w not in _STOPP and w not in woerter:
            woerter.append(w)
    return woerter


def suche(con, begriff: str, anzahl: int = 8) -> list[dict]:
    """Kandidaten für die KI: meiste Wort-Treffer im BLS-Namen zuerst (Marke, Größe, „Bio“ usw. zählen nicht),
    dann Rohware, dann Ähnlichkeit."""
    woerter = suchwoerter(begriff)
    if not woerter:
        return []
    zeilen = con.execute(f"""
        SELECT code, name, {', '.join(_FELDER)} FROM (
            SELECT b.*, (SELECT count(*) FROM unnest(%(w)s::text[]) w WHERE lower(b.name) LIKE '%%' || w || '%%') AS treffer
            FROM bls b
        ) x WHERE treffer > 0
        ORDER BY treffer DESC, (lower(name) LIKE '%%roh%%') DESC, similarity(name, %(b)s) DESC, length(name)
        LIMIT %(n)s""", {"w": woerter, "b": " ".join(woerter), "n": anzahl}).fetchall()
    return [_eintrag(z) for z in zeilen]
