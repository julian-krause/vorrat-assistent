# Vorrats- & Ernährungsassistent (n8n + Grocy + OpenFoodFacts)

REWE-eBons landen automatisch im Grocy-Vorrat. Ein Telegram-Bot schlägt gesunde Rezepte und Wochenpläne passend zu deinen Kalorien-/Makrozielen vor, bucht Gekochtes aus und warnt, bevor etwas abläuft.

## Architektur

```
iCloud-Mail (REWE eBon, PDF)
   │
   ▼
01 eBon-Import ──► MiniMax (Artikel, Menge, MHD-Schätzung)
   │                 │
   │                 ├─ Produkt in Grocy vorhanden → einbuchen
   │                 └─ neu → OpenFoodFacts (Nährwerte, Nutri-Score, Packungsgröße)
   │                          → Grocy-Produkt anlegen → Cache vorrat_produkte
   ▼
Grocy (Bestand, MHD, Einkaufsliste)  ◄──────────────┐
   │                                                │
   ▼                                                │
02 Planer (Rezepte / Wochenplan, Makroziele) ───────┤ Einkaufsliste
   │                                                │
   ▼                                                │
03 Telegram-Bot  ── „✅ Gekocht“ → Grocy consume ───┘
   ▲             ── Chat-Agent (Verbrauch, MHD, Ziele)
   │
04 MHD-Wächter (täglich 8 Uhr): „Iss das zuerst“, Abgelaufenes, heutige Mahlzeiten
```

| Datei | Workflow | Trigger |
|---|---|---|
| `workflows/00-grocy-einrichten.json` | Vorrat · Grocy einrichten | manuell, einmalig |
| `workflows/01-ebon-import.json` | Vorrat · eBon-Import (REWE → Grocy) | IMAP (iCloud) |
| `workflows/02-planer.json` | Vorrat · Planer (Rezepte & Wochenplan) | Sub-Workflow + So 10:00 |
| `workflows/03-telegram-bot.json` | Vorrat · Telegram-Bot | Telegram |
| `workflows/04-mhd-waechter.json` | Vorrat · MHD-Wächter | täglich 08:00 |
| `workflows/05-fehlermeldung.json` | Vorrat · Fehlermeldung (Telegram) | Error Trigger (Fehler-Workflow von 01–04, 06, 07) |
| `workflows/06-rewe-angebote.json` | Vorrat · REWE-Angebote (wöchentlich) | Mo 06:00 |
| `workflows/07-rewe-crawl.json` | Vorrat · REWE-Crawl (monatlich) | am 1. um 02:00 |
| `workflows/08-verzehr-erfassen.json` | Vorrat · Verzehr erfassen | alle 5 Minuten |

Zeitzone der Zeitpläne: `Europe/Berlin` (in den Workflow-Einstellungen gesetzt).

Datentabellen (n8n Data Tables): siehe `data-tables/schema.json`.

## Einrichtung

1. **Grocy starten:** `docker compose -f docker/grocy.compose.yml up -d` → http://localhost:9283 (Standard-Login admin/admin, sofort ändern) → Einstellungen → API-Schlüssel anlegen.
2. **Credentials in n8n anlegen:**
   | Name | Typ | Inhalt |
   |---|---|---|
   | iCloud IMAP | IMAP | `imap.mail.me.com`, Port 993, SSL, app-spezifisches Passwort |
   | MiniMax | OpenAI | API-Key, Base URL `https://api.minimax.io/v1` |
   | Telegram Vorrats-Bot | Telegram | Token von @BotFather |
   | Grocy API | Custom Auth | `{"headers":{"GROCY-API-KEY":"<API-Key>"}}` |
   | REWE Postgres | Postgres | Host `rewe-db`, Port 5432, DB `rewe`, User `n8n`, Passwort = `REWE_DB_N8N_PASSWORD` aus `docker/rewe.env`, SSL aus |
3. **„Vorrat · Grocy einrichten“** einmal ausführen (URL im Node „Einstellungen“, Standard `http://grocy:80`).
4. **Telegram-Webhook:** n8n braucht eine öffentliche HTTPS-URL (z. B. ngrok-Static-Domain oder Cloudflare Tunnel) und `WEBHOOK_URL=https://…/` in der n8n-Umgebung.
5. Workflows 01–04 aktivieren, dem Bot `/start` schicken, dann Ziele senden: *„Meine Ziele: 2200 kcal, 160 g Protein, 70 g Fett, 220 g KH, 3 Mahlzeiten“*.

