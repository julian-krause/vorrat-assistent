# Graph Report - vorrat-assistent  (2026-09-29)

## Corpus Check
- Corpus is ~39,885 words - fits in a single context window. You may not need a graph.

## Summary
- 245 nodes · 474 edges · 12 communities (8 shown, 4 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 15 edges (avg confidence: 0.85)
- Token cost: 48,981 input · 0 output

## Community Hubs (Navigation)
- eBon-Zuordnung (bon.py)
- Architektur und Infrastruktur
- HTTP-Endpunkte (main.py)
- REWE-API-Zugriff (rewe.py)
- Parser Größe Nährwerte EAN
- Crawl-Konfiguration und Datenbank
- Crawler-Ablauf
- Crawler-Tests
- Verzehr-Test
- Workflow-Export
- Workflow-Import
- n8n Plattform

## God Nodes (most connected - your core abstractions)
1. `normalisieren()` - 13 edges
2. `Crawler` - 13 edges
3. `parse_naehrwerte()` - 11 edges
4. `ean_aus_article_id()` - 11 edges
5. `finde_ean()` - 11 edges
6. `REWE-Dienst (rewerse, FastAPI)` - 10 edges
7. `bon_lesen()` - 9 edges
8. `textwert()` - 9 edges
9. `verbinden()` - 9 edges
10. `parse_groesse()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `REWE-Dienst (rewerse, FastAPI)` --references--> `rewe-service Python-Abhaengigkeiten`  [INFERRED]
  README.md → rewe-service/requirements.txt
- `rewe-service Container` --references--> `mTLS-Zertifikate aus REWE-APK`  [INFERRED]
  docker/rewe.compose.yml → README.md
- `Grocy (Bestand, MHD, Einkaufsliste)` --references--> `grocy Service (linuxserver/grocy)`  [EXTRACTED]
  README.md → docker/grocy.compose.yml
- `laden() Polling (3 s)` --references--> `REWE-Dienst (rewerse, FastAPI)`  [INFERRED]
  rewe-service/app/live.html → README.md
- `rewe-service Python-Abhaengigkeiten` --references--> `rewerse (REWE-App-API-Bibliothek)`  [INFERRED]
  rewe-service/requirements.txt → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **eBon-Import zu Grocy mit REWE-Zuordnung** — readme_workflow_ebon_import, readme_bon_zuordnen, readme_bon_zuordnung_lerntabelle, readme_rewe_products_table, readme_grocy [EXTRACTED 1.00]
- **REWE-Crawl-Stack** — readme_workflow_rewe_crawl, readme_crawl, rewe_service_kategorien_kategorien, docker_rewe_compose_rewe_service, docker_rewe_compose_rewe_db, rewe_service_app_live_rewe_crawl_live [INFERRED 0.85]

## Communities (12 total, 4 thin omitted)

### Community 0 - "eBon-Zuordnung (bon.py)"
Cohesion: 0.09
Nodes (49): date, datetime, Decimal, antwort_speichern(), bon_lesen(), ist_wasser(), _kassenwoerter(), lernen() (+41 more)

### Community 1 - "Architektur und Infrastruktur"
Cohesion: 0.08
Nodes (38): grocy Service (linuxserver/grocy), Docker-Netz n8n_default, rewe-db (postgres:17), rewe-service Container, Abholmarkt fuer Sortiment/Preise, POST /bon/zuordnen (eBon -> REWE-Produkte), Lerntabelle bon_zuordnung, REWE-Crawl (Liste, Details, Preisverlauf) (+30 more)

### Community 2 - "HTTP-Endpunkte (main.py)"
Cohesion: 0.10
Nodes (34): contextlib, FastAPI, fastapi_responses, get, post, kategorien_config(), listen_produkt(), verbinden() (+26 more)

### Community 3 - "REWE-API-Zugriff (rewe.py)"
Cohesion: 0.11
Nodes (30): exception_handler, httpx, json, random, nicht_bereit(), _angebote(), aufruf(), client() (+22 more)

### Community 4 - "Parser Größe Nährwerte EAN"
Cohesion: 0.12
Nodes (26): parametrize, re, _bezug_100(), ean_aus_article_id(), finde_ean(), grundpreis(), gtin_gueltig(), parse_groesse() (+18 more)

### Community 5 - "Crawl-Konfiguration und Datenbank"
Cohesion: 0.10
Nodes (23): Connection, logging, os, pathlib, psycopg, psycopg_types_json, pytest, _alle_kategorien() (+15 more)

### Community 6 - "Crawler-Ablauf"
Cohesion: 0.21
Nodes (4): _Abbruch, Crawler, RuntimeError, Läufe, die beim letzten Beenden noch liefen, gelten als abgebrochen…

### Community 7 - "Crawler-Tests"
Cohesion: 0.26
Nodes (8): FakeRewe, laufen(), fixture, Crawler gegen eine nachgebaute REWE-API: Upsert, Preisverlauf, Details,…, test_fortsetzen_nach_abbruch(), test_kompletter_lauf(), test_mini_crawl(), umgebung()

## Knowledge Gaps
- **8 isolated node(s):** `export.sh script`, `import.sh script`, `n8n Workflow-Plattform`, `04 MHD-Waechter`, `05 Fehlermeldung` (+3 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 80 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Crawler` connect `Crawler-Ablauf` to `HTTP-Endpunkte (main.py)`, `Crawl-Konfiguration und Datenbank`, `Crawler-Tests`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `parse_naehrwerte()` connect `Parser Größe Nährwerte EAN` to `HTTP-Endpunkte (main.py)`, `Crawl-Konfiguration und Datenbank`, `Crawler-Ablauf`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `ean_aus_article_id()` connect `Parser Größe Nährwerte EAN` to `HTTP-Endpunkte (main.py)`, `Crawl-Konfiguration und Datenbank`, `Crawler-Ablauf`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **What connects `export.sh script`, `import.sh script`, `n8n Workflow-Plattform` to the rest of the system?**
  _8 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `eBon-Zuordnung (bon.py)` be split into smaller, more focused modules?**
  _Cohesion score 0.08521870286576169 - nodes in this community are weakly interconnected._
- **Should `Architektur und Infrastruktur` be split into smaller, more focused modules?**
  _Cohesion score 0.07965860597439545 - nodes in this community are weakly interconnected._
- **Should `HTTP-Endpunkte (main.py)` be split into smaller, more focused modules?**
  _Cohesion score 0.10252100840336134 - nodes in this community are weakly interconnected._