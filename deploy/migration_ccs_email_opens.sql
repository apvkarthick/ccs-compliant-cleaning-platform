-- Run this in Supabase SQL Editor to create the email open tracking table.

CREATE TABLE IF NOT EXISTS ccs_email_opens (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_email TEXT     NOT NULL,
  contact_id  TEXT        NOT NULL DEFAULT '',
  opened_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  user_agent  TEXT        NOT NULL DEFAULT '',
  ip_address  TEXT        NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ccs_email_opens_email    ON ccs_email_opens (customer_email);
CREATE INDEX IF NOT EXISTS idx_ccs_email_opens_opened   ON ccs_email_opens (opened_at DESC);

-- Allow the service role to insert and select (RLS disabled by default for service role).
-- If RLS is enabled on this project, add a policy:
-- ALTER TABLE ccs_email_opens ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "service role full access" ON ccs_email_opens USING (true) WITH CHECK (true);