## KI-Agent im Telegram-Bot

Der Node „Vorrats-Assistent“ (MiniMax-M3, Gedächtnis: letzte 10 Nachrichten) hat diese Tools:

| Tool | Zweck | Art |
|---|---|---|
| `grocy_bestand` | aktueller Bestand (product_id, Menge, MHD) | HTTP → Grocy |
| `grocy_produkt_suchen` | Duplikatprüfung per Name oder Barcode (`/api/stock/products/by-barcode/{ean}`) | HTTP → Grocy |
| `grocy_produkt_anlegen` | neues Produkt (`POST /api/objects/products`) inkl. kcal | HTTP → Grocy |
| `grocy_barcode_zuordnen` | EAN zum Produkt speichern (`/api/objects/product_barcodes`) | HTTP → Grocy |
| `naehrwerte_merken` | Makros pro 100 g in `vorrat_produkte` (für Planer/Rezepte) | n8n-Datentabelle |
| `grocy_bestand_hinzufuegen` | Einkauf einbuchen | HTTP → Grocy |
| `grocy_bestand_verbrauchen` | gegessen/weggeworfen ausbuchen | HTTP → Grocy |
| `grocy_eintraege`, `grocy_mhd_aendern` | MHD korrigieren | HTTP → Grocy |
| `rewe_produkt_suchen` | lokale REWE-Produkttabelle (Marke, Größe, Preis, Preis/kg, Angebot, Makros, Preis pro 100 g Protein) | Postgres |
| `verzehr_eintragen`, `verzehr_auswerten`, `verzehr_eintraege`, `verzehr_korrigieren` | Ist-Verbrauch protokollieren, auswerten, korrigieren | Postgres |
| `profil_lesen`, `ziele_speichern` | Ernährungsziele | n8n-Datentabelle |

- **Produkt aufnehmen** („Nimm Skyr von Milbona auf“): Duplikat prüfen → `rewe_produkt_suchen` → Zusammenfassung (Größe, Preis, Makros) → erst nach „ja“ anlegen. Ohne REWE-Treffer fragt der Agent nach Größe und Nährwerten, statt zu raten.
- **Harte Sperre:** `grocy_produkt_anlegen` schreibt nur, wenn die aktuelle Nachricht mit einer Zustimmung beginnt (ja, ok, passt, genau, leg an …). Sonst lehnt Grocy den Request ab (Feld `ABGELEHNT_kein_ja_vom_Nutzer…`), auch wenn das Modell es trotzdem versucht.
- **Ein-/Ausbuchen** bei klaren Angaben („Hab 2 Eier gegessen“) ohne Rückfrage, danach kurze Bestätigung.
- Standardwerte beim Anlegen: Lagerorte Kühlschrank = 3, Tiefkühler = 4, Vorratsschrank = 5 (Standard); Einheiten Gramm = 4, Milliliter = 6, Stück = 5 (Kauf-, Lager-, Verbrauchs- und Preiseinheit gleich). `calories` = kcal pro Lagereinheit.
- Gedächtnis: „Postgres Chat Memory“ (letzte 10 Nachrichten pro Chat) in der REWE-Postgres, Schema `chat` (gehört der Rolle `n8n`, Suchpfad `chat, public`) – bleibt über n8n-Neustarts erhalten.

## REWE-Dienst (rewerse)

