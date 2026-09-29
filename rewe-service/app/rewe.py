"""Zugriff auf die REWE-App-API: rewerse für Suche/Listen/Kategorien/Angebote, eigener Abruf für Produktdetails.

Viele Märkte (auch 1940430) bieten keine Abholung an. rewerse sendet bei Produktdetails und Kategorien fest
den Service „PICKUP“, den die API für solche Märkte mit „Invalid market selection“ ablehnt. Deshalb:
- Service-Typ wird aus den Marktdetails ermittelt (hasPickup), überschreibbar per REWE_SERVICE_TYPE,
- Listen/Suche/Kategorien laufen über rewerse mit diesem Service-Typ,
- Produktdetails laufen über eine eigene Anfrage (Nachbau aus rewerse pkg/products.go, pkg/util.go),
  die zugleich die ungefilterte Antwort liefert.
"""

from __future__ import annotations

import json
import os
import random
import ssl
import threading
import time
import uuid
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
HOST = "https://mobile-clients-api.rewe.de"

_lock = threading.Lock()
_client = None
_http: httpx.Client | None = None
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


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        if not zertifikate_vorhanden():
            raise NichtBereit("Zertifikate fehlen")
        ctx = ssl.create_default_context()
        ctx.load_cert_chain(CERT_PATH, KEY_PATH)
        _http = httpx.Client(verify=ctx, timeout=30, base_url=HOST)
    return _http


def _produkt_roh(product_id: str) -> dict:
    st, mid = service_type(), markt_id()
    headers = {
        "x-instana-android": str(uuid.uuid4()),
        "user-agent": "REWE-Mobile-Client/5.17.2.53406 Android/14 Phone/Google_Pixel_8",
        "rdfa": str(uuid.uuid4()),
        "rdtga": "payment-enable-google-pay,productlist-citrusad",
        "correlation-id": str(uuid.uuid4()),
        "rd-service-types": st, "x-rd-service-types": st,
        "rd-customer-zip": ZIP, "x-rd-customer-zip": ZIP,
        "rd-market-id": mid, "x-rd-market-id": mid,
        "rd-postcode": ZIP, "rd-is-lsfk": "false",
    }
    r = _http_client().get(f"/api/products/{product_id}", headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.text.lstrip().startswith("<!DOCTYPE html>"):
        raise RuntimeError("Antwort ist HTML (Cloudflare)")
    return r.json()


def _produkt_detail(product_id: str) -> dict:
    produkte = ((_produkt_roh(product_id).get("data") or {}).get("product")) or []
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


def openfoodfacts(ean: str) -> dict | None:
    """Nährwerte per Barcode (nur Fallback, wenn REWE keine nutritionFacts liefert)."""
    r = httpx.get(f"https://world.openfoodfacts.org/api/v2/product/{ean}.json",
                  params={"fields": "product_name,brands,quantity,nutriments"},
                  headers={"User-Agent": "VorratsAssistent-rewe-service/1.0"}, timeout=20)
    if r.status_code != 200:
        return None
    daten = r.json()
    if daten.get("status") != 1:
        return None
    n = (daten.get("product") or {}).get("nutriments") or {}
    werte = {"kcal": n.get("energy-kcal_100g"), "protein": n.get("proteins_100g"),
             "kh": n.get("carbohydrates_100g"), "fett": n.get("fat_100g")}
    werte = {k: round(float(v), 1) for k, v in werte.items() if isinstance(v, (int, float))}
    return werte or None
