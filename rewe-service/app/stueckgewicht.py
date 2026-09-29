"""Stückgewicht (essbarer Anteil) – Referenztabelle und Gewichtsklassen folgen in Paket 5."""

from __future__ import annotations

from . import naehrwerte as nw


def bestimmen(con, a: dict) -> dict | None:
    """Übergebenes Stückgewicht (ki oder manuell) durchreichen, nur bei Stückware."""
    if str(a.get("einheit") or "").lower() not in ("stk", "stück"):
        return None
    g = nw._zahl(a.get("gramm_pro_stk"))
    q = a.get("gramm_quelle") if a.get("gramm_quelle") in nw.GRAMM_RANG else "ki"
    return {"gramm": g, "quelle": q, "rang": nw.GRAMM_RANG[q], "detail": None} if g and g > 0 else None
