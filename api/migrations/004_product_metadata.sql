-- Migration 004: Store product metadata from Chemical Register Title Sheet
-- Enables per-site Chemical Register Excel generation at send time

ALTER TABLE ccs_sds_links
  ADD COLUMN IF NOT EXISTS product_name TEXT,
  ADD COLUMN IF NOT EXISTS hazard_classification TEXT,
  ADD COLUMN IF NOT EXISTS primary_use TEXT,
  ADD COLUMN IF NOT EXISTS signal_word TEXT,
  ADD COLUMN IF NOT EXISTS un_number TEXT;
