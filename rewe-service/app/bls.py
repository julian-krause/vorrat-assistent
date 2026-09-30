"""Bundeslebensmittelschlüssel (BLS) 4.0: Import und Suche.

Quelle: Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 — Deutsche Nährstoffdatenbank.
Karlsruhe. DOI: 10.25826/Data20251217-134202-0. Lizenz CC BY 4.0.
"""

from __future__ import annotations

import csv
import gzip
import logging
import re
from pathlib import Path

from . import text
from .text import normalisieren

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


_STOPP = {"stueck", "stk", "bio", "frisch", "vorgereift", "reif", "lose", "packung", "beutel", "schale", "netz",
          "klasse", "groesse", "gramm", "ca", "und", "mit", "ohne", "der", "die", "das", "rewe", "ja", "beste", "wahl"}
_SYNONYME = {"eier": "huehnerei", "ei": "huehnerei", "moehren": "moehre", "karotte": "moehre", "karotten": "moehre",
             "kartoffeln": "kartoffel", "tomaten": "tomate", "zwiebeln": "zwiebel", "aepfel": "apfel", "bananen": "banane",
             "birnen": "birne", "zitronen": "zitrone", "orangen": "orange", "gurken": "gurke", "pflaumen": "pflaume",
             "freilandeier": "huehnerei", "bioeier": "huehnerei"}


def suchwoerter(begriff: str) -> list[str]:
    """Suchwörter in gemeinsamer Normalisierung (ä -> ae, …), Mehrzahl auf BLS-Form, ohne Füllwörter."""
    woerter = []
    for w in normalisieren(begriff).split():
        w = _SYNONYME.get(w, w)
        if len(w) >= 3 and w not in _STOPP and not w.isdigit() and w not in woerter:
            woerter.append(w)
    return woerter


def _wort_teile(wort: str) -> list[str]:
    """Zusammengesetzte Wörter zerlegen („Romatomaten“ -> tomate): Endteile ab 5 Buchstaben ohne Mehrzahl-Endung, längste zuerst."""
    stamm = re.sub(r"(en|n|e|s)$", "", wort)
    return [stamm[i:] for i in range(1, len(stamm) - 4) if len(stamm[i:]) >= 5]


def suche(con, begriff: str, anzahl: int = 8) -> list[dict]:
    """Kandidaten für die KI: meiste Wort-Treffer im BLS-Namen zuerst (Marke, Größe, „Bio“ usw. zählen nicht),
    dann Rohware, dann Ähnlichkeit. Schreibvarianten/Synonyme (Tabelle suchsynonyme) werden mitgesucht; findet sich nichts,
    werden zusammengesetzte Wörter in ihre Endteile zerlegt."""
    for zerlegen in (False, True):
        treffer = _suche(con, begriff, anzahl, zerlegen)
        if treffer:
            return treffer
    return []


def _suche(con, begriff: str, anzahl: int, zerlegen: bool) -> list[dict]:
    treffer: dict[str, tuple] = {}
    for v in text.varianten(con, begriff) or [normalisieren(begriff)]:
        woerter = suchwoerter(v)
        if zerlegen:
            # nur Wörter ohne eigenen Treffer und ab 8 Buchstaben zerlegen; andere unbekannte Wörter (Marken, „Cherry“) bleiben außen vor
            def im_bls(w):
                return con.execute("SELECT 1 FROM bls WHERE suchtext LIKE %s LIMIT 1", ("%" + w + "%",)).fetchone() is not None
            def teil(w):
                return next((t for t in _wort_teile(w) if im_bls(t)), None)
            woerter = [w for w in woerter if im_bls(w)] + [t for t in (teil(w) for w in woerter if not im_bls(w) and len(w) >= 8) if t]
        if not woerter:
            continue
        zeilen = con.execute(f"""
            SELECT code, name, {', '.join(_FELDER)}, treffer, roh, aehnlich FROM (
                SELECT b.*, (SELECT count(*) FROM unnest(%(w)s::text[]) w WHERE b.suchtext LIKE '%%' || w || '%%') AS treffer,
                       (b.suchtext LIKE '%%roh%%') AS roh, similarity(b.suchtext, %(b)s) AS aehnlich
                FROM bls b
            ) x WHERE treffer > 0
            ORDER BY treffer DESC, roh DESC, aehnlich DESC, length(name)
            LIMIT %(n)s""", {"w": woerter, "b": " ".join(woerter), "n": anzahl}).fetchall()
        for z in zeilen:
            schluessel = (-(z[-3] / len(woerter)), not z[-2], -z[-1], len(z[1]))
            if z[0] not in treffer or schluessel < treffer[z[0]][0]:
                treffer[z[0]] = (schluessel, z[:-3])
    return [_eintrag(z) for _, z in sorted(treffer.values(), key=lambda t: t[0])[:anzahl]]
