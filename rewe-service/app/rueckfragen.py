"""Offene Rückfragen des Bots (Produktwahl bei unsicheren Bonzeilen, „Menge offen“).

Solange eine Rückfrage offen ist, wird Freitext des Nutzers zuerst als Antwort darauf ausgewertet – erst wenn er nicht
passt (oder „abbrechen“ lautet), geht die Nachricht an den Agenten. Der Dienst entscheidet nur, n8n führt aus (Grocy, Telegram).
"""

from __future__ import annotations

import re
import time

from psycopg.types.json import Jsonb

from .bon import normalisieren

_ABBRUCH = re.compile(r"^\s*(abbrechen|abbruch|stopp?|vergiss (es|das)|egal|lass (es|das)|nein danke)\s*[.!]*\s*$", re.I)
_MENGE = re.compile(r"(?<![\w,.])(\d+(?:[.,]\d+)?)\s*(kg|g|gramm|ml|l|liter|stk|stück|stueck|st)?(?![\w])", re.I)
_FUELLWOERTER = {"ca", "circa", "etwa", "ungefahr", "waren", "war", "es", "das", "sind", "ist", "insgesamt", "genau", "nur", "also",
                 "so", "von", "vom", "die", "der", "den", "dem", "ein", "eine", "mal", "x", "je", "pro", "gesamt", "zusammen", "menge",
                 "bio", "natur", "frisch", "rewe", "ja", "klasse", "stueck", "stk"}
_EINHEIT = {"kg": ("g", 1000), "g": ("g", 1), "gramm": ("g", 1), "l": ("ml", 1000), "liter": ("ml", 1000), "ml": ("ml", 1),
            "stk": ("stk", 1), "stuck": ("stk", 1), "stueck": ("stk", 1), "st": ("stk", 1)}


def anlegen(con, chat_id: str, art: str, bon_zeile_id: int | None = None, bon_text: str | None = None,
            kandidaten: list | None = None, payload: dict | None = None, stunden: int = 48) -> int:
    """Neue Rückfrage; eine ältere offene Rückfrage zur selben Bonzeile und Art wird ersetzt."""
    if bon_zeile_id is not None:
        con.execute("UPDATE offene_rueckfragen SET status = 'abgebrochen' WHERE chat_id = %s AND art = %s AND bon_zeile_id = %s AND status = 'offen'",
                    (str(chat_id), art, bon_zeile_id))
    return con.execute("""INSERT INTO offene_rueckfragen (chat_id, art, bon_zeile_id, bon_text, kandidaten, payload, laeuft_ab_at)
                          VALUES (%s, %s, %s, %s, %s, %s, now() + make_interval(hours => %s)) RETURNING id""",
                       (str(chat_id), art, bon_zeile_id, bon_text, Jsonb(kandidaten or []), Jsonb(payload or {}), stunden)).fetchone()[0]


def offene(con, chat_id: str) -> list[dict]:
    con.execute("UPDATE offene_rueckfragen SET status = 'abgelaufen' WHERE status = 'offen' AND laeuft_ab_at < now()")
    zeilen = con.execute("""SELECT id, art, bon_zeile_id, bon_text, kandidaten, payload FROM offene_rueckfragen
                            WHERE chat_id = %s AND status = 'offen' ORDER BY id""", (str(chat_id),)).fetchall()
    return [dict(zip(("id", "art", "bon_zeile_id", "bon_text", "kandidaten", "payload"), z)) for z in zeilen]


def abschliessen(con, rueckfrage_id: int, status: str = "beantwortet") -> None:
    con.execute("UPDATE offene_rueckfragen SET status = %s WHERE id = %s", (status, rueckfrage_id))


