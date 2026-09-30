"""Gemeinsame Textnormalisierung und Katalogsuche für Katalogsuche, eBon-Zuordnung, Planer und BLS.

Normalisierung (auch als SQL-Funktion norm_text in schema.sql, beide müssen dasselbe ergeben):
Kleinbuchstaben, ä/ö/ü/ß -> ae/oe/ue/ss, übrige Akzente weg, alles außer a-z und 0-9 wird zum Leerzeichen.
„HAEHNCHENBRUST“ und „Hähnchenbrust“ ergeben beide „haehnchenbrust“.

Synonyme/Schreibvarianten stehen in der Tabelle suchsynonyme (Gruppen gleichbedeutender Begriffe, Startdaten in
daten/synonyme.csv, Ergänzungen per POST /synonyme). Die Suche erweitert jede Anfrage um alle Varianten
(SQL-Funktion suchvarianten) und bewertet Treffer nach Trigramm-Ähnlichkeit plus Wortabdeckung (SQL-Funktion katalog_treffer).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

SYNONYM_DATEI = Path(__file__).parent.parent / "daten" / "synonyme.csv"
OBERBEGRIFF_DATEI = Path(__file__).parent.parent / "daten" / "oberbegriffe.csv"

_AKZENT_VON = "àáâãåçèéêëìíîïñòóôõùúûýÿ"
_AKZENT_NACH = "aaaaaceeeeiiiinoooouuuyy"
_UMLAUTE = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))
assert len(_AKZENT_VON) == len(_AKZENT_NACH)


def normalisieren(text) -> str:
    """Kleinbuchstaben, ä->ae/ö->oe/ü->ue/ß->ss, übrige Akzente weg, nur a-z, 0-9 und einfache Leerzeichen."""
    t = str(text or "").lower()
    for a, b in _UMLAUTE:
        t = t.replace(a, b)
    t = t.translate(str.maketrans(_AKZENT_VON, _AKZENT_NACH))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def skelett(t: str) -> str:
    """Umlaut-Auflösung wieder zurück (ae -> a, oe -> o, ue -> u): für abgekürzte Kassentexte („HAHN.“ = Hähnchen)."""
    return t.replace("ae", "a").replace("oe", "o").replace("ue", "u")


def synonyme_laden(con) -> int:
    """Startdaten aus daten/synonyme.csv in die Tabelle übernehmen (ergänzt nur, überschreibt/löscht nie Pflege in der DB)."""
    if not SYNONYM_DATEI.is_file():
        return 0
    neu = 0
    with open(SYNONYM_DATEI, encoding="utf-8") as f:
        for z in csv.DictReader(f):
            if not z.get("gruppe") or not z.get("begriff"):
                continue
            neu += con.execute("INSERT INTO suchsynonyme (gruppe, begriff, quelle) VALUES (%s, norm_text(%s), 'datei') ON CONFLICT DO NOTHING",
                               (z["gruppe"].strip(), z["begriff"])).rowcount
    return neu


def oberbegriffe_laden(con) -> int:
    if not OBERBEGRIFF_DATEI.is_file():
        return 0
    neu = 0
    with open(OBERBEGRIFF_DATEI, encoding="utf-8") as f:
        for z in csv.DictReader(f):
            if z.get("oberbegriff") and z.get("mitglied"):
                neu += con.execute("INSERT INTO ausschluss_oberbegriffe (oberbegriff, mitglied) VALUES (norm_text(%s), norm_text(%s)) ON CONFLICT DO NOTHING",
                                   (z["oberbegriff"], z["mitglied"])).rowcount
    return neu


def synonym_hinzufuegen(con, gruppe: str, begriffe: list[str]) -> int:
    gruppe = normalisieren(gruppe) or normalisieren(begriffe[0] if begriffe else "")
    n = 0
    for b in begriffe:
        if normalisieren(b):
            n += con.execute("INSERT INTO suchsynonyme (gruppe, begriff, quelle) VALUES (%s, norm_text(%s), 'manuell') ON CONFLICT DO NOTHING",
                             (gruppe, b)).rowcount
    return n


def varianten(con, anfrage: str) -> list[str]:
    """Normalisierte Anfrage plus alle Synonym-Ersetzungen."""
    return con.execute("SELECT suchvarianten(%s)", (anfrage,)).fetchone()[0]


def suche(con, anfrage: str, schwelle: float = 0.45, anzahl: int = 30) -> list[dict]:
    """Katalog nach Ähnlichkeit durchsuchen: [{rewe_product_id, score, abdeckung}], bester zuerst, unter der Schwelle nichts."""
    if not normalisieren(anfrage):
        return []
    return [{"rewe_product_id": r[0], "score": round(float(r[1]), 3), "abdeckung": round(float(r[2]), 3)}
            for r in con.execute("SELECT rewe_product_id, score, abdeckung FROM katalog_treffer(%s, %s::real, %s::integer)",
                                 (anfrage, schwelle, anzahl))]
