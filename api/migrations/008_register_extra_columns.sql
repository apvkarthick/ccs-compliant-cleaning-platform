-- Migration 008: Add extra Chemical Register columns missing from 004
-- maximum_qty, hazchem, chemical_class, packing_group were parsed but never stored

ALTER TABLE ccs_sds_links
  ADD COLUMN IF NOT EXISTS maximum_qty TEXT,
  ADD COLUMN IF NOT EXISTS hazchem TEXT,
  ADD COLUMN IF NOT EXISTS chemical_class TEXT,
  ADD COLUMN IF NOT EXISTS packing_group TEXT;