def parse_menge(text: str) -> tuple[float, str | None, str] | None:
    """„ca. 500 g Kefir“ -> (500.0, 'g', 'kefir'); „2 Stück“ -> (2, 'stk', ''); ohne Zahl -> None. Rest = übrige Wörter."""
    treffer = list(_MENGE.finditer(text or ""))
    if len(treffer) != 1:
        return None
    m = treffer[0]
    zahl = float(m.group(1).replace(",", "."))
    einheit_roh = normalisieren(m.group(2) or "")
    einheit, faktor = _EINHEIT.get(einheit_roh, (None, 1))
    rest = (text[:m.start()] + " " + text[m.end():])
    return round(zahl * faktor, 3), einheit, normalisieren(rest)


def _in_einheit(menge: float, einheit: str | None, ziel: str | None, gramm_pro_stk: float | None) -> float | None:
    """Antwort in die Lagereinheit des Grocy-Produkts umrechnen; None = geht nicht ohne Rückfrage."""
    if einheit is None or ziel is None or einheit == ziel:
        return menge
    if einheit == "stk" and ziel == "g" and gramm_pro_stk:
        return round(menge * gramm_pro_stk, 2)
    if einheit == "g" and ziel == "stk" and gramm_pro_stk:
        return max(1.0, round(menge / gramm_pro_stk))
    if {einheit, ziel} == {"g", "ml"}:      # Dichte ≈ 1
        return menge
    return None


def _woerter(text: str) -> set[str]:
    return {w for w in normalisieren(text).split() if len(w) >= 3 and w not in _FUELLWOERTER}


def _passende(rueckfragen: list[dict], rest: str) -> list[dict]:
    """Rückfragen, zu denen die übrigen Wörter der Antwort am besten passen (Bontext bzw. Produktname); bei Gleichstand alle davon."""
    w = _woerter(rest)
    if not w:
        return rueckfragen
    wertung = []
    for r in rueckfragen:
        ziel = _woerter(f"{r['bon_text'] or ''} {(r['payload'] or {}).get('name') or ''}")
        for k in r["kandidaten"] or []:
            ziel |= _woerter(k.get("name") or "")
        # Teilwörter zählen (Kefir ↔ Bio-Kefir, Kartoffel ↔ Kartoffeln)
        wertung.append((sum(1 for a in w if any(a in b or b in a for b in ziel)), r))
    beste = max((x for x, _ in wertung), default=0)
    return [r for x, r in wertung if x == beste] if beste else []


