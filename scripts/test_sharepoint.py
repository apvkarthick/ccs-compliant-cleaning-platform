"""
SharePoint / Microsoft Graph connectivity test for CCS platform.

Reads credentials from E:\\claude\\myenv.env (CCS_SP_* vars).
Run: python scripts/test_sharepoint.py

Tests (in order):
  1. OAuth2 token via client credentials
  2. Token roles / permissions
  3. List SharePoint sites (needs Sites.Read.All)
  4. Search for Onepoint site / Chemical Register folder
  5. List files in target folder (needs Files.Read.All)
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import base64


# ── Load env ──────────────────────────────────────────────────────────────────

def _load_env(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


_load_env(r"E:\claude\myenv.env")

TENANT_ID     = os.environ.get("CCS_SP_TENANT_ID", "")
CLIENT_ID     = os.environ.get("CCS_SP_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CCS_SP_CLIENT_SECRET", "")

if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
    sys.exit("Missing CCS_SP_TENANT_ID / CCS_SP_CLIENT_ID / CCS_SP_CLIENT_SECRET in myenv.env")

GRAPH = "https://graph.microsoft.com/v1.0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _graph(token: str, path: str) -> dict:
    url = f"{GRAPH}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"_http_error": e.code, "_body": body}


def _decode_token_roles(token: str) -> list[str]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("roles", [])
    except Exception:
        return []


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    print(f"  [INFO] {msg}")


# ── Step 1: Get token ─────────────────────────────────────────────────────────

print("\n=== 1. OAuth2 token (client credentials) ===")
token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
body = urllib.parse.urlencode({
    "grant_type":    "client_credentials",
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scope":         "https://graph.microsoft.com/.default",
}).encode()

try:
    with urllib.request.urlopen(urllib.request.Request(token_url, data=body), timeout=15) as r:
        token_data = json.loads(r.read())
    TOKEN = token_data.get("access_token", "")
    if TOKEN:
        ok(f"Token obtained (expires_in={token_data.get('expires_in')}s)")
    else:
        fail(f"No access_token in response: {token_data}")
        sys.exit(1)
except urllib.error.HTTPError as e:
    fail(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    sys.exit(1)


# ── Step 2: Roles ─────────────────────────────────────────────────────────────

print("\n=== 2. App roles (permissions in token) ===")
roles = _decode_token_roles(TOKEN)
if roles:
    for r in roles:
        ok(r)
else:
    fail("No roles in token — admin has not granted API permissions yet.")
    info("Required: Files.Read.All + Sites.Read.All")
    info("Fix: Azure Portal > App registrations > 67c23570-... > API permissions > Grant admin consent")


# ── Step 3: List sites ────────────────────────────────────────────────────────

print("\n=== 3. List SharePoint sites ===")
result = _graph(TOKEN, "/sites?search=*")
if "_http_error" in result:
    fail(f"HTTP {result['_http_error']}: {result['_body'][:300]}")
else:
    sites = result.get("value", [])
    if sites:
        ok(f"{len(sites)} site(s) returned")
        for s in sites[:5]:
            info(f"  {s.get('displayName','?')} — {s.get('webUrl','')}")
        if len(sites) > 5:
            info(f"  ... and {len(sites)-5} more")
    else:
        info("No sites returned (empty result)")


# ── Step 4: Find SDSPlatform site ────────────────────────────────────────────

SP_HOST = "compliantcs.sharepoint.com"
SP_SITE = "SDSPlatform"
SDS_FOLDER = "SDS Share Folder"

# Known folder structure (confirmed from local download mirror):
IMPORT_FOLDERS = {
    "mapping":          "Customer Purchased List",
    "sds_links":        "SDS With URL Links",
    "risk_links":       "Risk Assessments With URL Links",
    "stock_groups":     "Product Size Mapping",
    "chemical_register":"Chemical Register",
}

print(f"\n=== 4. Find site: {SP_HOST}/sites/{SP_SITE} ===")
site_path = f"/sites/{SP_HOST}:/sites/{SP_SITE}"
result = _graph(TOKEN, site_path)
SITE_ID = None
if "_http_error" in result:
    fail(f"HTTP {result['_http_error']}: {result['_body'][:300]}")
else:
    SITE_ID = result.get("id")
    ok(f"Site found: id={SITE_ID} name={result.get('displayName')} url={result.get('webUrl')}")


# ── Step 5: Get Shared Documents drive ───────────────────────────────────────

DRIVE_ID = None
if SITE_ID:
    print(f"\n=== 5. Get drives on SDSPlatform site ===")
    result = _graph(TOKEN, f"/sites/{SITE_ID}/drives")
    if "_http_error" in result:
        fail(f"HTTP {result['_http_error']}: {result['_body'][:300]}")
    else:
        drives = result.get("value", [])
        for d in drives:
            info(f"  name={d.get('name')} id={d.get('id')}")
            if d.get("name") == "Documents":
                DRIVE_ID = d.get("id")
        if DRIVE_ID:
            ok(f"Shared Documents drive: {DRIVE_ID}")
        else:
            info("'Documents' drive not found — check drive names above")


# ── Step 6: List SDS Share Folder contents ────────────────────────────────────

if DRIVE_ID:
    print(f"\n=== 6. List '{SDS_FOLDER}' subfolders ===")
    folder_path = f"/drives/{DRIVE_ID}/root:/{SDS_FOLDER}:/children"
    result = _graph(TOKEN, folder_path)
    if "_http_error" in result:
        fail(f"HTTP {result['_http_error']}: {result['_body'][:300]}")
    else:
        items = result.get("value", [])
        ok(f"{len(items)} item(s) in '{SDS_FOLDER}'")
        for item in items:
            kind = "folder" if "folder" in item else "file"
            info(f"  [{kind}] {item.get('name')} — modified {item.get('lastModifiedDateTime','?')[:10]}")


# ── Step 7: Probe each import folder — latest file ───────────────────────────

if DRIVE_ID:
    print(f"\n=== 7. Latest file in each import folder ===")
    for key, folder_name in IMPORT_FOLDERS.items():
        folder_path = f"/drives/{DRIVE_ID}/root:/{SDS_FOLDER}/{folder_name}:/children"
        result = _graph(TOKEN, folder_path)
        if "_http_error" in result:
            fail(f"[{key}] HTTP {result['_http_error']}: {result['_body'][:200]}")
            continue
        items = [i for i in result.get("value", []) if "folder" not in i]
        if not items:
            info(f"[{key}] No files in '{folder_name}'")
            continue
        # Sort by lastModifiedDateTime descending
        items.sort(key=lambda x: x.get("lastModifiedDateTime", ""), reverse=True)
        latest = items[0]
        ok(f"[{key}] {latest.get('name')} ({latest.get('size',0)//1024}KB) modified {latest.get('lastModifiedDateTime','?')[:10]}")
        info(f"       download: {latest.get('@microsoft.graph.downloadUrl', 'no direct URL — use /content endpoint')[:80]}")


print("\n=== Done ===\n")
