"""Stückgewicht (immer essbarer Anteil): manuell (1) → Packung/Gewichtsklasse (2) → Referenz (3) → KI (4)."""

from __future__ import annotations

import re

from . import naehrwerte as nw

_USDA = "USDA SR Legacy/SR28 (FoodData Central)"
_EIER = ("Gewichtsklassen nach VO (EG) Nr. 589/2008 (Klassenmitte; XL mit 76 g angenommen), "
         "essbarer Anteil 88 % laut USDA SR28 NDB 01123 (12 % Schale)")
# schluessel, bezeichnung, muster, prioritaet, gramm_essbar, anteil_essbar, quelle
REFERENZ = [
    ("ei_s", "Ei Größe S (< 53 g)", r"$^", 10, 42, 0.88, _EIER),
    ("ei_m", "Ei Größe M (53–63 g), auch ohne Angabe", r"eier\b|\bei\b", 10, 51, 0.88, _EIER),
    ("ei_l", "Ei Größe L (63–73 g)", r"$^", 10, 60, 0.88, _EIER),
    ("ei_xl", "Ei Größe XL (≥ 73 g)", r"$^", 10, 67, 0.88, _EIER),
    ("kiwi_gold", "Kiwi Gold", r"kiwi.*gold|gold.*kiwi|sungold", 20, 81, 0.72, _USDA + " NDB 09520: 1 fruit 81 g, Abfall 28 % (Schale)"),
    ("kiwi", "Kiwi (grün)", r"\bkiwi", 30, 69, 0.76, _USDA + " NDB 09148: 1 fruit (2\" dia) 69 g, Abfall 24 % (Schale)"),
    ("avocado", "Avocado (Hass)", r"avocado", 30, 136, 0.67,
     _USDA + " NDB 09038 (California = Hass): 1 fruit without skin and seed 136 g, Abfall 33 % (Kern und Schale)"),
    ("banane", "Banane", r"banane", 30, 118, 0.64, _USDA + " NDB 09040: medium 118 g, Abfall 36 % (Schale)"),
    ("apfel", "Apfel", r"\b(apfel|äpfel|aepfel)\b", 30, 182, 0.90, _USDA + " NDB 09003: medium (3\" dia) 182 g, Abfall 10 % (Kerngehäuse, Stiel)"),
    ("birne", "Birne", r"\bbirnen?\b", 30, 178, 0.90, _USDA + " NDB 09252: medium 178 g, Abfall 10 %"),
    ("zitrone", "Zitrone", r"zitrone", 30, 58, 0.53, _USDA + " NDB 09150: fruit (2-1/8\" dia) 58 g ohne Schale, Abfall 47 % (Schale, Kerne)"),
    ("orange", "Orange", r"\borangen?\b", 30, 131, 0.73, _USDA + " NDB 09200: fruit (2-5/8\" dia) 131 g, Abfall 27 % (Schale, Kerne)"),
    ("tomate", "Tomate (mittel, keine Cherry-/Cocktailtomate)", r"tomate(?!n?mark)", 30, 123, 0.91,
     _USDA + " NDB 11529: medium whole 123 g, Abfall 9 % (Strunk)"),
    ("paprika", "Paprika", r"paprika(?!pulver|mark)", 30, 119, 0.82, _USDA + " NDB 11821: medium 119 g, Abfall 18 % (Stiel, Kerne)"),
    ("zwiebel", "Zwiebel", r"(?<!früh)(?<!lauch)zwiebel", 30, 110, 0.90, _USDA + " NDB 11282: medium (2-1/2\" dia) 110 g, Abfall 10 %"),
    ("kartoffel", "Kartoffel", r"kartoffel", 30, 213, 0.75, _USDA + " NDB 11352: medium 213 g, Abfall 25 % (Schälverlust)"),
    ("karotte", "Karotte/Möhre", r"karotte|möhre|moehre", 30, 61, 0.89, _USDA + " NDB 11124: medium 61 g, Abfall 11 %"),
    ("gurke", "Salatgurke", r"(?<!gewürz)gurke", 30, 301, 0.97, _USDA + " NDB 11205: 1 cucumber (8-1/4\") 301 g, Abfall 3 % (Enden)"),
    ("zucchini", "Zucchini", r"zucchini", 30, 196, 0.95, _USDA + " NDB 11477: medium 196 g, Abfall 5 % (Enden)"),
    ("pflaume", "Pflaume", r"pflaume", 30, 66, 0.94, _USDA + " NDB 09279: fruit 66 g, Abfall 6 % (Stein)"),
]
_AUSNAHMEN = re.compile(r"cherry|cocktail|datteltomate|mini|saft|mus|chips|getrocknet|pulver|konserve|dose|püree", re.I)
# Gewichtsklasse im Namen: „Eier M“, „Gr. L“, „Größe XL“, „M/L“ (gemischt -> Mittelwert)
_KLASSE = re.compile(r"(?:\b(?:gr(?:ö|oe)(?:ß|ss)e|gr\.|klasse|kl\.)\s*)?\b(XL|S|M|L)(?:\s*/\s*(XL|M|L))?\b")


