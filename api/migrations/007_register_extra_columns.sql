-- Migration 007: add extra columns to ccs_sds_links for full A-K Chemical Register output
ALTER TABLE ccs_sds_links
  ADD COLUMN IF NOT EXISTS maximum_qty TEXT,
  ADD COLUMN IF NOT EXISTS hazchem TEXT,
  ADD COLUMN IF NOT EXISTS chemical_class TEXT,
  ADD COLUMN IF NOT EXISTS packing_group TEXT;
