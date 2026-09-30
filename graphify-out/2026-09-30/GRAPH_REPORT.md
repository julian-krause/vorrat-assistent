# Graph Report - vorrat-assistent  (2026-09-30)

## Corpus Check
- 51 files · ~76,305 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 2, .csv 2, .example 1)

## Summary
- 610 nodes · 1286 edges · 27 communities (24 shown, 3 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 21 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c9d38bda`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- REWE-Dienst (rewerse, FastAPI)
- ermitteln
- test_bon.py
- speichern
- verbinden
- test_parse.py
- rewe.py
- bls.py
- Crawler
- normalisieren
- planer.test.cjs
- export.sh
- import.sh
- test_rueckfragen.py
- main.py
- bon.py
- ermitteln.py
- naehrwerte.py
- test_suche.py
- test_naehrwerte.py
- crawler.py
- zuordnen
- verzehr.py
- bestimmen
- produkt_anzeige
- finde_ean
- run.sh

## God Nodes (most connected - your core abstractions)
1. `normalisieren()` - 30 edges
2. `verbinden()` - 25 edges
3. `ermitteln()` - 21 edges
4. `auswerten()` - 21 edges
5. `zuordnen()` - 20 edges
6. `speichern()` - 19 edges
7. `antwort_speichern()` - 14 edges
8. `details_uebernehmen()` - 14 edges
9. `Crawler` - 14 edges
10. `rewe_speichern()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Standard-Stückgewichte (`app/stueckgewicht.py`, Tabelle `stueckgewichte`)` --references--> `stueckgewichte()`  [INFERRED]
  rewe-service/daten/QUELLEN.md → rewe-service/app/main.py
- `rewe-service Container` --references--> `REWE mTLS-Zertifikate`  [INFERRED]
  docker/rewe.compose.yml → README.md
- `REWE-Dienst (rewerse, FastAPI)` --references--> `rewe-service Python-Abhaengigkeiten`  [INFERRED]
  README.md → rewe-service/requirements.txt
- `Grocy (Bestand, MHD, Einkaufsliste)` --references--> `grocy Service (linuxserver/grocy)`  [EXTRACTED]
  README.md → docker/grocy.compose.yml
- `rewe-service Container` --references--> `Crawl-Kategorien (REWE-Slugs)`  [EXTRACTED]
  docker/rewe.compose.yml → rewe-service/kategorien.yml

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Naehrwert-Ermittlung ueber Quellen-Rangfolge** — readme_naehrwerte_ermitteln_endpoint, readme_naehrwert_rangfolge, readme_openfoodfacts, readme_bls, readme_minimax_m3, readme_vorrat_naehrwerte_view [EXTRACTED 1.00]
- **eBon-Import zu Grocy mit REWE-Zuordnung** — readme_workflow_ebon_import, readme_bon_zuordnen, readme_bon_zuordnung_lerntabelle, readme_rewe_products_table, readme_grocy [EXTRACTED 1.00]
- **Ist-Verbrauch erfassen, korrigieren und auswerten** — readme_workflow_08_verzehr_erfassen, readme_verzehr_protokoll, readme_verzehr_korrektur, readme_verzehr_auswertung, readme_workflow_09_nachtjob [EXTRACTED 1.00]
- **REWE-Crawl-Stack** — readme_workflow_rewe_crawl, readme_crawl, rewe_service_kategorien_kategorien, docker_rewe_compose_rewe_service, docker_rewe_compose_rewe_db, rewe_service_app_live_rewe_crawl_live [INFERRED 0.85]

## Communities (27 total, 3 thin omitted)

### Community 0 - "REWE-Dienst (rewerse, FastAPI)"
Cohesion: 0.05
Nodes (65): grocy Service (linuxserver/grocy), Docker-Netz n8n_default, rewe-db (postgres:17), rewe-service Container, Abholmarkt fuer Sortiment/Preise, Bundeslebensmittelschluessel (BLS) Tabelle bls, POST /bon/zuordnen (eBon -> REWE-Produkte), Lerntabelle bon_zuordnung (+57 more)

### Community 1 - "ermitteln"
Cohesion: 0.13
Nodes (17): ermitteln(), _in_warteschlange(), marke_passt(), _norm(), off_name_treffer(), Nachtjob: Anfragen, die am Open-Food-Facts-Limit gescheitert sind, erneut…, Bester Treffer der Namenssuche: Marke muss übereinstimmen, ≥ 60 % der…, a: grocy_product_id?, name, marke?, rewe_product_id?, ean?, einheit?,… (+9 more)

### Community 2 - "test_bon.py"
Cohesion: 0.11
Nodes (26): Decimal, bon_angabe(), bon_lesen(), ist_wasser(), ist_wasser_produkt(), ki_menge_pruefen(), menge_bestimmen(), Nur die Ziffern einer Zahl ohne führende Nullen: 4,45 -> „445“, 0,89 -> „89“,… (+18 more)

### Community 3 - "speichern"
Cohesion: 0.12
Nodes (22): alle_aktualisieren(), Stückgewichte aller Stückware-Produkte neu bestimmen (bessere Ränge ersetzen…, einheit_code(), lesen(), migrieren(), zeilen: n8n-Datentabelle vorrat_produkte + Grocy-Beschreibung (Feld…, Rang der (plausiblen) Nährwerte des verknüpften REWE-Produkts, 99 = keine., Legt an oder aktualisiert. daten (alles optional außer name bei neuen… (+14 more)

### Community 4 - "verbinden"
Cohesion: 0.06
Nodes (45): get, post, verbinden(), bls_suche(), bon_antwort(), bon_zuordnen(), crawl(), crawl_status() (+37 more)

### Community 5 - "test_parse.py"
Cohesion: 0.13
Nodes (24): _bezug_100(), ean_aus_article_id(), grundpreis(), gtin_gueltig(), _ist_pro_100(), parse_groesse(), parse_naehrwerte(), Umwandlung der REWE-Rohdaten: Packungsgröße, Grundpreis, Nährwerte, Barcode. (+16 more)

### Community 6 - "rewe.py"
Cohesion: 0.09
Nodes (39): exception_handler, httpx, json, random, Response, nicht_bereit(), _angebote(), aufruf() (+31 more)

### Community 7 - "bls.py"
Cohesion: 0.11
Nodes (22): csv, gzip, os, pathlib, psycopg, laden(), Bundeslebensmittelschlüssel (BLS) 4.0: Import und Suche. Quelle: Max Rubner-…, BLS-Tabelle aus der CSV füllen, wenn sie fehlt oder unvollständig ist. (+14 more)

### Community 8 - "Crawler"
Cohesion: 0.11
Nodes (15): _Abbruch, Crawler, RuntimeError, Läufe, die beim letzten Beenden noch liefen, gelten als abgebrochen…, Reihenfolge: Vorratsprodukte (jeder Lauf), ohne Details (neu oder Name/Größe…, FakeRewe, laufen(), fixture (+7 more)

### Community 9 - "normalisieren"
Cohesion: 0.06
Nodes (61): datetime, eintrag(), _eintrag(), Suchwörter in gemeinsamer Normalisierung (ä -> ae, …), Mehrzahl auf BLS-Form,…, Kandidaten für die KI: meiste Wort-Treffer im BLS-Namen zuerst (Marke, Größe,…, suche(), suchwoerter(), _produkt() (+53 more)

### Community 10 - "planer.test.cjs"
Cohesion: 0.07
Nodes (34): ref_fs, ref_node_assert, ref_node_test, ref_path, assert, { code, laufen, workflow }, test, u (+26 more)

### Community 13 - "test_rueckfragen.py"
Cohesion: 0.10
Nodes (39): _nachbuchen(), Produktwahl für eine noch nicht gebuchte Zeile („Menge offen“): steht die Menge…, abschliessen(), anlegen(), auswerten(), _in_einheit(), kandidaten_text(), offene() (+31 more)

### Community 14 - "main.py"
Cohesion: 0.15
Nodes (19): contextlib, FastAPI, fastapi_responses, listen_produkt(), produkt_aktualisieren(), Details eines Produkts sofort live holen und speichern (fehlt es in der…, categories(), baum() (+11 more)

### Community 15 - "bon.py"
Cohesion: 0.18
Nodes (19): bewerten(), _hat(), ist_wasser_marke(), _kandidaten_laden(), _kassenwoerter(), _preis_kandidaten(), date, REWE-eBon: Zeilen auslesen und den Produkten aus der REWE-Tabelle zuordnen. Der… (+11 more)

### Community 16 - "ermitteln.py"
Cohesion: 0.20
Nodes (11): logging, psycopg_types_json, pytest, re, Zentrale Nährwert-Ermittlung für eBon-Import und Bot: arbeitet die Rangfolge…, gewichtsklasse(), ist_ei(), Stückgewicht (immer essbarer Anteil): manuell (1) → Packung/Gewichtsklasse (2)… (+3 more)

### Community 17 - "naehrwerte.py"
Cohesion: 0.21
Nodes (15): abweichungen(), bereinigen(), gleich(), _log(), melden(), plausibel(), Nährwert-Regeln: Rangfolge der Quellen, Plausibilität, Verlauf und Meldungen.…, Einzige Stelle, die Nährwerte in rewe_products schreibt (Crawler und… (+7 more)

### Community 18 - "test_suche.py"
Cohesion: 0.17
Nodes (14): Katalog nach Ähnlichkeit durchsuchen: [{rewe_product_id, score, abdeckung}],…, suche(), _ids(), katalog(), fixture, Gemeinsame Normalisierung, Synonyme, Katalogsuche und Ranking der eBon-…, test_bon_0930_rheinfels_wird_nicht_gebucht(), test_bon_0930_zuordnung() (+6 more)

### Community 19 - "test_naehrwerte.py"
Cohesion: 0.18
Nodes (13): Aktueller Stand eines REWE-Produkts: Nährwerte, Quelle, Verlaufs-ID, Details-…, rewe_werte(), produkt(), fixture, parametrize, Nährwert-Regeln: Plausibilität, leer überschreibt nie, Rangfolge, Verlauf,…, test_abweichung_20_prozent(), test_einzelprodukt_aktualisieren() (+5 more)

### Community 20 - "crawler.py"
Cohesion: 0.21
Nodes (12): Connection, _alle_kategorien(), details_uebernehmen(), kategorien_aufloesen(), kategorien_config(), Fortsetzbarer Crawl der Lebensmittelkategorien eines REWE-Marktes. Phase…, Config-Einträge (Namensteile oder Slugs) -> [{name, slug}] anhand der Shop-…, Detailansicht eines Produkts übernehmen: Stammdaten + Nährwerte (REWE, sonst… (+4 more)

### Community 21 - "zuordnen"
Cohesion: 0.23
Nodes (12): antwort_speichern(), bonpreis_merken(), lernen(), Bestätigten Bonpreis pro Markt speichern (Ladenpreise weichen vom Katalogmarkt…, Liest den Bon, ordnet alle Zeilen zu und merkt sie sich (für die spätere…, Antwort auf die Rückfrage: Zuordnung lernen (oder „keins davon“ vermerken) und…, zuordnen(), Kassentext ohne „Wasser“: erkannt über Kategorie + Beschreibung des… (+4 more)

### Community 22 - "verzehr.py"
Cohesion: 0.22
Nodes (7): psycopg_rows, naehrwerte_nachtlauf(), Nächtliche Pflege: OFF-Warteschlange, Stückgewichte aus der Referenz, Verzehr-…, _aktuell(), korrigieren(), Korrektur des Verzehr-Protokolls (Nachtjob). Neu berechnet (Gramm × aktuelle…, Ist-Verbrauch: Auswertung pro Kalendertag, geschätzte Anteile, ignorierte…

### Community 23 - "bestimmen"
Cohesion: 0.25
Nodes (9): aus_gewogen(), bestimmen(), Vom Nutzer gewogenes Stück -> essbarer Anteil (Rang 1). Mit Schale/Kern nur mit…, Passende Zeile der Referenztabelle (Rang 3) für einen Produktnamen., Bestes Stückgewicht für Stückware: {gramm, quelle, rang, detail} oder None., referenz(), parametrize, test_bestimmen() (+1 more)

### Community 24 - "produkt_anzeige"
Cohesion: 0.40
Nodes (6): _de(), produkt_anzeige(), Bonzeile lesbar für die Rückfrage – nie leere Klammern: „0,106 kg × 3,99 €/kg =…, Kandidat für Buttons: Name · Preis · €/kg bzw. €/l · Packungsgröße (nur, was…, zeile_text(), test_rueckfrage_anzeige()

### Community 25 - "finde_ean"
Cohesion: 0.40
Nodes (5): debug_raw_product(), Ungefilterte API-Antwort + gefundene Barcode-Felder (Prüfung, ob REWE eine…, finde_ean(), Sucht rekursiv nach einem EAN/GTIN-Feld mit 8-14 Ziffern., test_ean()

## Knowledge Gaps
- **42 isolated node(s):** `export.sh script`, `import.sh script`, `test`, `assert`, `{ code, laufen, workflow }` (+37 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 216 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `normalisieren()` connect `normalisieren` to `test_bon.py`, `verbinden`, `bls.py`, `test_rueckfragen.py`, `bon.py`, `test_suche.py`, `zuordnen`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Why does `Crawler` connect `Crawler` to `crawler.py`, `main.py`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Why does `ermitteln()` connect `ermitteln` to `speichern`, `verbinden`, `rewe.py`, `normalisieren`, `main.py`, `ermitteln.py`, `naehrwerte.py`, `test_naehrwerte.py`, `bestimmen`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **What connects `export.sh script`, `import.sh script`, `test` to the rest of the system?**
  _42 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `REWE-Dienst (rewerse, FastAPI)` be split into smaller, more focused modules?**
  _Cohesion score 0.052403846153846155 - nodes in this community are weakly interconnected._
- **Should `ermitteln` be split into smaller, more focused modules?**
  _Cohesion score 0.13450292397660818 - nodes in this community are weakly interconnected._
- **Should `test_bon.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10541310541310542 - nodes in this community are weakly interconnected._