-- Document Library: maps client-provided raw PDFs to products by code/name.
-- Separate from the existing workbook flow (which uses client-supplied public URLs).
-- Files stored in DO Spaces simplyrun-media under ccs/{YYYY-MM-DD}/ prefix.
-- Re-ingesting never overwrites old files; old distribution URLs stay valid forever.

CREATE TABLE IF NOT EXISTS ccs_document_library (
    product_code          text PRIMARY KEY,
    product_name          text NOT NULL DEFAULT '',
    -- Current SDS version
    sds_filename          text,
    sds_url               text,
    sds_version           integer NOT NULL DEFAULT 1,
    sds_uploaded_at       timestamptz,
    sds_url_previous      text,
    -- Current Risk Assessment version
    risk_filename         text,
    risk_url              text,
    risk_version          integer NOT NULL DEFAULT 1,
    risk_uploaded_at      timestamptz,
    risk_url_previous     text,
    -- Metadata
    match_method          text NOT NULL DEFAULT 'code',  -- 'code' | 'name' | 'manual'
    customer_id           text,
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ccs_document_versions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code    text NOT NULL,
    document_type   text NOT NULL,   -- 'sds' | 'risk'
    version         integer NOT NULL,
    filename        text NOT NULL,
    url             text NOT NULL,
    ingest_batch    text,            -- YYYY-MM-DD of the ingest run
    uploaded_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ccs_document_versions_code_type
    ON ccs_document_versions (product_code, document_type);

ALTER TABLE ccs_document_library ENABLE ROW LEVEL SECURITY;
ALTER TABLE ccs_document_versions ENABLE ROW LEVEL SECURITY;
