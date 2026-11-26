"""Zugriff auf die REWE-App-API, ausschließlich über die Bibliothek rewerse.

Die Schnittstelle selbst hat das Projekt rewerse-engineering untersucht und dokumentiert
(https://github.com/ByteSizedMarius/rewerse-engineering). Dieses Modul baut darauf auf und
sendet keine eigenen Anfragen an REWE.

Viele Märkte bieten keine Abholung an. Der Service-Typ wird deshalb aus den Marktdetails ermittelt
(hasPickup), überschreibbar per REWE_SERVICE_TYPE, und an Listen, Suche und Kategorien übergeben.
Produktdetails fragt rewerse mit dem Service „PICKUP“ an: REWE_MARKET_ID sollte daher ein Markt
mit Abholservice sein (dort gibt es ohnehin Ladenpreise und das volle Sortiment).
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path

import httpx

CERT_PATH = os.environ.get("REWE_CERT_PATH", "/certs/rewe.pem")
KEY_PATH = os.environ.get("REWE_KEY_PATH", "/certs/rewe.key")
# Sortiment/Preise: am besten ein Markt mit Abholservice (Ladenpreise, volles Sortiment);
# der Lieferservice hat eigene Preise und ein kleineres Sortiment.
MARKET_ID = os.environ.get("REWE_MARKET_ID", "").strip()
# Angebote gelten pro Markt: hier der Markt, in dem tatsächlich eingekauft wird
ANGEBOTE_MARKET_ID = os.environ.get("REWE_ANGEBOTE_MARKET_ID", "").strip() or MARKET_ID
SERVICE_TYPE = os.environ.get("REWE_SERVICE_TYPE", "").strip().upper()  # leer = automatisch
# Für DELIVERY akzeptiert die API die rewerse-Standard-PLZ; die Marktpreise hängen an der Markt-ID
ZIP = os.environ.get("REWE_ZIP", "67065").strip()
PAUSE_MIN = float(os.environ.get("REWE_PAUSE_MIN", "2"))
PAUSE_MAX = float(os.environ.get("REWE_PAUSE_MAX", "3"))

_lock = threading.Lock()
_client = None
_service_type: str | None = None
_letzter_aufruf = 0.0


class NichtBereit(RuntimeError):
    """Zertifikate oder Markt-ID fehlen."""


def zertifikate_vorhanden() -> bool:
    return Path(CERT_PATH).is_file() and Path(KEY_PATH).is_file()


def client():
    global _client
    if _client is None:
        if not zertifikate_vorhanden():
            raise NichtBereit(f"Zertifikate fehlen ({CERT_PATH}, {KEY_PATH}), siehe README")
        from rewerse import Rewerse  # erst hier laden: die Go-Bibliothek braucht die Zertifikate
        _client = Rewerse(cert=CERT_PATH, key=KEY_PATH)
    return _client


def markt_id() -> str:
    if not MARKET_ID:
        raise NichtBereit("REWE_MARKET_ID ist nicht gesetzt (Markt über GET /markets/search?q=PLZ ermitteln)")
    return MARKET_ID


def service_type() -> str:
    """PICKUP, wenn der Markt Abholung anbietet, sonst DELIVERY."""
    global _service_type
    if SERVICE_TYPE:
        return SERVICE_TYPE
    if _service_type is None:
        details = client().get_market_details(markt_id())
        markt = details.get("Market", details) if isinstance(details, dict) else {}
        _service_type = "PICKUP" if (markt.get("serviceFlags") or {}).get("hasPickup") else "DELIVERY"
    return _service_type


def _drosseln() -> None:
    global _letzter_aufruf
    warten = random.uniform(PAUSE_MIN, PAUSE_MAX) - (time.monotonic() - _letzter_aufruf)
    if warten > 0:
        time.sleep(warten)


def aufruf(methode: str, *args, drosseln: bool = True, **kwargs):
    """Führt eine Funktion dieses Moduls serialisiert aus; beim Crawlen mit 2-3 s Abstand zwischen Requests."""
    global _letzter_aufruf
    with _lock:
        if drosseln:
            _drosseln()
        try:
            return _FUNKTIONEN[methode](*args, **kwargs)
        finally:
            _letzter_aufruf = time.monotonic()


# --- einzelne API-Funktionen (nur über aufruf() benutzen) ---------------------------------------

def _produktliste(funktion: str, ziel: str, page: int, objects_per_page: int) -> dict:
    from rewerse._ffi import call
    opts = {"Page": page, "ObjectsPerPage": objects_per_page, "Filters": [], "ServiceType": service_type()}
    return call(funktion, markt_id(), ziel, json.dumps(opts))


def _produkte_suchen(suche: str, page: int = 1, objects_per_page: int = 30) -> dict:
    return _produktliste("GetProducts", suche, page, objects_per_page)


def _kategorie_produkte(slug: str, page: int = 1, objects_per_page: int = 60) -> dict:
    return _produktliste("GetCategoryProducts", slug, page, objects_per_page)


def _shop_uebersicht() -> dict:
    st = service_type()
    if st == "PICKUP":
        return client().get_shop_overview(markt_id())
    return client().get_shop_overview(markt_id(), service_type=st, zip_code=ZIP)


def _angebote() -> dict:
    if not ANGEBOTE_MARKET_ID:
        raise NichtBereit("REWE_ANGEBOTE_MARKET_ID bzw. REWE_MARKET_ID ist nicht gesetzt")
    return client().get_discounts(ANGEBOTE_MARKET_ID)


def _maerkte_suchen(suche: str) -> list:
    return client().market_search(suche)


def _produkt_roh(product_id: str) -> dict:
    """Ungefilterte Produktdetails über rewerse (GetProductByID), in der Form {"data": {...}}."""
    return {"data": client().get_product_by_id(markt_id(), product_id) or {}}


def _produkt_detail(product_id: str) -> dict:
    produkte = (_produkt_roh(product_id).get("data") or {}).get("product") or []
    if isinstance(produkte, dict):
        produkte = [produkte]
    if not produkte:
        raise RuntimeError(f"Produkt {product_id} nicht gefunden")
    return produkte[0]


_FUNKTIONEN = {
    "produkte_suchen": _produkte_suchen,
    "kategorie_produkte": _kategorie_produkte,
    "shop_uebersicht": _shop_uebersicht,
    "angebote": _angebote,
    "maerkte_suchen": _maerkte_suchen,
    "produkt_roh": _produkt_roh,
    "produkt_detail": _produkt_detail,
}


class OffLimit(RuntimeError):
    """Open Food Facts lehnt wegen Anfrage-Limit ab (HTTP 429/503) – später erneut versuchen."""


OFF_HEADERS = {"User-Agent": "VorratsAssistent-rewe-service/1.0 (privat)"}
_OFF_FELDER = {"kcal": "energy-kcal_100g", "protein": "proteins_100g", "kh": "carbohydrates_100g", "fett": "fat_100g",
               "zucker": "sugars_100g", "ballaststoffe": "fiber_100g", "salz": "salt_100g"}


def off_werte(nutriments: dict | None) -> dict | None:
    n = nutriments or {}
    werte = {k: n.get(f) for k, f in _OFF_FELDER.items()}
    werte = {k: round(float(v), 2 if k == "salz" else 1) for k, v in werte.items() if isinstance(v, (int, float))}
    return werte or None


def _off_get(url: str, params: dict) -> httpx.Response:
    try:
        r = httpx.get(url, params=params, headers=OFF_HEADERS, timeout=20)
    except httpx.TimeoutException as e:
        raise OffLimit(f"Zeitüberschreitung: {e}") from e
    if r.status_code in (429, 503):
        raise OffLimit(f"HTTP {r.status_code}")
    return r


def openfoodfacts(ean: str) -> dict | None:
    """Nährwerte pro 100 g per Barcode. OffLimit bei Anfrage-Limit."""
    r = _off_get(f"https://world.openfoodfacts.org/api/v2/product/{ean}.json",
                 {"fields": "product_name,brands,quantity,nutriments"})
    if r.status_code != 200:
        return None
    daten = r.json()
    if daten.get("status") != 1:
        return None
    return off_werte((daten.get("product") or {}).get("nutriments"))


def openfoodfacts_suche(begriff: str, seiten_groesse: int = 10) -> list[dict]:
    """Namenssuche über die Such-API search.openfoodfacts.org (die alte cgi/search.pl antwortet meist mit 503).

    OffLimit bei Anfrage-Limit oder Überlastung. brands kommt als Liste.
    """
    r = _off_get("https://search.openfoodfacts.org/search",
                 {"q": begriff, "page_size": seiten_groesse, "fields": "code,product_name,product_name_de,brands,nutriments"})
    if r.status_code != 200:
        return []
    treffer = r.json().get("hits") or []
    for t in treffer:
        t["product_name"] = t.get("product_name_de") or t.get("product_name") or ""
    return treffer
