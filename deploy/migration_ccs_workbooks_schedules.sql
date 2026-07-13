-- Migration: workbook persistence + recurring distribution schedules
-- Run once against the Supabase project (afednjjvdzoawhgixvxh)

-- Persists the parsed workbook JSON per customer (upsert by customer_id on re-upload)
CREATE TABLE IF NOT EXISTS ccs_workbooks (
    customer_id   text PRIMARY KEY,
    customer_name text NOT NULL DEFAULT '',
    filename      text NOT NULL DEFAULT '',
    parsed_json   jsonb NOT NULL DEFAULT '{}',
    uploaded_at   timestamptz NOT NULL DEFAULT now()
);

-- Recurring distribution schedule per customer
CREATE TABLE IF NOT EXISTS ccs_schedules (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id          text UNIQUE NOT NULL,
    customer_name        text NOT NULL DEFAULT '',
    frequency            text NOT NULL DEFAULT 'weekly',   -- weekly | biweekly | monthly | custom
    custom_interval_days integer,
    next_send_at         timestamptz,
    last_sent_at         timestamptz,
    active               boolean NOT NULL DEFAULT true,
    dry_run              boolean NOT NULL DEFAULT true,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE ccs_workbooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE ccs_schedules  ENABLE ROW LEVEL SECURITY;
