-- Schema der REWE-Produktdatenbank. Wird beim Start des Dienstes idempotent ausgeführt.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS rewe_products (
    rewe_product_id    text PRIMARY KEY,
    article_id         text,
    name               text NOT NULL,
    brand              text,
    description        text,
    category           text,
    size_value         numeric(12, 3),
    size_unit          text CHECK (size_unit IN ('g', 'ml', 'Stück')),
    grammage_raw       text,
    price              numeric(10, 2),
    price_per_kg_or_l  numeric(10, 2),
    angebotspreis      numeric(10, 2),
    angebot_bis        date,
    ean                text,
    kcal_100           numeric(7, 1),
    protein_100        numeric(6, 1),
    kh_100             numeric(6, 1),
    fett_100           numeric(6, 1),
    naehrwerte_quelle  text,
    is_organic         boolean,
    is_vegan           boolean,
    is_vegetarian      boolean,
    details_fetched_at timestamptz,
    first_seen         timestamptz NOT NULL DEFAULT now(),
    last_seen          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rewe_products_suche_idx
    ON rewe_products USING gin ((name || ' ' || coalesce(brand, '')) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS rewe_products_ohne_details_idx
    ON rewe_products (first_seen) WHERE details_fetched_at IS NULL;
CREATE INDEX IF NOT EXISTS rewe_products_details_alter_idx ON rewe_products (details_fetched_at);

ALTER TABLE rewe_products
    ADD COLUMN IF NOT EXISTS zucker_100 numeric(6, 1),
    ADD COLUMN IF NOT EXISTS ballaststoffe_100 numeric(6, 1),
    ADD COLUMN IF NOT EXISTS salz_100 numeric(6, 2),
    ADD COLUMN IF NOT EXISTS naehrwert_verlauf_id bigint;

-- Jede tatsächliche Änderung der Nährwerte eines REWE-Produkts; rewe_products hält den aktuellen Stand
-- (naehrwert_verlauf_id zeigt auf die gültige Zeile). name/grammage_raw: Stand bei der Änderung, für die 20-%-Prüfung.
CREATE TABLE IF NOT EXISTS rewe_naehrwert_verlauf (
    id                bigserial PRIMARY KEY,
    rewe_product_id   text NOT NULL REFERENCES rewe_products (rewe_product_id),
    kcal_100          numeric(7, 1),
    protein_100       numeric(6, 1),
    kh_100            numeric(6, 1),
    fett_100          numeric(6, 1),
    zucker_100        numeric(6, 1),
    ballaststoffe_100 numeric(6, 1),
    salz_100          numeric(6, 2),
    quelle            text,                -- rewe | openfoodfacts
    ean               text,
    marke             text,
    name              text,
    grammage_raw      text,
    gueltig_ab        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rewe_naehrwert_verlauf_produkt_idx ON rewe_naehrwert_verlauf (rewe_product_id, gueltig_ab);

-- Bestand vor Einführung des Verlaufs: je Produkt mit Nährwerten eine Startzeile
WITH neu AS (
    INSERT INTO rewe_naehrwert_verlauf (rewe_product_id, kcal_100, protein_100, kh_100, fett_100, quelle, ean, marke, name,
                                        grammage_raw, gueltig_ab)
    SELECT rewe_product_id, kcal_100, protein_100, kh_100, fett_100, naehrwerte_quelle, ean, brand, name, grammage_raw,
           coalesce(details_fetched_at, first_seen)
    FROM rewe_products WHERE kcal_100 IS NOT NULL AND naehrwert_verlauf_id IS NULL
    RETURNING id, rewe_product_id
)
UPDATE rewe_products p SET naehrwert_verlauf_id = neu.id FROM neu WHERE p.rewe_product_id = neu.rewe_product_id;

-- Hinweise für den nächtlichen Telegram-Versand (Abweichungen > 20 %, unplausible Werte, Fehler der Nachtjobs)
CREATE TABLE IF NOT EXISTS meldungen (
    id          bigserial PRIMARY KEY,
    art         text NOT NULL,
    text        text NOT NULL,
    daten       jsonb,
    erstellt_at timestamptz NOT NULL DEFAULT now(),
    gesendet_at timestamptz
);
CREATE INDEX IF NOT EXISTS meldungen_offen_idx ON meldungen (erstellt_at) WHERE gesendet_at IS NULL;

-- Plausibilität wie app/naehrwerte.py: kcal ≈ 4·P + 4·KH + 9·F (+ 2·Ballaststoffe) ±15 % (mind. 5 kcal), P + F + KH ≤ 100 g
CREATE OR REPLACE FUNCTION naehrwerte_plausibel(kcal numeric, protein numeric, fett numeric, kh numeric,
                                                ballaststoffe numeric DEFAULT NULL)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT kcal IS NOT NULL AND protein IS NOT NULL AND fett IS NOT NULL AND kh IS NOT NULL
       AND least(kcal, protein, fett, kh) >= 0
       AND protein + fett + kh <= 100.5
       AND abs(kcal - (4 * protein + 4 * kh + 9 * fett + 2 * coalesce(ballaststoffe, 0)))
           <= greatest(0.15 * (4 * protein + 4 * kh + 9 * fett + 2 * coalesce(ballaststoffe, 0)), 5);
$$;

CREATE TABLE IF NOT EXISTS rewe_price_history (
    id              bigserial PRIMARY KEY,
    rewe_product_id text NOT NULL REFERENCES rewe_products (rewe_product_id),
    price           numeric(10, 2) NOT NULL,
    crawled_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rewe_price_history_produkt_idx ON rewe_price_history (rewe_product_id, crawled_at);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id          serial PRIMARY KEY,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text NOT NULL,          -- laeuft | abgebrochen | fertig | fehler
    params      jsonb NOT NULL,
    cursor      jsonb NOT NULL DEFAULT '{}'::jsonb,
    stats       jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS crawl_log (
    id         bigserial PRIMARY KEY,
    run_id     integer REFERENCES crawl_runs (id),
    level      text NOT NULL,
    message    text NOT NULL,
    payload    jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Suche für den n8n-Agenten: alle Wörter müssen in Name oder Marke vorkommen,
-- sortiert nach Ähnlichkeit, dann nach effektivem Preis.
CREATE OR REPLACE FUNCTION produkt_suche(suchbegriff text, max_treffer integer DEFAULT 12)
RETURNS TABLE (
    rewe_product_id text, name text, brand text, category text,
    size_value numeric, size_unit text, price numeric, price_per_kg_or_l numeric,
    angebotspreis numeric, angebot_bis date, preis_aktuell numeric,
    kcal_100 numeric, protein_100 numeric, kh_100 numeric, fett_100 numeric,
    preis_pro_100g_protein numeric, ean text, last_seen date
) LANGUAGE sql STABLE AS $$
    SELECT p.rewe_product_id, p.name, p.brand, p.category, p.size_value, p.size_unit, p.price, p.price_per_kg_or_l,
           CASE WHEN p.angebot_bis >= current_date THEN p.angebotspreis END,
           CASE WHEN p.angebot_bis >= current_date THEN p.angebot_bis END,
           CASE WHEN p.angebot_bis >= current_date AND p.angebotspreis IS NOT NULL THEN p.angebotspreis ELSE p.price END,
           p.kcal_100, p.protein_100, p.kh_100, p.fett_100,
           CASE WHEN p.protein_100 > 0 AND p.size_unit IN ('g', 'ml') AND p.size_value > 0
                THEN round((CASE WHEN p.angebot_bis >= current_date AND p.angebotspreis IS NOT NULL THEN p.angebotspreis ELSE p.price END)
                           / (p.size_value * p.protein_100 / 100) * 100, 2) END,
           p.ean, p.last_seen::date
    FROM rewe_products p
    WHERE NOT EXISTS (
        SELECT 1 FROM unnest(string_to_array(lower(trim(suchbegriff)), ' ')) AS w
        WHERE w <> '' AND lower(p.name || ' ' || coalesce(p.brand, '')) NOT LIKE '%' || w || '%'
    )
    ORDER BY similarity(p.name || ' ' || coalesce(p.brand, ''), suchbegriff) DESC,
             CASE WHEN p.angebot_bis >= current_date AND p.angebotspreis IS NOT NULL THEN p.angebotspreis ELSE p.price END
    LIMIT max_treffer;
$$;

-- eBon-Zuordnung: gelernte Kassentexte und die einzelnen Bonzeilen (für Rückfragen per Telegram)
CREATE TABLE IF NOT EXISTS bon_zuordnung (
    bon_text_norm   text PRIMARY KEY,
    bon_text        text NOT NULL,
    rewe_product_id text NOT NULL REFERENCES rewe_products (rewe_product_id),
    bestaetigt      boolean NOT NULL DEFAULT false,   -- true = vom Nutzer bestätigt, wird nie automatisch überschrieben
    anzahl          integer NOT NULL DEFAULT 1,
    zuletzt         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bon_zeilen (
    id              serial PRIMARY KEY,
    bon_id          text NOT NULL,
    kaufdatum       date NOT NULL,
    bon_text        text NOT NULL,
    bon_text_norm   text NOT NULL,
    anzahl          integer,
    einzelpreis     numeric(10, 2),
    gewicht_kg      numeric(8, 3),
    kilopreis       numeric(10, 2),
    status          text NOT NULL,              -- sicher | unsicher | keine | bestaetigt | keins
    rewe_product_id text,
    kandidaten      jsonb,
    erstellt_at     timestamptz NOT NULL DEFAULT now(),
    beantwortet_at  timestamptz,
    UNIQUE (bon_id, bon_text_norm)
);

-- Ist-Verbrauch: was tatsächlich gegessen wurde, mit Zeitstempel und festgeschriebenen Nährwerten.
-- quelle: grocy (Verbrauchsbuchung aus dem Vorrat, per n8n-Abgleich) | rezept (Zutaten eines gekochten Rezepts,
-- die nicht aus dem Vorrat kamen) | manuell (vom Agenten eingetragen, z.B. auswärts gegessen)
CREATE TABLE IF NOT EXISTS verzehr (
    id               bigserial PRIMARY KEY,
    zeitpunkt        timestamptz NOT NULL,
    quelle           text NOT NULL CHECK (quelle IN ('grocy', 'rezept', 'manuell')),
    grocy_log_id     integer UNIQUE,
    grocy_product_id integer,
    rezept_id        integer,
    name             text NOT NULL,
    menge            numeric(10, 2),
    einheit          text,
    gramm            numeric(10, 1),
    kcal             numeric(8, 1),
    protein          numeric(7, 1),
    fett             numeric(7, 1),
    kh               numeric(7, 1),
    geschaetzt       boolean NOT NULL DEFAULT false,
    ignoriert        boolean NOT NULL DEFAULT false,  -- vom Nutzer korrigiert; bleibt stehen, damit der Abgleich es nicht neu anlegt
    notiz            text,
    erfasst_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS verzehr_zeitpunkt_idx ON verzehr (zeitpunkt);

-- Summe und Durchschnitt pro Kalendertag (Europe/Berlin). Liegt „bis“ in der Zukunft, zählt nur bis heute.
CREATE OR REPLACE FUNCTION verzehr_auswertung(von date, bis date) RETURNS jsonb LANGUAGE sql STABLE AS $$
    WITH g AS (
        SELECT von AS v, LEAST(bis, (now() AT TIME ZONE 'Europe/Berlin')::date) AS b
    ), e AS (
        SELECT x.*, (x.zeitpunkt AT TIME ZONE 'Europe/Berlin')::date AS tag
        FROM verzehr x, g WHERE NOT x.ignoriert AND (x.zeitpunkt AT TIME ZONE 'Europe/Berlin')::date BETWEEN g.v AND g.b
    ), s AS (
        SELECT coalesce(sum(kcal), 0) AS kcal, coalesce(sum(protein), 0) AS p, coalesce(sum(fett), 0) AS f, coalesce(sum(kh), 0) AS kh,
               count(*) AS n, count(DISTINCT tag) AS tage_mit, coalesce(sum(kcal) FILTER (WHERE geschaetzt), 0) AS kcal_geschaetzt,
               count(*) FILTER (WHERE kcal IS NULL) AS ohne_nw
        FROM e
    ), t AS (SELECT GREATEST(g.b - g.v + 1, 0) AS tage FROM g)
    SELECT jsonb_build_object(
        'von', g.v, 'bis', g.b, 'kalendertage', t.tage, 'tage_mit_eintraegen', s.tage_mit, 'eintraege', s.n,
        'summe', jsonb_build_object('kcal', round(s.kcal), 'protein_g', round(s.p), 'fett_g', round(s.f), 'kh_g', round(s.kh)),
        'durchschnitt_pro_kalendertag', CASE WHEN t.tage > 0 THEN jsonb_build_object(
            'kcal', round(s.kcal / t.tage), 'protein_g', round(s.p / t.tage), 'fett_g', round(s.f / t.tage), 'kh_g', round(s.kh / t.tage)) END,
        'durchschnitt_pro_tag_mit_eintraegen', CASE WHEN s.tage_mit > 0 THEN jsonb_build_object(
            'kcal', round(s.kcal / s.tage_mit), 'protein_g', round(s.p / s.tage_mit), 'fett_g', round(s.f / s.tage_mit), 'kh_g', round(s.kh / s.tage_mit)) END,
        'anteil_geschaetzt_prozent', CASE WHEN s.kcal > 0 THEN round(100 * s.kcal_geschaetzt / s.kcal) END,
        'eintraege_ohne_naehrwerte', s.ohne_nw,
        'top_lebensmittel', (SELECT coalesce(jsonb_agg(x), '[]'::jsonb) FROM (
            SELECT name, round(sum(kcal)) AS kcal, round(sum(protein)) AS protein_g, count(*) AS mal
            FROM e GROUP BY name ORDER BY sum(kcal) DESC NULLS LAST LIMIT 8) x)
    ) FROM g, s, t;
$$;

-- Vorratsprodukte (ein Eintrag je Grocy-Produkt): Verknüpfung zu REWE und eigene Werte.
-- Eigene Nährwerte nur für Produkte ohne REWE-Werte oder für Korrekturen durch den Nutzer; die View
-- vorrat_naehrwerte liefert pro Produkt den besten Wert. Schreiben nur über den rewe-service (Rangregel).
CREATE TABLE IF NOT EXISTS vorrat_produkte (
    grocy_product_id  integer PRIMARY KEY,
    name              text NOT NULL,
    einheit           text NOT NULL DEFAULT 'g' CHECK (einheit IN ('g', 'ml', 'stk')),
    kategorie         text,
    rewe_product_id   text REFERENCES rewe_products (rewe_product_id),
    ean               text,
    kcal_100          numeric(7, 1),
    protein_100       numeric(6, 1),
    fett_100          numeric(6, 1),
    kh_100            numeric(6, 1),
    zucker_100        numeric(6, 1),
    ballaststoffe_100 numeric(6, 1),
    salz_100          numeric(6, 2),
    naehrwert_quelle  text CHECK (naehrwert_quelle IN ('manuell', 'rewe', 'off_barcode', 'off_name', 'bls', 'ki')),
    naehrwert_rang    smallint CHECK (naehrwert_rang BETWEEN 1 AND 6),
    naehrwert_stand   timestamptz,
    naehrwert_detail  text,             -- z.B. OFF-Code, BLS-Code, „Etikett-Foto“
    gramm_pro_stk     numeric(7, 1) CHECK (gramm_pro_stk > 0),   -- essbarer Anteil eines Stücks
    gramm_quelle      text CHECK (gramm_quelle IN ('manuell', 'packung', 'referenz', 'ki')),
    gramm_rang        smallint CHECK (gramm_rang BETWEEN 1 AND 4),
    gramm_detail      text,
    nutriscore        text,
    nova              smallint,
    erstellt_at       timestamptz NOT NULL DEFAULT now(),
    aktualisiert_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS vorrat_produkte_rewe_idx ON vorrat_produkte (rewe_product_id);

-- Bester Nährwert je Vorratsprodukt: kleinster Rang aus eigenem Wert und REWE-Produkt (REWE nur, wenn plausibel);
-- bei gleichem Rang gewinnt das REWE-Produkt. Zahlen als float8, damit n8n echte Zahlen bekommt.
DROP VIEW IF EXISTS vorrat_naehrwerte CASCADE;
CREATE VIEW vorrat_naehrwerte AS
SELECT v.grocy_product_id, v.name, v.einheit, v.kategorie, v.rewe_product_id, coalesce(v.ean, r.ean) AS ean,
       b.kcal_100::float8 AS kcal_100, b.protein_100::float8 AS protein_100, b.fett_100::float8 AS fett_100,
       b.kh_100::float8 AS kh_100, b.zucker_100::float8 AS zucker_100, b.ballaststoffe_100::float8 AS ballaststoffe_100,
       b.salz_100::float8 AS salz_100,
       b.quelle AS naehrwert_quelle, b.rang AS naehrwert_rang, b.verlauf_id AS naehrwert_verlauf_id, b.stand AS naehrwert_stand,
       v.gramm_pro_stk::float8 AS gramm_pro_stk, v.gramm_quelle, v.gramm_rang,
       (b.rang IS NULL OR b.rang >= 5 OR (v.einheit = 'stk' AND coalesce(v.gramm_rang, 4) >= 4)) AS geschaetzt,
       CASE WHEN v.einheit = 'stk' THEN round(b.kcal_100 * v.gramm_pro_stk / 100, 1)::float8
            ELSE round(b.kcal_100 / 100, 4)::float8 END AS kcal_pro_einheit,
       v.nutriscore, v.nova, r.name AS rewe_name, r.brand AS rewe_marke
FROM vorrat_produkte v
LEFT JOIN rewe_products r ON r.rewe_product_id = v.rewe_product_id
LEFT JOIN LATERAL (
    SELECT x.* FROM (VALUES
        (v.kcal_100, v.protein_100, v.fett_100, v.kh_100, v.zucker_100, v.ballaststoffe_100, v.salz_100,
         v.naehrwert_quelle, v.naehrwert_rang::integer, NULL::bigint, v.naehrwert_stand),
        (r.kcal_100, r.protein_100, r.fett_100, r.kh_100, r.zucker_100, r.ballaststoffe_100, r.salz_100,
         CASE r.naehrwerte_quelle WHEN 'rewe' THEN 'rewe' WHEN 'openfoodfacts' THEN 'off_barcode' END,
         CASE r.naehrwerte_quelle WHEN 'rewe' THEN 2 WHEN 'openfoodfacts' THEN 3 END,
         r.naehrwert_verlauf_id, r.details_fetched_at)
    ) x(kcal_100, protein_100, fett_100, kh_100, zucker_100, ballaststoffe_100, salz_100, quelle, rang, verlauf_id, stand)
    WHERE x.kcal_100 IS NOT NULL AND x.rang IS NOT NULL
      AND (x.verlauf_id IS NULL OR naehrwerte_plausibel(x.kcal_100, x.protein_100, x.fett_100, x.kh_100, x.ballaststoffe_100))
    ORDER BY x.rang, x.verlauf_id IS NULL
    LIMIT 1
) b ON true;

-- Open-Food-Facts-Anfragen, die am Anfrage-Limit gescheitert sind; der Nachtjob versucht sie erneut
CREATE TABLE IF NOT EXISTS off_warteschlange (
    id               bigserial PRIMARY KEY,
    grocy_product_id integer NOT NULL,
    art              text NOT NULL CHECK (art IN ('barcode', 'name')),
    anfrage          jsonb NOT NULL,           -- Eingabe für ermitteln()
    versuche         integer NOT NULL DEFAULT 0,
    letzter_fehler   text,
    erstellt_at      timestamptz NOT NULL DEFAULT now(),
    erledigt_at      timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS off_warteschlange_offen_idx ON off_warteschlange (grocy_product_id, art) WHERE erledigt_at IS NULL;
