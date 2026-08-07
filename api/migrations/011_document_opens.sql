-- Track PDF/document clicks per site contact
CREATE TABLE IF NOT EXISTS ccs_document_opens (
  id           BIGSERIAL PRIMARY KEY,
  contact_id   TEXT NOT NULL,         -- accno
  customer_email TEXT NOT NULL,
  document_id  TEXT NOT NULL,         -- site_{accno}_{code}_{sds|risk_assessment}
  stock_code   TEXT NOT NULL DEFAULT '',
  doc_type     TEXT NOT NULL DEFAULT '', -- 'sds' or 'risk_assessment'
  opened_at    TIMESTAMPTZ DEFAULT NOW(),
  batch_id     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_document_opens_contact   ON ccs_document_opens(contact_id);
CREATE INDEX IF NOT EXISTS idx_document_opens_batch     ON ccs_document_opens(batch_id);
CREATE INDEX IF NOT EXISTS idx_document_opens_opened_at ON ccs_document_opens(opened_at DESC);