Ein eigener Container (`rewe-service/`, FastAPI) kapselt die inoffizielle REWE-App-API über [rewerse](https://github.com/ByteSizedMarius/rewerse-engineering) und schreibt in eine eigene Postgres-Instanz (`rewe-db`). Beide laufen nur im Docker-Netz `n8n_default`, ohne veröffentlichte Ports. Die API ist inoffiziell und kann jederzeit brechen; die Nutzung erfolgt auf eigenes Risiko gegenüber den REWE-Nutzungsbedingungen.

### Zertifikate einrichten

Die REWE-API verlangt mTLS-Zertifikate aus der REWE-Android-App. Sie sind nicht im Repo und dürfen nicht committet werden (`.gitignore`: `docker/rewe-certs/`, `*.pem`, `*.key`, `*.pfx`).

1. REWE-APK herunterladen (z. B. über apkpure), in `.zip` umbenennen und öffnen. Bei einer `.xapk` zuerst `de.rewe.app.mobile.apk` herauskopieren und diese wieder als ZIP öffnen.
2. `res/raw/mtls_prod.pfx` herauskopieren.
3. Zertifikat und Schlüssel extrahieren (das PFX-Passwort steht in Schritt 5 dieser [Anleitung](https://github.com/torbenpfohl/rewe-discounts/blob/main/how%20to%20get%20private.pem%20and%20private.key.txt)):
   ```bash
   openssl pkcs12 -in mtls_prod.pfx -out rewe.pem -legacy -nokeys
   openssl pkcs12 -in mtls_prod.pfx -out rewe.key -legacy -nocerts -nodes
   ```
4. Beide Dateien auf der VM ablegen: `~/vorrat-assistent/docker/rewe-certs/rewe.pem` und `…/rewe.key` (z. B. `scp rewe.pem rewe.key vorrat-azure:vorrat-assistent/docker/rewe-certs/`, danach `chmod 600`). Der Container liest sie über `REWE_CERT_PATH=/certs/rewe.pem` und `REWE_KEY_PATH=/certs/rewe.key` (Volume, nur lesend).

### Starten und Markt-ID ermitteln

```bash
cd ~/vorrat-assistent/docker
cp rewe.env.example rewe.env    # Passwörter setzen (openssl rand -hex 24), Datei nicht committen
docker compose --env-file rewe.env -f rewe.compose.yml up -d --build
docker exec rewe-service python -c "import urllib.request,json;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/markets/search?q=48143')),indent=1,ensure_ascii=False))"
```

Die passende `market_id` als `REWE_MARKET_ID` in `docker/rewe.env` eintragen und den Dienst neu starten (`… up -d`). Danach die Workflows „REWE-Angebote“ und „REWE-Crawl“ in n8n aktivieren.

Aktuell eingerichtet: **Sortiment und Preise aus Markt 1940222 (REWE Warendorfer Str. 54, Abholservice), Angebote aus Markt 1940430 (REWE Catharina-Müller-Str. 4-8, Münster Nord, dort wird eingekauft).** Die Suche liefert pro Stadt nur ~20 Märkte; gesucht wird am besten mit PLZ oder Stadtteil.

**Warum ein Abholmarkt:** Der Lieferservice hat eigene (teils höhere) Preise und ein kleineres Sortiment. Im Abholservice gelten die Ladenpreise und das volle Sortiment – für den eBon-Abgleich entscheidend (Beispiel: „Harry 1688 Steinofenbrot 500g“ für 1,89 € gibt es nur im Abholsortiment, die Hähnchenlyoner kostet im Laden und bei Abholung 2,19 €, im Lieferservice 2,29 €). Die Produkt-IDs sind in allen Märkten gleich. `REWE_MARKET_ID` = Sortiment/Preise, `REWE_ANGEBOTE_MARKET_ID` = Angebote.

**Abholung vs. Lieferung:** Der Markt 1940430 bietet keine Abholung an. rewerse fragt Produktdetails und Kategorien fest mit dem Service „PICKUP“ an, was die API für solche Märkte mit „Invalid market selection“ ablehnt. Der Dienst ermittelt den Service-Typ deshalb aus den Marktdetails (hier `DELIVERY`, überschreibbar mit `REWE_SERVICE_TYPE`), nutzt ihn für Suche, Listen und Kategorien und holt Produktdetails über eine eigene Anfrage (`app/rewe.py`).

### Endpunkte (`http://rewe-service:8000`)

Die Live-Seite ist im Tailnet unter https://vorrat.tail892968.ts.net:8444/ erreichbar (`127.0.0.1:8010` auf der VM, freigegeben mit `sudo tailscale serve --bg --https=8444 http://127.0.0.1:8010`, nicht öffentlich).


| Endpunkt | Zweck |
|---|---|
| `GET /` | **Live-Seite** zum Crawl (Fortschritt, Tempo, voraussichtliches Ende, zuletzt verarbeitete Produkte, Protokoll) |
| `GET /stats` | Zahlen für die Live-Seite |
| `GET /health` | Status, Zertifikate vorhanden, Markt-ID, Anzahl Produkte |
| `GET /markets/search?q=PLZ` | Märkte suchen (Markt-ID) |
| `GET /categories` | Shop-Kategorien des Marktes + konfigurierte Kategorien |
| `GET /products/search?q=…` | Live-Suche im Shop (Test/Debug) |
| `GET /products/{id}` | Live-Produktdetails inkl. Nährwerte (nur anzeigen) |
| `POST /products/{id}/aktualisieren` | Details live holen und speichern: Verlauf in `rewe_naehrwert_verlauf`, leere Werte überschreiben nie, unplausible Werte werden nicht übernommen, > 20 % Abweichung bei gleichem Namen/Größe wird gemeldet (`meldungen`) |
| `GET /debug/raw/product/{id}` | ungefilterte API-Antwort, prüft auf EAN/GTIN-Felder |
| `GET /discounts` | Angebote des Marktes (für Workflow 06) |
| `POST /crawl` | Crawl im Hintergrund starten bzw. abgebrochenen Lauf fortsetzen |
| `GET /crawl/status`, `POST /crawl/stop` | Fortschritt, Log, Stopp |

Mini-Crawl zum Testen: `POST /crawl` mit `{"kategorien": ["Obst & Gemüse"], "max_seiten": 1, "max_details": 5, "neu": true}`.
Beide REWE-Workflows haben zusätzlich einen Node „Manuell starten“, um sie in n8n per Klick auszuführen.

### Crawl

- Kategorien stehen in `rewe-service/kategorien.yml` als REWE-Slugs (per Volume eingebunden, ohne Neubau änderbar). `GET /categories` zeigt die echten Namen und Slugs des Marktes. Aktuell ~3.000 Lebensmittel (ohne Eis, Pizza, Kuchen, Süßes, Getränke); der erste Crawl dauert wegen der Detailabrufe etwa 2–3 Stunden.
- Listenansicht → Upsert über `rewe_product_id` (Preis, Größe, `last_seen`) + Eintrag in `rewe_price_history`. Nicht mehr gelistete Produkte bleiben stehen.
- Details (Marke, Beschreibung, `nutritionFacts` → kcal/Protein/KH/Fett/Zucker/Ballaststoffe/Salz pro 100 g): zuerst Produkte ohne Details (neu, oder Name/Größenangabe hat sich in der Listenansicht geändert → `details_fetched_at` wird zurückgesetzt), danach pro Lauf die ältesten Details bis `REWE_DETAILS_ERNEUERN` (Standard 1.500, pro Lauf auch als `max_erneuern` übergebbar). Liefert REWE einen Barcode, aber keine Nährwerte, und hat das Produkt noch keine REWE-Werte, wird Open Food Facts per Barcode gefragt.
- Alle Nährwert-Schreibvorgänge laufen über `app/naehrwerte.py`: Verlauf in `rewe_naehrwert_verlauf`, leere Werte überschreiben nie, unplausible Werte (kcal ≠ 4·P + 4·KH + 9·F ± 15 % oder P + F + KH > 100 g) werden nicht übernommen, mehr als 20 % Abweichung bei unverändertem Namen/Größe wird trotzdem gespeichert, aber gemeldet (Tabelle `meldungen`, Versand nachts per Telegram).
- **Barcode:** Die API hat kein eigenes EAN-Feld, aber die `articleId` ist im Onlineshop meist die GTIN/EAN (geprüft mit Open Food Facts, z. B. Arla Skyr Natur 450 g = 4016241030603). Sie wird gespeichert, wenn die GS1-Prüfziffer stimmt; sonst bleibt `ean` leer (im Test: 40 von 64 Produkten mit EAN).
- Größe aus Texten wie „500g (1 kg = 3,98 €)“, „6 x 1,5 l“, „10 Stück“ → `size_value`/`size_unit` (g/ml/Stück), daraus `price_per_kg_or_l`. Nicht erkannte Größen landen in `crawl_log`.
- 2–3 s Pause zwischen Requests. Der Fortschritt wird nach jeder Seite gespeichert; nach einem Abbruch setzt der nächste `POST /crawl` an derselben Stelle fort.
- Tests: `docker exec rewe-service python -m pytest -q tests` (Parser und Crawler gegen nachgebaute API-Antworten).

## Vorratsprodukte und Nährwert-Quellen

`vorrat_produkte` (Postgres, ein Eintrag je Grocy-Produkt) verknüpft Grocy mit REWE (`rewe_product_id`) und hält eigene Werte nur dort, wo REWE keine hat oder der Nutzer korrigiert. Die View **`vorrat_naehrwerte`** liefert pro Produkt den besten Wert mit `naehrwert_quelle`/`naehrwert_rang`, dazu Stückgewicht (`gramm_pro_stk`, essbarer Anteil, mit `gramm_quelle`/`gramm_rang`), `geschaetzt` und `kcal_pro_einheit` (für das Grocy-Feld). Sie ist die einzige Wahrheit; das kcal-Feld in Grocy ist nur eine Kopie.

| Rang | Nährwerte | Stückgewicht |
|---|---|---|
| 1 | `manuell` (Etikett-Foto, Korrektur durch den Nutzer) | `manuell` (gewogen) |
| 2 | `rewe` (Packungsangabe aus `rewe_products`, nur wenn plausibel) | `packung` (z. B. Gewichtsklasse im Namen) |
| 3 | `off_barcode` (Open Food Facts per EAN) | `referenz` (Standard-Stückgewichte) |
| 4 | `off_name` (Namenssuche, nur bei gleicher Marke) | `ki` |
| 5 | `bls` (Bundeslebensmittelschlüssel) | |
| 6 | `ki` (Schätzung) | |

Geschrieben wird nur über den rewe-service (`POST /vorrat/produkte/{grocy_id}`), der die Regeln prüft: schlechter überschreibt nie besser, leere Werte überschreiben nie, unplausible Werte werden abgelehnt und gemeldet. Gelesen wird direkt aus der View (Planer, Verzehr-Abgleich) oder über `GET /vorrat/produkte/{grocy_id}`. Die frühere n8n-Datentabelle `vorrat_produkte` wurde mit `POST /vorrat/migrieren` übernommen (REWE-ID aus der Grocy-Beschreibung „REWE-ID 123“).

## Ist-Verbrauch (Verzehr-Protokoll)

Unabhängig vom Plan wird festgehalten, was tatsächlich gegessen wurde – Tabelle `verzehr` in der REWE-Postgres, mit Zeitstempel und zum Zeitpunkt des Essens festgeschriebenen Nährwerten:

| Quelle | Wie es hineinkommt |
|---|---|
| `grocy` | Workflow 08 übernimmt alle 5 Minuten jede Verbrauchsbuchung aus Grocy (Chat „Hab 2 Eier gegessen“, „✅ Gekocht“, Grocy-App). Weggeworfenes zählt nicht; rückgängig gemachte Buchungen werden als ignoriert markiert. Nährwerte aus der View `vorrat_naehrwerte`. |
| `rezept` | „✅ Gekocht“: Zutaten, die nicht (ganz) aus dem Vorrat abgebucht werden konnten, mit den Nährwerten pro 100 g aus dem Rezept (ältere Rezepte: anteilig, als geschätzt markiert). |
| `manuell` | Der Agent trägt auswärts Gegessenes ein („Mittags Currywurst in der Mensa“), mit geschätzten oder REWE-Nährwerten. |

Auswertung: `verzehr_auswertung(von, bis)` summiert kcal/Protein/Fett/KH und teilt durch die Kalendertage (bei einem laufenden Monat bis heute); dazu Tage mit Einträgen, Anteil geschätzter Werte und die häufigsten Lebensmittel. Im Chat z. B. „Wie viel habe ich im September durchschnittlich gegessen?“. Korrekturen setzen `ignoriert` (statt zu löschen), damit der Abgleich Grocy-Buchungen nicht neu anlegt.

## Wochenplan mit REWE-Produkten

Nach „MiniMax plant Rezepte“ sammelt der Planer alle Zutaten, die nicht aus dem Vorrat kommen, und fragt `POST /planer/kandidaten`: bis zu 8 REWE-Kandidaten je Zutat (Wortsuche mit Synonymen wie „Vollkornnudeln“ → „Vollkorn Penne“, Ähnlichkeitssuche; Geschmacksvarianten und Klammerzusätze wie „(Rest)“/„(TK)“ werden ausgefiltert bzw. ignoriert). „MiniMax wählt Produkte“ nimmt daraus das passende Grundprodukt (z. B. für „Olivenöl“ das Öl, nicht „Feta in Olivenöl“) oder keins.

Ergebnis: Nährwerte der Zutaten aus den REWE-Daten statt KI-Schätzung, Einkaufsliste mit konkreten Produkten („3× ja! Eismeergarnelen 225g · 3,29 €“), Angeboten (🏷️) und geschätzten Wochenkosten. Fällt der REWE-Dienst oder die Produktwahl aus, entsteht der Plan wie vorher ohne REWE-Daten. Ungültiges JSON der KI wird einmal automatisch repariert (z. B. „1.“ oder Dezimalkomma).

## eBon → REWE-Produkte

Der eBon enthält nur abgekürzte Kassentexte („HAHN.LYONER 2,19 B“), keine Barcodes. Der eBon-Import schickt den PDF-Text an `POST /bon/zuordnen`:

1. **Bon lesen** (Code, nicht KI): Kassentext, Betrag, „2 Stk x 1,19“, „0,524 kg x 1,39 EUR/kg“, Datum, Marktnummer.
2. **Zuordnen** pro Zeile: Lerntabelle `bon_zuordnung` → Produkte mit exakt passendem Preis (aktuell, Angebot oder Preisverlauf ±45 Tage; bei Gewichtsware Preis pro kg) → Textabgleich (jedes Wort des Kassentexts muss – auch abgekürzt – im Produktnamen vorkommen; „STEINOFENBROT“ passt nicht auf „…brötchen“, mit Punkt abgekürzte Wörter wie „HAHN.“ dürfen verlängert werden).
3. **Sicher** (genau ein Treffer) → Produkt wird mit REWE-Name, Marke, Packungsgröße, Barcode und REWE-Nährwerten angelegt/eingebucht (ohne Open-Food-Facts-Suche) und in der Lerntabelle gemerkt.
4. **Unsicher** → nach der Einkaufsmeldung fragt der Bot per Telegram mit bis zu 3 Vorschlägen + „Keins davon“. Die Antwort (`POST /bon/antwort`) landet bestätigt in der Lerntabelle; das Grocy-Produkt wird umbenannt, bekommt Barcode und REWE-Nährwerte.

Probelauf mit dem Bon vom 28.09.2026: 6 von 9 Zeilen sicher, 3 Rückfragen (zwei Lyoner-Sorten zum selben Preis, Bio-Eier, Mineralwasser), keine ohne Vorschlag. Grocy-Schreibzugriffe im eBon-Import laufen nacheinander mit Wiederholung (parallele Buchungen führten zu Grocy-Fehlern).

## Sichern & Wiederherstellen

```bash
./scripts/export.sh   # n8n → workflows/*.json (danach committen)
./scripts/import.sh   # workflows/*.json → n8n (gleiche IDs, überschreibt)
```

Credentials sind **nicht** im Repo und müssen in einer neuen Instanz neu angelegt werden. Die Workflows referenzieren Datentabellen und den Planer per ID. Bei einer frischen n8n-Instanz Tabellen laut `data-tables/schema.json` anlegen und die IDs in den JSON-Dateien ersetzen.

## Hinweise

- eBons sind Text-PDFs, OCR ist nicht nötig. Bild-PDFs werden per Telegram gemeldet.
- OpenFoodFacts-Suche: max. ~10 Anfragen/min, daher 6,5 s Abstand und nur für neue Produkte (Cache in `vorrat_produkte`). Ohne Barcode wird über den Namen gesucht; unsichere Treffer werden verworfen und durch KI-Schätzwerte ersetzt.
- Planer: Die KI liefert nur Rezepte mit Zutatenmengen, Packungsgrößen und Nährwerten pro 100 g. Der Node „Antwort auswerten“ berechnet kcal/Makros selbst (Vorrat: OpenFoodFacts-Werte), skaliert die Mengen pro Mahlzeit und Tag auf die Ziele und erstellt die Einkaufsliste in kaufbaren Einheiten. Ein neuer Wochenplan ersetzt die Grocy-Einkaufsposten derselben Kalenderwoche.
- Modell: überall `MiniMax-M3` (Nodes „MiniMax liest Bon aus“, „MiniMax plant Rezepte“, „MiniMax Chat-Modell“). eBon-Import und Planer senden `thinking: {type: "disabled"}`, weil M3 mit Denkphase beim Wochenplan das gesamte Token-Budget fürs Nachdenken verbraucht; der Chat-Agent nutzt die Standardeinstellung.
