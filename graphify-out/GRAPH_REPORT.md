# Graph Report - vorrat-assistent  (2026-09-30)

## Corpus Check
- 58 files · ~83,865 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: .gz 5, (none) 2, .csv 2)

## Summary
- 699 nodes · 1469 edges · 27 communities (23 shown, 4 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 23 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c9d38bda`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- REWE-Dienst (rewerse, FastAPI)
- ermitteln.py
- test_bon.py
- speichern
- main.py
- crawler.py
- rewe.py
- bls.py
- Crawler
- planer.py
- planer.test.cjs
- export.sh
- import.sh
- auswerten
- test_ebon_pdfs.py
- normalisieren
- _produkt_und_menge
- naehrwerte.py
- test_suche.py
- test_naehrwerte.py
- package.json
- zuordnen
- __init__.py
- stueckgewicht.py
- bon.py
- ebon_text.sh
- run.sh

## God Nodes (most connected - your core abstractions)
1. `normalisieren()` - 34 edges
2. `verbinden()` - 25 edges
3. `auswerten()` - 23 edges
4. `zuordnen()` - 22 edges
5. `ermitteln()` - 22 edges
6. `speichern()` - 19 edges
7. `antwort_speichern()` - 15 edges
8. `vorgaben()` - 15 edges
9. `details_uebernehmen()` - 14 edges
10. `Crawler` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Protokoll der Prüfstand-Läufe (rewe-service/tests/test_ebon_pdfs.py + workflows/tests)` --references--> `test_extraktion_live()`  [INFERRED]
  eBon/testlaeufe.md → rewe-service/tests/test_ebon_pdfs.py
- `Standard-Stückgewichte (`app/stueckgewicht.py`, Tabelle `stueckgewichte`)` --references--> `stueckgewichte()`  [INFERRED]
  rewe-service/daten/QUELLEN.md → rewe-service/app/main.py
- `rewe-service Container` --references--> `REWE mTLS-Zertifikate`  [INFERRED]
  docker/rewe.compose.yml → README.md
- `REWE-Dienst (rewerse, FastAPI)` --references--> `rewe-service Python-Abhaengigkeiten`  [INFERRED]
  README.md → rewe-service/requirements.txt
- `Grocy (Bestand, MHD, Einkaufsliste)` --references--> `grocy Service (linuxserver/grocy)`  [EXTRACTED]
  README.md → docker/grocy.compose.yml

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Naehrwert-Ermittlung ueber Quellen-Rangfolge** — readme_naehrwerte_ermitteln_endpoint, readme_naehrwert_rangfolge, readme_openfoodfacts, readme_bls, readme_minimax_m3, readme_vorrat_naehrwerte_view [EXTRACTED 1.00]
- **eBon-Import zu Grocy mit REWE-Zuordnung** — readme_workflow_ebon_import, readme_bon_zuordnen, readme_bon_zuordnung_lerntabelle, readme_rewe_products_table, readme_grocy [EXTRACTED 1.00]
- **Ist-Verbrauch erfassen, korrigieren und auswerten** — readme_workflow_08_verzehr_erfassen, readme_verzehr_protokoll, readme_verzehr_korrektur, readme_verzehr_auswertung, readme_workflow_09_nachtjob [EXTRACTED 1.00]
- **REWE-Crawl-Stack** — readme_workflow_rewe_crawl, readme_crawl, rewe_service_kategorien_kategorien, docker_rewe_compose_rewe_service, docker_rewe_compose_rewe_db, rewe_service_app_live_rewe_crawl_live [INFERRED 0.85]

## Communities (27 total, 4 thin omitted)

### Community 0 - "REWE-Dienst (rewerse, FastAPI)"
Cohesion: 0.05
Nodes (65): grocy Service (linuxserver/grocy), Docker-Netz n8n_default, rewe-db (postgres:17), rewe-service Container, Abholmarkt fuer Sortiment/Preise, Bundeslebensmittelschluessel (BLS) Tabelle bls, POST /bon/zuordnen (eBon -> REWE-Produkte), Lerntabelle bon_zuordnung (+57 more)

### Community 1 - "ermitteln.py"
Cohesion: 0.13
Nodes (20): pytest, ermitteln(), _in_warteschlange(), marke_passt(), _norm(), off_name_treffer(), Zentrale Nährwert-Ermittlung für eBon-Import und Bot: arbeitet die Rangfolge…, Nachtjob: Anfragen, die am Open-Food-Facts-Limit gescheitert sind, erneut… (+12 more)

### Community 2 - "test_bon.py"
Cohesion: 0.13
Nodes (19): bon_lesen(), ist_wasser(), ist_wasser_produkt(), Manche PDF-Extraktoren trennen Kassentext und Betrag auf zwei Zeilen – wieder…, PDF-Text eines REWE-eBons -> Kaufdatum, Marktnummer und Artikelzeilen., _zeilen_zusammenfuegen(), Zutat plus Synonyme; bei Komposita wie „Vollkornnudeln“ auch „Vollkorn…, _suchbegriffe() (+11 more)

### Community 3 - "speichern"
Cohesion: 0.13
Nodes (22): psycopg_rows, alle_aktualisieren(), Stückgewichte aller Stückware-Produkte neu bestimmen (bessere Ränge ersetzen…, einheit_code(), lesen(), migrieren(), Vorratsprodukte in Postgres: Verknüpfung Grocy ↔ REWE, eigene Nährwerte und…, zeilen: n8n-Datentabelle vorrat_produkte + Grocy-Beschreibung (Feld… (+14 more)

### Community 4 - "main.py"
Cohesion: 0.05
Nodes (67): contextlib, FastAPI, fastapi_responses, get, post, listen_produkt(), verbinden(), bls_suche() (+59 more)

### Community 5 - "crawler.py"
Cohesion: 0.09
Nodes (35): re, _alle_kategorien(), kategorien_aufloesen(), kategorien_config(), Fortsetzbarer Crawl der Lebensmittelkategorien eines REWE-Marktes. Phase…, Config-Einträge (Namensteile oder Slugs) -> [{name, slug}] anhand der Shop-…, _bezug_100(), ean_aus_article_id() (+27 more)

### Community 6 - "rewe.py"
Cohesion: 0.10
Nodes (36): exception_handler, httpx, random, Response, nicht_bereit(), _angebote(), aufruf(), client() (+28 more)

### Community 7 - "bls.py"
Cohesion: 0.06
Nodes (47): Connection, csv, gzip, logging, os, pathlib, psycopg, eintrag() (+39 more)

### Community 8 - "Crawler"
Cohesion: 0.11
Nodes (15): _Abbruch, Crawler, RuntimeError, Läufe, die beim letzten Beenden noch liefen, gelten als abgebrochen…, Reihenfolge: Vorratsprodukte (jeder Lauf), ohne Details (neu oder Name/Größe…, FakeRewe, laufen(), fixture (+7 more)

### Community 9 - "planer.py"
Cohesion: 0.08
Nodes (43): datetime, _produkt(), _anreichern(), ausschluss_begriffe(), ausschluss_liste(), ausschluss_treffer(), bereits_gegessen(), _ist_variante() (+35 more)

### Community 10 - "planer.test.cjs"
Cohesion: 0.07
Nodes (35): ref_fs, ref_node_assert, ref_node_test, ref_path, assert, { code, laufen, workflow }, test, u (+27 more)

### Community 13 - "auswerten"
Cohesion: 0.11
Nodes (37): _nachbuchen(), Produktwahl für eine noch nicht gebuchte Zeile („Menge offen“): steht die Menge…, abschliessen(), anlegen(), auswerten(), _in_einheit(), offene(), parse_menge() (+29 more)

### Community 14 - "test_ebon_pdfs.py"
Cohesion: 0.06
Nodes (48): Protokoll der Prüfstand-Läufe (rewe-service/tests/test_ebon_pdfs.py + workflows/tests), json, lerntabelle_laden(), dumps(), GrocyDry, ki_antwort_fehlerhaft(), lauf(), minimax() (+40 more)

### Community 15 - "normalisieren"
Cohesion: 0.19
Nodes (17): bewerten(), _hat(), ist_wasser_marke(), _kassenwoerter(), _preis_kandidaten(), date, Wörter des Kassentexts mit Kennzeichen, ob sie mit Punkt abgekürzt sind…, Anteil der Kassentext-Wörter, die (auch abgekürzt oder in Komposita) im… (+9 more)

### Community 16 - "_produkt_und_menge"
Cohesion: 0.19
Nodes (13): _kandidaten_laden(), produkt_anzeige(), Kandidat für Buttons: Name · Preis · €/kg bzw. €/l · Packungsgröße (nur, was…, kandidaten_text(), _produkt_antwort(), _produkt_und_menge(), treffer_wert(), vorschlagen() (+5 more)

### Community 17 - "naehrwerte.py"
Cohesion: 0.21
Nodes (11): abweichungen(), bereinigen(), gleich(), _log(), melden(), Nährwert-Regeln: Rangfolge der Quellen, Plausibilität, Verlauf und Meldungen.…, Nur bekannte Felder mit Zahlenwert; leere Werte fallen weg., Felder, die sich um mehr als 20 % (und mehr als die Rundungsgrenze) geändert… (+3 more)

### Community 18 - "test_suche.py"
Cohesion: 0.22
Nodes (12): _ids(), katalog(), fixture, Gemeinsame Normalisierung, Synonyme, Katalogsuche und Ranking der eBon-…, test_bon_0930_rheinfels_wird_nicht_gebucht(), test_bon_0930_zuordnung(), test_katalogsuche_brokkoli_findet_broccoli(), test_planer_kandidaten_brokkoli() (+4 more)

### Community 19 - "test_naehrwerte.py"
Cohesion: 0.13
Nodes (21): details_uebernehmen(), produkt_aktualisieren(), Details eines Produkts sofort live holen und speichern (fehlt es in der…, Detailansicht eines Produkts übernehmen: Stammdaten + Nährwerte (REWE, sonst…, Einzige Stelle, die Nährwerte in rewe_products schreibt (Crawler und…, Aktueller Stand eines REWE-Produkts: Nährwerte, Quelle, Verlaufs-ID, Details-…, rewe_speichern(), rewe_werte() (+13 more)

### Community 20 - "package.json"
Cohesion: 0.15
Nodes (12): luxon, author, dependencies, luxon, description, keywords, license, main (+4 more)

### Community 21 - "zuordnen"
Cohesion: 0.20
Nodes (14): antwort_speichern(), bonpreis_merken(), lernen(), menge_bestimmen(), Bestätigten Bonpreis pro Markt speichern (Ladenpreise weichen vom Katalogmarkt…, Zu buchende Menge einer Bonzeile. vertrauen: „sicher“ | „bestaetigt“ |…, Liest den Bon, ordnet alle Zeilen zu und merkt sie sich (für die spätere…, Antwort auf die Rückfrage: Zuordnung lernen (oder „keins davon“ vermerken) und… (+6 more)

### Community 22 - "__init__.py"
Cohesion: 0.25
Nodes (5): psycopg_types_json, _aktuell(), korrigieren(), Korrektur des Verzehr-Protokolls (Nachtjob). Neu berechnet (Gramm × aktuelle…, Ist-Verbrauch: Auswertung pro Kalendertag, geschätzte Anteile, ignorierte…

### Community 23 - "stueckgewicht.py"
Cohesion: 0.15
Nodes (15): aus_gewogen(), bestimmen(), gewichtsklasse(), ist_ei(), Stückgewicht (immer essbarer Anteil): manuell (1) → Packung/Gewichtsklasse (2)…, Vom Nutzer gewogenes Stück -> essbarer Anteil (Rang 1). Mit Schale/Kern nur mit…, Passende Zeile der Referenztabelle (Rang 3) für einen Produktnamen., Ei mit Gewichtsklasse im Namen -> Rang 2 (Packungsangabe). (+7 more)

### Community 24 - "bon.py"
Cohesion: 0.16
Nodes (16): Decimal, bon_angabe(), _de(), ki_menge_pruefen(), REWE-eBon: Zeilen auslesen und den Produkten aus der REWE-Tabelle zuordnen. Der…, Bonzeile lesbar für die Rückfrage – nie leere Klammern: „0,106 kg × 3,99 €/kg =…, Nur die Ziffern einer Zahl ohne führende Nullen: 4,45 -> „445“, 0,89 -> „89“,…, Menge, die auf dem Bon selbst steht: gewogenes Gewicht oder… (+8 more)

## Knowledge Gaps
- **54 isolated node(s):** `ebon_text.sh script`, `export.sh script`, `import.sh script`, `test`, `assert` (+49 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 258 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `normalisieren()` connect `normalisieren` to `ermitteln.py`, `test_bon.py`, `bls.py`, `planer.py`, `auswerten`, `_produkt_und_menge`, `test_suche.py`, `zuordnen`, `bon.py`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Why does `Crawler` connect `Crawler` to `main.py`, `crawler.py`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Why does `ermitteln()` connect `ermitteln.py` to `speichern`, `main.py`, `rewe.py`, `test_ebon_pdfs.py`, `naehrwerte.py`, `test_naehrwerte.py`, `stueckgewicht.py`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **What connects `ebon_text.sh script`, `export.sh script`, `import.sh script` to the rest of the system?**
  _54 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `REWE-Dienst (rewerse, FastAPI)` be split into smaller, more focused modules?**
  _Cohesion score 0.052403846153846155 - nodes in this community are weakly interconnected._
- **Should `ermitteln.py` be split into smaller, more focused modules?**
  _Cohesion score 0.13438735177865613 - nodes in this community are weakly interconnected._
- **Should `test_bon.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12631578947368421 - nodes in this community are weakly interconnected._