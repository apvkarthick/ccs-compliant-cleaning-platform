-- Add pulled_files JSONB column to ccs_import_history
-- Stores the filename of each file processed during a SharePoint pull
ALTER TABLE ccs_import_history
  ADD COLUMN IF NOT EXISTS pulled_files JSONB;
