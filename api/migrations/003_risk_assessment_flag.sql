-- Phase 1: Risk assessment required flag per product
-- Run in Supabase dashboard: SQL Editor → paste and execute

-- Flag controls whether risk assessment PDF is included in site emails
ALTER TABLE ccs_sds_links ADD COLUMN IF NOT EXISTS risk_assessment_required BOOLEAN DEFAULT FALSE;