def referenz_laden(con) -> None:
    for z in REFERENZ:
        con.execute("""
            INSERT INTO stueckgewichte (schluessel, bezeichnung, muster, prioritaet, gramm_essbar, anteil_essbar, quelle)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (schluessel) DO UPDATE SET bezeichnung = EXCLUDED.bezeichnung, muster = EXCLUDED.muster,
                prioritaet = EXCLUDED.prioritaet, gramm_essbar = EXCLUDED.gramm_essbar,
                anteil_essbar = EXCLUDED.anteil_essbar, quelle = EXCLUDED.quelle""", z)


def ist_ei(name: str) -> bool:
    return bool(re.search(r"eier\b|\bei\b", str(name or ""), re.I))


def referenz(con, name: str) -> dict | None:
    """Passende Zeile der Referenztabelle (Rang 3) für einen Produktnamen."""
    n = str(name or "")
    if _AUSNAHMEN.search(n):
        return None
    for schluessel, bez, muster, gramm, anteil, quelle in con.execute(
            "SELECT schluessel, bezeichnung, muster, gramm_essbar, anteil_essbar, quelle FROM stueckgewichte "
            "ORDER BY prioritaet, schluessel"):
        if re.search(muster, n, re.I):
            return {"schluessel": schluessel, "bezeichnung": bez, "gramm": float(gramm),
                    "anteil_essbar": float(anteil) if anteil is not None else None, "quelle": quelle}
    return None


def gewichtsklasse(con, name: str) -> dict | None:
    """Ei mit Gewichtsklasse im Namen -> Rang 2 (Packungsangabe)."""
    if not ist_ei(name):
        return None
    m = _KLASSE.search(str(name))
    if not m:
        return None
    klassen = [k for k in m.groups() if k]
    werte = dict(con.execute("SELECT schluessel, gramm_essbar FROM stueckgewichte WHERE schluessel LIKE 'ei_%'").fetchall())
    g = [float(werte["ei_" + k.lower()]) for k in klassen if "ei_" + k.lower() in werte]
    if not g:
        return None
    return {"gramm": round(sum(g) / len(g), 1), "klasse": "/".join(klassen)}


def bestimmen(con, a: dict) -> dict | None:
    """Bestes Stückgewicht für Stückware: {gramm, quelle, rang, detail} oder None."""
    if str(a.get("einheit") or "").lower() not in ("stk", "stück"):
        return None
    name = a.get("name") or ""
    kandidaten = []
    k = gewichtsklasse(con, name)
    if k:
        kandidaten.append({"gramm": k["gramm"], "quelle": "packung", "rang": 2,
                           "detail": f"Gewichtsklasse {k['klasse']} im Namen, essbarer Anteil; {_EIER}"})
    r = referenz(con, name)
    if r:
        kandidaten.append({"gramm": r["gramm"], "quelle": "referenz", "rang": 3, "detail": f"{r['bezeichnung']}: {r['quelle']}"})
    # übergebener Wert zuletzt: bei gleichem Rang gewinnt die belegte Tabelle; „packung“/„referenz“ kommen nur aus dem Code
    g = nw._zahl(a.get("gramm_pro_stk"))
    q = a.get("gramm_quelle") if a.get("gramm_quelle") in ("manuell", "ki") else "ki"
    if g and g > 0:
        kandidaten.append({"gramm": g, "quelle": q, "rang": nw.GRAMM_RANG[q],
                           "detail": a.get("gramm_detail") or ("vom Nutzer gewogen" if q == "manuell" else "KI-Schätzung")})
    return min(kandidaten, key=lambda x: x["rang"]) if kandidaten else None


def aus_gewogen(con, name: str, gewogen: float, mit_schale: bool) -> dict:
    """Vom Nutzer gewogenes Stück -> essbarer Anteil (Rang 1). Mit Schale/Kern nur mit Referenz-Anteil möglich."""
    if not mit_schale:
        return {"gramm": round(gewogen, 1), "detail": f"gewogen {gewogen:g} g ohne Schale/Kern"}
    r = referenz(con, name)
    if not r or not r["anteil_essbar"]:
        raise ValueError("Für dieses Produkt ist kein essbarer Anteil hinterlegt – bitte ohne Schale/Kern wiegen.")
    essbar = round(gewogen * r["anteil_essbar"], 1)
    return {"gramm": essbar, "detail": f"gewogen {gewogen:g} g mit Schale/Kern × {r['anteil_essbar']:.0%} essbar ({r['quelle']})"}


def alle_aktualisieren(con) -> list[dict]:
    """Stückgewichte aller Stückware-Produkte neu bestimmen (bessere Ränge ersetzen schlechtere)."""
    from . import vorrat
    erg = []
    for gid, name, g, gq in con.execute(
            "SELECT grocy_product_id, name, gramm_pro_stk, gramm_quelle FROM vorrat_produkte WHERE einheit = 'stk'").fetchall():
        b = bestimmen(con, {"einheit": "stk", "name": name})
        if not b:
            continue
        s = vorrat.speichern(con, gid, {"gramm_pro_stk": b["gramm"], "gramm_quelle": b["quelle"], "gramm_detail": b["detail"]})
        if s["gramm"] == "gespeichert" and (float(g or 0), gq) != (b["gramm"], b["quelle"]):
            erg.append({"grocy_product_id": gid, "name": name, "vorher": float(g) if g else None, "vorher_quelle": gq,
                        "gramm": b["gramm"], "quelle": b["quelle"]})
    return erg
