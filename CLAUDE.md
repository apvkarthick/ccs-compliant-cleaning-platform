# CCS Compliant Cleaning Platform — Claude Rules

## Obsidian Updates
After every session where something substantial is built or learned, append a dated entry to:
`E:\obsidian\myobsidian\Projects\Compliant Cleaning Project.md`

Include: what was built, key decisions, URLs, open items. Do this automatically at the end of each turn.

## Stack
- **Backend:** FastAPI (`api/`) — Python 3, no ORM, direct Supabase REST API calls
- **Frontend:** React 19 + Vite (`frontend/src/main.jsx`) — single file SPA, no React Router
- **Database:** Supabase (PostgreSQL) — project `afednjjvdzoawhgixvxh`, region `ap-southeast-2`
- **Email:** GoHighLevel API (`GHL_EMAIL_ENDPOINT`)
- **Hosting:** DigitalOcean droplet 209.38.93.174, served at `https://ccs.nxai.com.au`
- **Proxy:** nginx — config at `deploy/nginx-ccs.conf`

## URLs
- Production: `https://ccs.nxai.com.au`
- Distribution tab: `https://ccs.nxai.com.au/app`
- Email Opens dashboard: `https://ccs.nxai.com.au/email-opens`
- Rebrand (legacy HTML): `https://ccs.nxai.com.au/rebrand`

## Supabase Tables
- `ccs_documents` — SDS document stubs (UUID, product_code, chemical_name, branded_url)
- `ccs_distributions` — per-document send log (document_id FK, customer_email, ghl_contact_id, status, downloaded_at)
- `ccs_email_opens` — email open events (customer_email, contact_id, opened_at, user_agent, ip_address)

## Tracking
- Download tracking: `GET /api/ccs-msds-track` — HMAC-signed, records to `ccs_distributions`
- Email open tracking: `GET /api/ccs-email-open` — HMAC-signed pixel, records to `ccs_email_opens`
- Both use `CCS_TRACKING_HMAC_SECRET` env var; email open sig prefixed with `"open:"` to avoid collision

## Key Env Vars
`CCS_PUBLIC_BASE_URL`, `CCS_TRACKING_HMAC_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_JWT_SECRET`, `GHL_ACCESS_TOKEN`, `GHL_LOCATION_ID`, `GHL_EMAIL_ENDPOINT`

## Deploy
Deployment is fully automated via GitHub Actions. Pushing to `main` triggers the pipeline — no manual SSH, build, or restart steps needed.

**Workflow:** commit changes → get user approval → `git push origin main` → GitHub Actions deploys automatically.

IMPORTANT: Always get explicit user approval before running `git push`. Never push without the user saying to.