def auswerten(con, chat_id: str, text: str) -> dict:
    """Freitext als Antwort auf eine offene Rückfrage auswerten. treffer=False -> Nachricht gehört dem Agenten."""
    offen = offene(con, chat_id)
    if not offen:
        return {"treffer": False}
    if _ABBRUCH.match(text or ""):
        for r in offen:
            abschliessen(con, r["id"], "abgebrochen")
        return {"treffer": True, "aktion": "abbrechen", "anzahl": len(offen),
                "text": f"👌 Okay, {len(offen)} offene Rückfrage{'n' if len(offen) != 1 else ''} verworfen."}
    produkt_fragen = [r for r in offen if r["art"] == "produkt"]
    if produkt_fragen and (re.fullmatch(r"\s*(nr\.?|nummer)?\s*\d\s*[.)]?\s*", text or "", re.I) or normalisieren(text) in _ORDINAL
                           or normalisieren(text) in _KEINS):
        return _produkt_antwort(con, produkt_fragen, text)       # „2“ ist die Auswahl, keine Mengenangabe
    parsed = parse_menge(text)
    if parsed is None:
        return _produkt_antwort(con, [r for r in offen if r["art"] == "produkt"], text)
    menge, einheit, rest = parsed
    if len(_woerter(rest)) > 4:         # langer Satz mit Zahl: eher eine Frage an den Agenten
        return {"treffer": False}
    kandidaten = _passende(offen, rest)
    if not kandidaten and len(produkt_fragen) == 1 and _woerter(rest):
        # nennt die Antwort ein anderes Produkt als den Kassentext („Speisekartoffeln 1000g“ zu „DIE FEINEN KART.“)?
        p1 = produkt_fragen[0]["payload"] or {}
        wahl = _produkt_und_menge(con, produkt_fragen[0], rest, _in_einheit(menge, einheit, p1.get("einheit"), p1.get("gramm_pro_stk")) or menge,
                                  p1.get("einheit") or einheit)
        if wahl:
            return wahl
    if not kandidaten:
        return {"treffer": False}
    if len(kandidaten) > 1:
        namen = ", ".join(f"„{r['bon_text']}“" for r in kandidaten)
        return {"treffer": True, "aktion": "nachfragen", "text": f"Für welchen Artikel meinst du {menge:g} {einheit or ''}? Offen: {namen}. "
                                                                   "Schreib z. B. „Kefir 500 g“."}
    r = kandidaten[0]
    p = r["payload"] or {}
    ziel_einheit = p.get("einheit")
    umgerechnet = _in_einheit(menge, einheit, ziel_einheit, p.get("gramm_pro_stk"))
    einheit_aendern = False
    if umgerechnet is None and p.get("neu") and einheit:
        # neu angelegtes Produkt ohne Bestand: die Einheit des Nutzers gilt, die Lagereinheit in Grocy wird angepasst
        umgerechnet, ziel_einheit, einheit_aendern = menge, einheit, True
    if umgerechnet is None:
        return {"treffer": True, "aktion": "nachfragen", "rueckfrage_id": r["id"],
                "text": f"„{r['bon_text']}“ führe ich in {ziel_einheit}. Gib es bitte in {ziel_einheit} an (z. B. {'500 g' if ziel_einheit == 'g' else '500 ml' if ziel_einheit == 'ml' else '2 Stück'})."}
    if r["art"] == "menge":
        abschliessen(con, r["id"])
        return {"treffer": True, "aktion": "menge_buchen", "rueckfrage_id": r["id"], "bon_zeile_id": r["bon_zeile_id"],
                "bon_text": r["bon_text"], "menge": umgerechnet, "einheit": ziel_einheit or einheit, "payload": p, "einheit_aendern": einheit_aendern}
    # Produktwahl offen: nennt die Antwort auch ein Produkt („Speisekartoffeln 1000g“), wird es gewählt und die Menge gleich mitgenommen
    if _woerter(rest):
        wahl = _produkt_und_menge(con, r, rest, umgerechnet, ziel_einheit or einheit)
        if wahl:
            return wahl
    # sonst: die gebuchte Menge dieser Bonzeile wird ERSETZT (nicht addiert)
    if p.get("unbucht"):
        return {"treffer": True, "aktion": "nachfragen", "rueckfrage_id": r["id"],
                "text": f"Für „{r['bon_text']}“ ist noch kein Produkt gewählt – tippe einen Button oder schreib mir den Produktnamen, dann buche ich es ein."}
    abschliessen(con, r["id"])
    return {"treffer": True, "aktion": "menge_ersetzen", "rueckfrage_id": r["id"], "bon_zeile_id": r["bon_zeile_id"],
            "bon_text": r["bon_text"], "menge": umgerechnet, "einheit": ziel_einheit or einheit, "payload": p}


_KEINS = {"keins", "keines", "nichts davon", "keins davon", "keiner", "nix"}
_ORDINAL = {"1": 0, "erste": 0, "ersten": 0, "erstes": 0, "eins": 0, "2": 1, "zweite": 1, "zweiten": 1, "zwei": 1, "3": 2, "dritte": 2, "dritten": 2, "drei": 2}


def kandidaten_text(bon_text: str, kandidaten: list[dict]) -> str:
    zeilen = [f"{i}) {k.get('anzeige') or k.get('name')}" for i, k in enumerate(kandidaten, 1)]
    return f"🔍 Für „{bon_text}“ habe ich gefunden:\n" + "\n".join(zeilen) + "\nAntworte mit 1" + (f"–{len(kandidaten)}" if len(kandidaten) > 1 else "") + \
        ", „keins“ oder einem anderen Produktnamen."


