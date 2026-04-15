#!/usr/bin/env bash
# Create test schema + table with assorted types incl. arrays.
set -euo pipefail

NAME="aide-crawler-target-pg14"

docker exec -i "${NAME}" psql -U crawler -d target <<'SQL'
DROP SCHEMA IF EXISTS demo CASCADE;
CREATE SCHEMA demo;

CREATE TABLE demo.products (
    id              bigserial PRIMARY KEY,
    sku             varchar(64) NOT NULL UNIQUE,
    name            text NOT NULL,
    price           numeric(12, 2) NOT NULL,
    in_stock        boolean NOT NULL DEFAULT true,
    weight_kg       double precision,
    tags            text[] NOT NULL DEFAULT '{}',
    dimensions_cm   integer[],
    metadata        jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_on      date
);

CREATE INDEX ix_products_name ON demo.products (name);

CREATE TABLE demo.orders (
    id          bigserial PRIMARY KEY,
    product_id  bigint NOT NULL REFERENCES demo.products(id),
    qty         integer NOT NULL,
    notes       text
);

INSERT INTO demo.products (sku, name, price, tags, dimensions_cm, metadata)
VALUES
  ('SKU-1', 'Widget', 9.99, ARRAY['new','sale'], ARRAY[10,20,5], '{"color":"red"}'),
  ('SKU-2', 'Gadget', 19.50, ARRAY['popular'],   ARRAY[15,15,8], '{"color":"blue"}');

CREATE TABLE demo.types_zoo (
    id              bigserial PRIMARY KEY,
    code_char       char(8),
    bits_fixed      bit(8),
    bits_varying    bit varying(16),
    money_amount    money,
    macaddr8_addr   macaddr8,
    text_search     tsvector,
    text_query      tsquery,
    int4_window     int4range,
    int8_window     int8range,
    num_window      numrange,
    ts_window       tsrange,
    tstz_window     tstzrange,
    date_window     daterange,
    ts_with_tz      timestamptz,
    time_with_tz    timetz,
    nested_array    integer[]
);

\dt demo.*
SQL

echo "Seeded schema 'demo' with tables: products, orders."
