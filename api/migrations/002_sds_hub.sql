-- Phase 1: Hold status, SDS expiry date, product history
-- Run in Supabase dashboard: SQL Editor → paste and execute

-- Soft-pause table (temporary hold, separate from permanent exclusions)
CREATE TABLE IF NOT EXISTS ccs_site_holds (
  accno     TEXT PRIMARY KEY,
  name      TEXT,
  held_at   TIMESTAMPTZ DEFAULT NOW()
);

-- SDS expiry date per product (for 1-month expiry alerts)
ALTER TABLE ccs_sds_links ADD COLUMN IF NOT EXISTS sds_expiry DATE;

-- Track when each product first appeared per site (for new-product audit)
CREATE TABLE IF NOT EXISTS ccs_site_product_history (
  id            BIGSERIAL PRIMARY KEY,
  accno         TEXT NOT NULL,
  stock_code    TEXT NOT NULL,
  first_seen_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(accno, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_site_product_history_accno
  ON ccs_site_product_history(accno);