def _produkt_antwort(con, produkt_fragen: list[dict], text_: str) -> dict:
    """Freitext zu einer offenen Produktwahl: Nummer/„keins“ wählt einen Kandidaten, ein kurzer Produktname durchsucht den Katalog.
    Was nicht eindeutig passt (Frage, langer Satz, schwacher Treffer), gehört dem Agenten."""
    if not produkt_fragen:
        return {"treffer": False}
    from . import bon, text as textmodul
    # „1“/„keins“ bezieht sich auf die Rückfrage, für die zuletzt Vorschläge gezeigt wurden, sonst auf die jüngste
    r = max(produkt_fragen, key=lambda x: ((x["payload"] or {}).get("zuletzt", 0), x["id"]))
    t = normalisieren(text_)
    woerter = t.split()
    if not woerter or "?" in (text_ or ""):
        return {"treffer": False}
    if t in _ORDINAL or (len(woerter) == 2 and woerter[0] in ("nummer", "nr") and woerter[1] in _ORDINAL):
        i = _ORDINAL[woerter[-1]]
        if i < len(r["kandidaten"]):
            k = r["kandidaten"][i]
            wunsch = (r["payload"] or {}).get("menge_wunsch") or {}
            return {"treffer": True, "aktion": "produkt_waehlen", "rueckfrage_id": r["id"], "bon_zeile_id": r["bon_zeile_id"],
                    "rewe_product_id": k["rewe_product_id"], "menge": wunsch.get("menge"), "einheit": wunsch.get("einheit"), "payload": r["payload"]}
        return {"treffer": True, "aktion": "nachfragen", "text": f"So viele Vorschläge gibt es nicht (1–{len(r['kandidaten'])})."}
    if re.fullmatch(r"(nr |nummer )?\d", t):
        return {"treffer": True, "aktion": "nachfragen", "text": f"So viele Vorschläge gibt es nicht (1–{max(1, len(r['kandidaten']))})."}
    if t in _KEINS:
        return {"treffer": True, "aktion": "produkt_waehlen", "rueckfrage_id": r["id"], "bon_zeile_id": r["bon_zeile_id"],
                "rewe_product_id": None, "payload": r["payload"]}
    if len(woerter) > 5:
        return {"treffer": False}
    treffer = textmodul.suche(con, text_, 0.5, 6)
    if not treffer or treffer[0]["score"] < 0.6:
        return {"treffer": bool((r["payload"] or {}).get("suche")), "aktion": "nachfragen",
                "text": f"Zu „{text_.strip()}“ habe ich im Katalog nichts Passendes gefunden. Versuch es mit einem anderen Namen oder schreib „keins“."} \
            if (r["payload"] or {}).get("suche") else {"treffer": False}
    produkte = bon._kandidaten_laden(con, [x["rewe_product_id"] for x in treffer])
    kandidaten = []
    for x in treffer:
        p = produkte.get(x["rewe_product_id"])
        if p:
            p["anzeige"] = bon.produkt_anzeige(p)
            kandidaten.append(p)
        if len(kandidaten) == 3:
            break
    con.execute("UPDATE offene_rueckfragen SET kandidaten = %s, payload = payload || %s WHERE id = %s",
                (Jsonb(kandidaten), Jsonb({"zuletzt": time.time()}), r["id"]))
    return {"treffer": True, "aktion": "kandidaten", "rueckfrage_id": r["id"], "bon_zeile_id": r["bon_zeile_id"],
            "text": kandidaten_text(r["bon_text"], kandidaten), "kandidaten": kandidaten}


