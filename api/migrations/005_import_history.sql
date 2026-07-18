-- Migration 005: Import history log
-- Records each mapping import event for the Data Management page

CREATE TABLE IF NOT EXISTS ccs_import_history (
    id          BIGSERIAL PRIMARY KEY,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sites_count INT         NOT NULL DEFAULT 0,
    sds_links_count INT     NOT NULL DEFAULT 0,
    groups_count INT        NOT NULL DEFAULT 0,
    register_count INT      NOT NULL DEFAULT 0
);
