-- Site distribution tables
-- Run in Supabase dashboard: SQL Editor → paste and execute

CREATE TABLE IF NOT EXISTS ccs_site_mapping (
  accno      TEXT PRIMARY KEY,
  ho_accno   TEXT,
  ho_name    TEXT,
  name       TEXT NOT NULL,
  emails     TEXT[] NOT NULL DEFAULT '{}',
  stockcodes TEXT[] NOT NULL DEFAULT '{}',
  imported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ccs_sds_links (
  stock_code  TEXT PRIMARY KEY,
  sds_url     TEXT,
  risk_url    TEXT,
  imported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ccs_stock_groups (
  primary_code  TEXT PRIMARY KEY,
  related_codes TEXT[] NOT NULL DEFAULT '{}',
  imported_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ccs_site_exclusions (
  accno       TEXT PRIMARY KEY,
  name        TEXT,
  excluded_at TIMESTAMPTZ DEFAULT NOW()
);
