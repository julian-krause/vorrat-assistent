"""Umwandlung der REWE-Rohdaten: Packungsgröße, Grundpreis, Nährwerte, Barcode."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

_EINHEIT = {
    "kg": ("g", 1000), "g": ("g", 1), "gr": ("g", 1),
    "l": ("ml", 1000), "ltr": ("ml", 1000), "ml": ("ml", 1), "cl": ("ml", 10),
    "stück": ("Stück", 1), "stk": ("Stück", 1), "st": ("Stück", 1), "er": ("Stück", 1),
}
_ZAHL = r"(\d+(?:[.,]\d+)?)"
_EINH = r"(kg|gr|g|ltr|l|ml|cl|stück|stk|st|er)\b\.?"
_MULTI = re.compile(rf"^(\d+)\s*[x×]\s*{_ZAHL}\s*{_EINH}")
_EINFACH = re.compile(rf"^{_ZAHL}\s*{_EINH}")


def _zahl(s: str) -> float:
    return float(s.replace(",", "."))


def parse_groesse(grammage: str | None, gewicht_pro_stueck: float | None = None) -> tuple[float | None, str | None]:
    """„500g (1 kg = 3,98 €)“ -> (500, "g"); „6 x 1,5 l“ -> (9000, "ml"); „10 Stück“ -> (10, "Stück").

    Liefert (None, None), wenn nichts erkannt wird. Als Rückfall dient packaging.weightPerPiece.
    """
    text = (grammage or "").split("(")[0].strip().lower()
    m = _MULTI.match(text)
    if m:
        einheit, faktor = _EINHEIT[m.group(3)]
        return round(int(m.group(1)) * _zahl(m.group(2)) * faktor, 3), einheit
    m = _EINFACH.match(text)
    if m:
        einheit, faktor = _EINHEIT[m.group(2)]
        return round(_zahl(m.group(1)) * faktor, 3), einheit
    if gewicht_pro_stueck and gewicht_pro_stueck > 0:
        return float(gewicht_pro_stueck), "g"
    return None, None


def grundpreis(preis: float | None, groesse: float | None, einheit: str | None) -> float | None:
    """Preis pro kg bzw. l (nur für g/ml)."""
    if not preis or not groesse or einheit not in ("g", "ml"):
        return None
    # kaufmännisch runden wie REWE (2,19 € / 400 g = 5,475 -> 5,48 €/kg)
    wert = Decimal(str(preis)) * 1000 / Decimal(str(groesse))
    return float(wert.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _bezug_100(fact: dict) -> float:
    """Faktor auf 100 g/ml, falls die Angabe nicht pro 100 ist."""
    ss = fact.get("servingSize") or {}
    wert = ss.get("value")
    if isinstance(wert, (int, float)) and wert > 0 and str(ss.get("uomShortText", "")).lower() in ("g", "ml"):
        return 100.0 / wert
    return 1.0


def parse_naehrwerte(facts: list | None) -> dict | None:
    """nutritionFacts -> {kcal, protein, kh, fett} pro 100 g/ml (unzubereitet bevorzugt)."""
    if not facts:
        return None
    fact = next((f for f in facts if str(f.get("preparationState", "")).lower().startswith("unzubereitet")), facts[0])
    faktor = _bezug_100(fact)
    werte: dict[str, float] = {}
    kj = None
    for n in fact.get("nutrientInformation") or []:
        typ = str(n.get("nutrientType", "")).strip().lower()
        menge = n.get("quantityContained") or {}
        wert = menge.get("value")
        if not isinstance(wert, (int, float)):
            continue
        einheit = str(menge.get("uomShortText", "")).lower()
        if typ.startswith("energie") or typ.startswith("brennwert"):
            if einheit == "kcal":
                werte["kcal"] = wert * faktor
            elif einheit == "kj":
                kj = wert * faktor
        elif typ in ("eiweiß", "eiweiss", "protein"):
            werte["protein"] = wert * faktor
        elif typ == "kohlenhydrate":
            werte["kh"] = wert * faktor
        elif typ == "fett":
            werte["fett"] = wert * faktor
    if "kcal" not in werte and kj is not None:
        werte["kcal"] = kj / 4.184
    if not werte:
        return None
    return {k: round(v, 1) for k, v in werte.items()}


def gtin_gueltig(code: str) -> bool:
    """GS1-Prüfziffer für EAN-8/UPC-A/EAN-13/GTIN-14."""
    if not re.fullmatch(r"\d{8}|\d{12,14}", code or ""):
        return False
    ziffern = [int(c) for c in code]
    summe = sum(z * (3 if i % 2 == 0 else 1) for i, z in enumerate(reversed(ziffern[:-1])))
    return (10 - summe % 10) % 10 == ziffern[-1]


def ean_aus_article_id(article_id: str | None) -> str | None:
    """Im REWE-Onlineshop ist die articleId meist die GTIN/EAN des Produkts (sonst alphanumerisch, z.B. „4H27HYFW“)."""
    code = str(article_id or "").strip()
    return code if gtin_gueltig(code) else None


_EAN_SCHLUESSEL = re.compile(r"^(ean|ean13|gtin|gtin\d+|barcode)$", re.I)


def finde_ean(obj) -> str | None:
    """Sucht rekursiv nach einem EAN/GTIN-Feld mit 8-14 Ziffern."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _EAN_SCHLUESSEL.match(str(k)) and re.fullmatch(r"\d{8,14}", str(v or "")):
                return str(v)
        for v in obj.values():
            gefunden = finde_ean(v)
            if gefunden:
                return gefunden
    elif isinstance(obj, list):
        for v in obj:
            gefunden = finde_ean(v)
            if gefunden:
                return gefunden
    return None
