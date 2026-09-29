"""Bundeslebensmittelschlüssel (BLS 4.0) – Import und Suche folgen in Paket 5."""

from __future__ import annotations


def eintrag(con, code: str) -> dict | None:
    return None


def suche(con, begriff: str, anzahl: int = 8) -> list[dict]:
    return []
