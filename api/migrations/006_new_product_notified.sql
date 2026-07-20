-- Migration 006: Track when new-product queue entries are actioned (sent)
-- notified_at NULL = pending CCS team action; set when email is sent

ALTER TABLE ccs_site_product_history
  ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
