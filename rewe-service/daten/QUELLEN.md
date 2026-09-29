# Datenquellen

## Bundeslebensmittelschlüssel (`bls_4_0.csv.gz`)

Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 — Deutsche Nährstoffdatenbank. Karlsruhe.
DOI: [10.25826/Data20251217-134202-0](https://doi.org/10.25826/Data20251217-134202-0) · Download: https://blsdb.de/download
Lizenz: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de).

Änderungen: Aus `BLS_4_0_Daten_2025_DE.xlsx` wurden nur Code, Bezeichnung (de/en) und je 100 g Energie (kcal, ENERCC),
Protein (PROT625), Fett (FAT), Kohlenhydrate verfügbar (CHO), Zucker (SUGAR), Ballaststoffe (FIBT) und Salz (NACL)
übernommen. Werte unter der Nachweis-/Bestimmungsgrenze („<LOD“, „<LOQ“) sind als 0 gespeichert, „TR“ und „-“ als leer.

## Standard-Stückgewichte (`app/stueckgewicht.py`, Tabelle `stueckgewichte`)

- Obst und Gemüse: U.S. Department of Agriculture, Agricultural Research Service. USDA National Nutrient Database for
  Standard Reference, Release 28 / SR Legacy (FoodData Central). Stückgewicht = essbarer Anteil der jeweiligen
  Portionsangabe (FOOD_PORTION), Anteil essbar = 100 % − Abfall (FOOD_DES, Feld „Refuse“). NDB-Nummer je Zeile.
- Eier: Gewichtsklassen nach Verordnung (EG) Nr. 589/2008 (S < 53 g, M 53–63 g, L 63–73 g, XL ≥ 73 g; Klassenmitte,
  XL mit 76 g angenommen), essbarer Anteil 88 % (USDA SR28 NDB 01123, 12 % Schale).