def _produkt_und_menge(con, r: dict, rest: str, menge: float, einheit: str | None) -> dict | None:
    """Antwort mit Produktname und Menge zu einer offenen Produktwahl. Nennt sie eindeutig einen Kandidaten oder (bei anderem Namen) klar
    ein Katalogprodukt, wird es gewählt und die Menge des Nutzers gleich mitgenommen (sie geht vor der Packungsgröße). Ist es nicht
    eindeutig, kommen Vorschläge und die Menge wird bis zur Auswahl gemerkt. None: die Antwort nennt nur die Bonzeile selbst."""
    from . import bon, text as textmodul
    worte = _woerter(rest)
    if not worte:
        return None

    def treffer_wert(name: str) -> int:
        n = normalisieren(name)
        return sum(1 for w in worte if w in n or any(t.startswith(w) or w.startswith(t) for t in n.split() if len(t) >= 4))

    def waehlen(pid: str) -> dict:
        return {"treffer": True, "aktion": "produkt_waehlen", "rueckfrage_id": r["id"], "bon_zeile_id": r["bon_zeile_id"],
                "rewe_product_id": pid, "menge": menge, "einheit": einheit, "payload": r["payload"]}

    def vorschlagen(kandidaten: list[dict]) -> dict:
        payload = {**(r["payload"] or {}), "menge_wunsch": {"menge": menge, "einheit": einheit}, "zuletzt": time.time()}
        con.execute("UPDATE offene_rueckfragen SET kandidaten = %s, payload = %s WHERE id = %s", (Jsonb(kandidaten), Jsonb(payload), r["id"]))
        return {"treffer": True, "aktion": "kandidaten", "rueckfrage_id": r["id"], "bon_zeile_id": r["bon_zeile_id"], "kandidaten": kandidaten,
                "text": kandidaten_text(r["bon_text"], kandidaten) + f"\nDie Menge {menge:g} {einheit or ''} merke ich mir."}

    # 1) einer der bisherigen Vorschläge passt am besten
    bewertet = [(treffer_wert(k.get("name") or ""), k) for k in r["kandidaten"] or [] if k.get("name")]
    beste = max((w for w, _ in bewertet), default=0)
    besten = [k for w, k in bewertet if w == beste and beste > 0]
    if len(besten) == 1:
        return waehlen(besten[0]["rewe_product_id"])
    ziel_worte = _woerter(f"{r['bon_text'] or ''} {(r['payload'] or {}).get('name') or ''}")
    fremd = {w for w in worte if not any(w in z or z in w for z in ziel_worte)}
    if len(besten) > 1 and not fremd:
        return vorschlagen(besten[:3])                      # gleich gute Vorschläge („Kefir 500 g“): Auswahl zeigen
    if not fremd and beste == 0:
        return None
    # 2) anderes Produkt aus dem Katalog
    treffer = textmodul.suche(con, rest, 0.5, 8)
    if not treffer or treffer[0]["score"] < 0.6:
        return None
    produkte = bon._kandidaten_laden(con, [t["rewe_product_id"] for t in treffer])
    zeile = con.execute("SELECT bon_text, anzahl, einzelpreis, kilopreis FROM bon_zeilen WHERE id = %s", (r["bon_zeile_id"],)).fetchone()
    zdict = {"bon_text": zeile[0] if zeile else r["bon_text"], "anzahl": zeile[1] if zeile else 1, "einzelpreis": zeile[2] if zeile else None,
             "kilopreis": zeile[3] if zeile else None}
    liste = []
    for t in treffer:
        pr = produkte.get(t["rewe_product_id"])
        if pr:
            pr["rang"] = bon.bewerten(zdict, pr, t["score"])
            pr["anzeige"] = bon.produkt_anzeige(pr)
            liste.append(pr)
    liste.sort(key=lambda x: -x["rang"])
    if len(liste) > 1 and liste[0]["rang"] - liste[1]["rang"] < 0.1:
        return vorschlagen(liste[:3])
    return waehlen(liste[0]["rewe_product_id"])
