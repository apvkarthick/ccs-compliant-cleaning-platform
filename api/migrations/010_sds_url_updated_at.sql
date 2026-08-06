-- Track when SDS/Risk URLs change so the Updated SDS Alert can auto-suggest recently updated products
ALTER TABLE ccs_sds_links
  ADD COLUMN IF NOT EXISTS sds_url_updated_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS risk_url_updated_at TIMESTAMPTZ;
