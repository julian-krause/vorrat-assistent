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
