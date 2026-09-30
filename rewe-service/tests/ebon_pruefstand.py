"""Prüfstand für echte eBons (PDF in eBon/): dieselbe Kette wie im Workflow „eBon-Import“, aber ohne produktives Grocy.

Eingangsweg: Mail mit PDF-Anhang („PDF-Anhang finden“) -> Text aus PDF (n8n extractFromFile, gecacht in eBon/.text/, erzeugt mit
scripts/ebon_text.sh) -> „Bon vorbereiten“ (MiniMax-Prompt) -> MiniMax -> „Artikel aufbereiten“ -> REWE-Zuordnung (rewe-service, echter Katalog)
-> „REWE-Daten übernehmen“ -> „Produkte zuordnen“ -> Menge bekannt? -> Einbuchen (DRY-RUN: nur protokolliert) -> „Bons zusammenfassen“ -> Nährwerte.
Die n8n-Code-Knoten laufen mit ihrem echten Code (workflows/tests/node_cli.cjs); HTTP/Grocy/Telegram sind ersetzt.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from decimal import Decimal
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
EBON = WURZEL / "eBon"
NODE_CLI = WURZEL / "workflows" / "tests" / "node_cli.cjs"
LUXON = WURZEL / "workflows" / "tests" / "node_modules" / "luxon"
KEYDATEI = Path.home() / ".config" / "vorrat" / "minimax.key"


def _node_bin() -> str:
    """Erstes funktionierende node (PATH, sonst Homebrew-Versionen); Umgebungsvariable NODE_BIN hat Vorrang."""
    import shutil
    kandidaten = [os.environ.get("NODE_BIN"), shutil.which("node"), "/opt/homebrew/opt/node@24/bin/node", "/opt/homebrew/opt/node/bin/node",
                  "/opt/homebrew/opt/node@22/bin/node", "/usr/local/bin/node"]
    for k in kandidaten:
        if k and os.path.exists(k) and subprocess.run([k, "-v"], capture_output=True).returncode == 0:
            return k
    return "node"


NODE = _node_bin()


def luxon_verfuegbar() -> bool:
    return LUXON.is_dir() or bool(os.environ.get("LUXON_PATH"))


def node(datei: str, knoten: str, nodes: dict | None = None, eingabe: list | None = None, jetzt: str = "2026-09-30T13:30:00+02:00") -> list[dict]:
    """Führt einen Code-Knoten eines Workflows mit seinem echten Code aus; Rückgabe: Liste der json-Objekte (bzw. Items mit binary)."""
    env = {**os.environ, "LUXON_PATH": os.environ.get("LUXON_PATH", str(LUXON))}
    p = subprocess.run([NODE, str(NODE_CLI)], input=json.dumps({"datei": datei, "knoten": knoten, "nodes": nodes or {}, "input": eingabe or [], "jetzt": jetzt}),
                       capture_output=True, text=True, env=env, timeout=120)
    if p.returncode:
        raise RuntimeError(f"Knoten {datei}:{knoten} fehlgeschlagen:\n{p.stderr[-1500:]}")
    return [i["json"] for i in json.loads(p.stdout)]


def dumps(o) -> str:
    return json.dumps(o, default=lambda x: float(x) if isinstance(x, Decimal) else str(x), ensure_ascii=False)


def roundtrip(o):
    return json.loads(dumps(o))


# ---------------------------------------------------------------------------------------------------------------- Bons
def bons() -> list[dict]:
    """Alle PDFs in eBon/: {pdf, name, text, datum}. Text bevorzugt aus dem n8n-Cache (eBon/.text), sonst pdftotext (Hinweis im Ergebnis)."""
    from app import bon as bonmod
    out = []
    for pdf in sorted(EBON.glob("*.pdf")):
        cache = EBON / ".text" / (pdf.stem + ".txt")
        if cache.is_file():
            text, quelle = cache.read_text(encoding="utf-8"), "n8n extractFromFile"
        else:
            text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
            quelle = "pdftotext (Ersatz, scripts/ebon_text.sh fehlt)"
        d = bonmod.bon_lesen(text)["datum"]
        out.append({"pdf": pdf, "name": pdf.stem, "text": text, "datum": d.isoformat() if d else None, "textquelle": quelle})
    return out


# -------------------------------------------------------------------------------------------------------------- MiniMax
def minimax_key() -> str | None:
    if os.environ.get("MINIMAX_API_KEY"):
        return os.environ["MINIMAX_API_KEY"].strip()
    return KEYDATEI.read_text().strip() if KEYDATEI.is_file() else None


def minimax(system: str, prompt: str) -> dict:
    """Derselbe Aufruf wie der Workflow-Knoten „MiniMax liest Bon aus“."""
    import httpx
    r = httpx.post("https://api.minimax.io/v1/chat/completions", headers={"Authorization": "Bearer " + (minimax_key() or "")}, timeout=240,
                   json={"model": "MiniMax-M3", "thinking": {"type": "disabled"}, "temperature": 0.1, "max_tokens": 16000,
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()


def ki_antwort_fehlerhaft(bon_zeilen: list[dict], datum: str) -> dict:
    """Worst-Case-KI: liest den Preis als Menge (445 g bei 4,45 €), nimmt Wasser/Pfand als Artikel mit auf, erfindet Packungsgrößen."""
    artikel = []
    for z in bon_zeilen:
        if z["betrag"] <= 0:
            continue
        ziffern = int(str(z["betrag"]).replace(".", ""))
        name = re.sub(r"[.\d]+", " ", z["bon_text"]).strip().title()
        artikel.append({"name": name, "bon_text": z["bon_text"], "off_suche": name, "frischware": False, "kategorie": "Sonstiges",
                        "menge": ziffern, "einheit": "g", "packungen": z.get("anzahl", 1), "menge_geschaetzt": False, "gramm_pro_stk": None,
                        "naehrwerte_100g": {"kcal": 150, "protein": 5, "fett": 5, "kh": 20}, "lagerort": "Kühlschrank", "haltbarkeit_tage": 7})
    summe = float(sum(z["betrag"] for z in bon_zeilen))
    return {"choices": [{"message": {"content": json.dumps({"kaufdatum": datum, "summe": summe, "artikel": artikel}, ensure_ascii=False)}}]}


# ------------------------------------------------------------------------------------------------------ Dry-Run-Grocy
class GrocyDry:
    """Ersetzt Grocy: legt Produkte an und protokolliert Buchungen, ohne irgendetwas zu schreiben."""

    def __init__(self, produkte: list[dict] | None = None):
        self.produkte = list(produkte or [])
        self.naechste_id = 100
        self.angelegt: list[dict] = []
        self.buchungen: list[dict] = []
        self.bestand: dict[int, float] = {}
        self.einheiten = [{"id": 4, "name": "Gramm"}, {"id": 5, "name": "Stück"}, {"id": 6, "name": "Milliliter"}]
        self.lagerorte = [{"id": 3, "name": "Kühlschrank"}, {"id": 4, "name": "Tiefkühler"}, {"id": 5, "name": "Vorratsschrank"}]

    def anlegen(self, a: dict) -> int:
        pid = self.naechste_id
        self.naechste_id += 1
        self.produkte.append({"id": pid, "name": a["name"], "qu_id_stock": a["qu_id"], "location_id": a["location_id"], "calories": 0})
        self.angelegt.append({"product_id": pid, "name": a["name"], "qu_id": a["qu_id"], "calories": a.get("kcal_pro_einheit", 0)})
        return pid

    def einbuchen(self, a: dict) -> None:
        self.buchungen.append({"product_id": a["product_id"], "name": a["name"], "bon_text": a.get("bon_text"), "menge": a["menge"],
                               "einheit": a["einheit"], "mhd": a.get("mhd"), "quelle": a.get("menge_quelle")})
        self.bestand[a["product_id"]] = self.bestand.get(a["product_id"], 0) + float(a["menge"])


# ------------------------------------------------------------------------------------------------------------- Pipeline
def lauf(con, b: dict, ki_antwort: dict, grocy: GrocyDry, chat_id: str = "42") -> dict:
    """Ein kompletter Import-Lauf für einen Bon. Rückgabe: alle Zwischenergebnisse für die Prüfungen."""
    from app import bon as bonmod, rueckfragen
    E = "01-ebon-import.json"
    text, datum = b["text"], b["datum"]
    mail = {"__item": True, "json": {"messageId": f"test-{datum}", "subject": "Dein eBon", "date": f"{datum}T13:03:00+02:00"},
            "binary": {"attachment_0": {"mimeType": "application/pdf", "fileName": b["pdf"].name}}}
    pdf = node(E, "PDF-Anhang finden", eingabe=[mail])
    prep = node(E, "Bon vorbereiten", {"PDF-Anhang finden": pdf}, [{"text": text}])
    artikel = node(E, "Artikel aufbereiten", {"Bon vorbereiten": prep}, [ki_antwort])
    anfrage = node(E, "REWE-Anfrage bauen", {"Artikel aufbereiten": artikel, "PDF-Anhang finden": pdf, "Text aus PDF lesen": [{"text": text}]})
    body = anfrage[0]["body"]
    antwort = roundtrip(bonmod.zuordnen(con, body["text"], body["bon_id"], body["artikel_texte"], body["kaufdatum"]))
    uebernommen = node(E, "REWE-Daten übernehmen", {"Artikel aufbereiten": artikel, "REWE-Anfrage bauen": anfrage}, [antwort])
    verkn = [{"grocy_product_id": p["id"], "rewe_product_id": p.get("rewe_product_id")} for p in grocy.produkte if p.get("rewe_product_id")]
    zugeordnet = node(E, "Produkte zuordnen", {
        "REWE-Daten übernehmen": uebernommen, "Grocy-Produkte laden": grocy.produkte, "Grocy-Einheiten laden": grocy.einheiten,
        "Grocy-Lagerorte laden": grocy.lagerorte, "Vorrat-Verknüpfungen laden": verkn})
    alle = []
    for a in zugeordnet:
        if a.get("product_id"):
            alle.append(a)
            continue
        neu = node(E, "Neues Produkt vorbereiten", {}, [a])[0]
        pid = grocy.anlegen(neu)
        alle.append(node(E, "Neue Produkt-ID übernehmen", {"Neues Produkt vorbereiten": [neu]}, [{"created_object_id": pid}])[0])
    # Weiche „Menge bekannt?“ (gleiche Bedingung wie im Workflow) und Dry-Run-Buchung
    gebucht, offen = [], []
    for a in alle:
        m = a.get("menge")
        (gebucht if (m is not None and float(m) > 0) else offen).append(a)
    for a in gebucht:
        grocy.einbuchen(a)
    profil = [{"grocy_url": "http://grocy.dry", "chat_id": chat_id}]
    zusammenfassung = node(E, "Bons zusammenfassen", {"Alle Artikel": alle})
    sammeln = node(E, "Rückfragen sammeln", {"Alle Artikel": alle, "Profil laden": profil})
    gemerkt = [rueckfragen.anlegen(con, s["body"]["chat_id"], s["body"]["art"], s["body"]["bon_zeile_id"], s["body"]["bon_text"],
                                   s["body"]["kandidaten"], s["body"]["payload"]) for s in sammeln]
    bauen = node(E, "Rückfragen bauen", {"Alle Artikel": alle, "Profil laden": profil})
    return {"pdf": pdf, "prompt": prep[0], "artikel": artikel, "anfrage": body, "antwort": antwort, "uebernommen": uebernommen, "alle": alle,
            "gebucht": gebucht, "offen": offen, "zusammenfassung": zusammenfassung, "rueckfragen_sammeln": [s["body"] for s in sammeln],
            "rueckfrage_ids": gemerkt, "rueckfragen_bauen": bauen}
