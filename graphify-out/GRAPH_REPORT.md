# Graph Report - vorrat-assistent  (2026-09-29)

## Corpus Check
- 30 files · ~55,772 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 425 nodes · 877 edges · 14 communities (11 shown, 3 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 17 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Architektur und eBon-Zuordnung
- Nährwert-Regeln und Vorrat
- eBon lesen und Planer-Kandidaten
- BLS und Stückgewichte
- HTTP-Schnittstelle (FastAPI)
- Produktdetails übernehmen
- REWE-API-Zugriff
- Datenbank und Kategorien
- Crawler-Ablauf
- Crawler-Tests
- Datenquellen und Lizenzen
- Workflow-Export
- Workflow-Import
- Test-Parametrisierung

## God Nodes (most connected - your core abstractions)
1. `ermitteln()` - 21 edges
2. `speichern()` - 19 edges
3. `verbinden()` - 18 edges
4. `REWE-Dienst (rewerse, FastAPI)` - 14 edges
5. `details_uebernehmen()` - 14 edges
6. `Crawler` - 14 edges
7. `rewe_speichern()` - 14 edges
8. `Grocy (Bestand, MHD, Einkaufsliste)` - 13 edges
9. `normalisieren()` - 13 edges
10. `parse_naehrwerte()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Referenztabelle stueckgewichte` --semantically_similar_to--> `Standard-Stueckgewichte (app/stueckgewicht.py)`  [INFERRED] [semantically similar]
  README.md → rewe-service/daten/QUELLEN.md
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
- **eBon-Import zu Grocy mit REWE-Zuordnung** — readme_workflow_ebon_import, readme_bon_zuordnen, readme_bon_zuordnung_lerntabelle, readme_rewe_products_table, readme_grocy [EXTRACTED 1.00]
- **REWE-Crawl-Stack** — readme_workflow_rewe_crawl, readme_crawl, rewe_service_kategorien_kategorien, docker_rewe_compose_rewe_service, docker_rewe_compose_rewe_db, rewe_service_app_live_rewe_crawl_live [INFERRED 0.85]
- **Naehrwert-Ermittlung ueber Quellen-Rangfolge** — readme_naehrwerte_ermitteln_endpoint, readme_naehrwert_rangfolge, readme_openfoodfacts, readme_bls, readme_minimax_m3, readme_vorrat_naehrwerte_view [EXTRACTED 1.00]
- **Ist-Verbrauch erfassen, korrigieren und auswerten** — readme_workflow_08_verzehr_erfassen, readme_verzehr_protokoll, readme_verzehr_korrektur, readme_verzehr_auswertung, readme_workflow_09_nachtjob [EXTRACTED 1.00]
- **Referenzquellen fuer Standard-Stueckgewichte** — rewe_service_daten_quellen_standard_stueckgewichte, rewe_service_daten_quellen_usda_sr28, rewe_service_daten_quellen_vo_eg_589_2008, readme_stueckgewichte [EXTRACTED 1.00]

## Communities (14 total, 3 thin omitted)

### Community 0 - "Architektur und eBon-Zuordnung"
Cohesion: 0.05
Nodes (63): grocy Service (linuxserver/grocy), Docker-Netz n8n_default, rewe-db (postgres:17), rewe-service Container, Abholmarkt fuer Sortiment/Preise, POST /bon/zuordnen (eBon -> REWE-Produkte), Lerntabelle bon_zuordnung, REWE-Crawl (Liste, Details, Preisverlauf) (+55 more)

### Community 1 - "Nährwert-Regeln und Vorrat"
Cohesion: 0.06
Nodes (54): psycopg_rows, psycopg_types_json, abweichungen(), bereinigen(), gleich(), _log(), melden(), plausibel() (+46 more)

### Community 2 - "eBon lesen und Planer-Kandidaten"
Cohesion: 0.08
Nodes (50): date, datetime, Decimal, re, antwort_speichern(), bon_lesen(), ist_wasser(), _kassenwoerter() (+42 more)

### Community 3 - "BLS und Stückgewichte"
Cohesion: 0.06
Nodes (46): csv, gzip, logging, pathlib, pytest, eintrag(), _eintrag(), Bundeslebensmittelschlüssel (BLS) 4.0: Import und Suche. Quelle: Max Rubner-… (+38 more)

### Community 4 - "HTTP-Schnittstelle (FastAPI)"
Cohesion: 0.07
Nodes (48): contextlib, FastAPI, fastapi_responses, get, post, kategorien_config(), verbinden(), bls_suche() (+40 more)

### Community 5 - "Produktdetails übernehmen"
Cohesion: 0.08
Nodes (41): details_uebernehmen(), listen_produkt(), produkt_aktualisieren(), Fortsetzbarer Crawl der Lebensmittelkategorien eines REWE-Marktes. Phase…, Details eines Produkts sofort live holen und speichern (fehlt es in der…, Detailansicht eines Produkts übernehmen: Stammdaten + Nährwerte (REWE, sonst…, product_detail(), products_search() (+33 more)

### Community 6 - "REWE-API-Zugriff"
Cohesion: 0.09
Nodes (37): exception_handler, httpx, json, random, Response, nicht_bereit(), _angebote(), aufruf() (+29 more)

### Community 7 - "Datenbank und Kategorien"
Cohesion: 0.12
Nodes (19): Connection, os, psycopg, laden(), BLS-Tabelle aus der CSV füllen, wenn sie fehlt oder unvollständig ist., _alle_kategorien(), kategorien_aufloesen(), Config-Einträge (Namensteile oder Slugs) -> [{name, slug}] anhand der Shop-… (+11 more)

### Community 8 - "Crawler-Ablauf"
Cohesion: 0.18
Nodes (5): _Abbruch, Crawler, RuntimeError, Läufe, die beim letzten Beenden noch liefen, gelten als abgebrochen…, Reihenfolge: Vorratsprodukte (jeder Lauf), ohne Details (neu oder Name/Größe…

### Community 9 - "Crawler-Tests"
Cohesion: 0.25
Nodes (10): FakeRewe, laufen(), fixture, Crawler gegen eine nachgebaute REWE-API: Upsert, Preisverlauf, Details,…, test_details_aktuell_halten(), test_fortsetzen_nach_abbruch(), test_kompletter_lauf(), test_mini_crawl() (+2 more)

### Community 10 - "Datenquellen und Lizenzen"
Cohesion: 0.36
Nodes (8): Bundeslebensmittelschluessel (BLS) Tabelle bls, Referenztabelle stueckgewichte, Bundeslebensmittelschluessel BLS 4.0 (Max Rubner-Institut 2025), Lizenz CC BY 4.0, Datenquellen (QUELLEN.md), Standard-Stueckgewichte (app/stueckgewicht.py), USDA National Nutrient Database SR28 / SR Legacy, Verordnung (EG) Nr. 589/2008 (Eier-Gewichtsklassen)

## Knowledge Gaps
- **16 isolated node(s):** `import.sh script`, `Tailscale serve (Live-Seite im Tailnet)`, `05 Fehlermeldung`, `00 Grocy einrichten`, `04 MHD-Waechter` (+11 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 140 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Crawler` connect `Crawler-Ablauf` to `Crawler-Tests`, `HTTP-Schnittstelle (FastAPI)`, `Produktdetails übernehmen`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `ermitteln()` connect `BLS und Stückgewichte` to `Nährwert-Regeln und Vorrat`, `HTTP-Schnittstelle (FastAPI)`, `Produktdetails übernehmen`, `REWE-API-Zugriff`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `parse_naehrwerte()` connect `Produktdetails übernehmen` to `HTTP-Schnittstelle (FastAPI)`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `REWE-Dienst (rewerse, FastAPI)` (e.g. with `rewe-service Python-Abhaengigkeiten` and `laden() Polling (3 s)`) actually correct?**
  _`REWE-Dienst (rewerse, FastAPI)` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `import.sh script`, `Tailscale serve (Live-Seite im Tailnet)`, `05 Fehlermeldung` to the rest of the system?**
  _16 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Architektur und eBon-Zuordnung` be split into smaller, more focused modules?**
  _Cohesion score 0.05478750640040963 - nodes in this community are weakly interconnected._
- **Should `Nährwert-Regeln und Vorrat` be split into smaller, more focused modules?**
  _Cohesion score 0.060814383923849816 - nodes in this community are weakly interconnected._