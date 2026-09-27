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
   | Grocy API | Custom Auth (Template) | `{"headers":{"GROCY-API-KEY":"{{api_key}}"}}` |
3. **„Vorrat · Grocy einrichten“** einmal ausführen (URL im Node „Einstellungen“, Standard `http://grocy:80`).
4. **Telegram-Webhook:** n8n braucht eine öffentliche HTTPS-URL (z. B. ngrok-Static-Domain oder Cloudflare Tunnel) und `WEBHOOK_URL=https://…/` in der n8n-Umgebung.
5. Workflows 01–04 aktivieren, dem Bot `/start` schicken, dann Ziele senden: *„Meine Ziele: 2200 kcal, 160 g Protein, 70 g Fett, 220 g KH, 3 Mahlzeiten“*.

## Sichern & Wiederherstellen

```bash
./scripts/export.sh   # n8n → workflows/*.json (danach committen)
./scripts/import.sh   # workflows/*.json → n8n (gleiche IDs, überschreibt)
```

Credentials sind **nicht** im Repo und müssen in einer neuen Instanz neu angelegt werden. Die Workflows referenzieren Datentabellen und den Planer per ID. Bei einer frischen n8n-Instanz Tabellen laut `data-tables/schema.json` anlegen und die IDs in den JSON-Dateien ersetzen.

## Hinweise

- eBons sind Text-PDFs, OCR ist nicht nötig. Bild-PDFs werden per Telegram gemeldet.
- OpenFoodFacts-Suche: max. ~10 Anfragen/min, daher 6,5 s Abstand und nur für neue Produkte (Cache in `vorrat_produkte`). Ohne Barcode wird über den Namen gesucht; unsichere Treffer werden verworfen und durch KI-Schätzwerte ersetzt.
- Modell: überall `MiniMax-M2` (Nodes „MiniMax liest Bon aus“, „MiniMax plant Rezepte“, „MiniMax Chat-Modell“).
