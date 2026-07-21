"""
Microsoft Graph / SharePoint helpers for CCS platform.

Reads credentials from environment:
  CCS_SP_TENANT_ID, CCS_SP_CLIENT_ID, CCS_SP_CLIENT_SECRET

Folder structure (SDSPlatform site, SDS Share Folder):
  Chemical Register/            -> chemical_register import
  Customer Purchased List/      -> mapping import
  Product Size Mapping/         -> stock_groups import
  Risk Assessments With URL Links/ -> risk_links import
  SDS With URL Links/           -> sds_links import
"""

from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from functools import lru_cache

GRAPH = "https://graph.microsoft.com/v1.0"

SP_HOST = "compliantcs.sharepoint.com"
SP_SITE = "SDSPlatform"
SDS_FOLDER = "SDS Share Folder"

IMPORT_FOLDERS: dict[str, str] = {
    "mapping":          "Customer Purchased List",
    "sds_links":        "SDS With URL Links",
    "risk_links":       "Risk Assessments With URL Links",
    "stock_groups":     "Product Size Mapping",
    "chemical_register": "Chemical Register",
}


class SharePointError(Exception):
    pass


def _env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise SharePointError(f"Missing env var: {key}")
    return val


def get_sp_token() -> str:
    """Get OAuth2 client-credentials token for Microsoft Graph."""
    tenant_id = _env("CCS_SP_TENANT_ID")
    client_id = _env("CCS_SP_CLIENT_ID")
    client_secret = _env("CCS_SP_CLIENT_SECRET")

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    body = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=15) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SharePointError(f"Token request failed {e.code}: {e.read().decode(errors='replace')[:300]}") from e

    token = data.get("access_token", "")
    if not token:
        raise SharePointError(f"No access_token in response: {data}")
    return token


def _graph_get(token: str, path: str) -> dict:
    url = f"{GRAPH}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SharePointError(f"Graph {path} HTTP {e.code}: {body[:300]}") from e


def get_site_id(token: str) -> str:
    data = _graph_get(token, f"/sites/{SP_HOST}:/sites/{SP_SITE}")
    site_id = data.get("id", "")
    if not site_id:
        raise SharePointError(f"Site '{SP_SITE}' not found on {SP_HOST}")
    return site_id


def get_drive_id(token: str, site_id: str) -> str:
    data = _graph_get(token, f"/sites/{site_id}/drives")
    for drive in data.get("value", []):
        if drive.get("name") == "Documents":
            return drive["id"]
    raise SharePointError("'Documents' drive not found on SDSPlatform site")


def list_folder(token: str, drive_id: str, folder_path: str) -> list[dict]:
    """List files (not folders) in a given path under the drive root."""
    encoded = urllib.parse.quote(folder_path, safe="/")
    data = _graph_get(token, f"/drives/{drive_id}/root:/{encoded}:/children")
    return [item for item in data.get("value", []) if "folder" not in item]


def download_file(token: str, drive_id: str, item_id: str) -> bytes:
    """Download file content by item ID."""
    url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/content"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SharePointError(f"Download failed HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from e


def get_latest_file(token: str, drive_id: str, subfolder: str) -> tuple[str, bytes] | None:
    """Return (filename, bytes) for the most-recently-modified file in SDS_FOLDER/subfolder.
    Returns None if folder is empty."""
    folder_path = f"{SDS_FOLDER}/{subfolder}"
    files = list_folder(token, drive_id, folder_path)
    if not files:
        return None
    files.sort(key=lambda x: x.get("lastModifiedDateTime", ""), reverse=True)
    latest = files[0]
    content = download_file(token, drive_id, latest["id"])
    return latest["name"], content


def pull_all_import_files() -> dict[str, tuple[str, bytes] | None]:
    """
    Pull the latest file from each import folder in SharePoint.

    Returns dict keyed by import type:
      mapping, sds_links, risk_links, stock_groups, chemical_register
    Each value is (filename, bytes) or None if folder is empty.

    Raises SharePointError if credentials missing or Graph API returns an error
    (e.g. 401 when admin consent not yet granted).
    """
    token = get_sp_token()
    site_id = get_site_id(token)
    drive_id = get_drive_id(token, site_id)

    result: dict[str, tuple[str, bytes] | None] = {}
    for key, folder_name in IMPORT_FOLDERS.items():
        result[key] = get_latest_file(token, drive_id, folder_name)
    return result


def check_permissions() -> dict[str, object]:
    """Quick connectivity check — returns token roles and site accessibility."""
    import base64
    token = get_sp_token()

    roles: list[str] = []
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        roles = json.loads(base64.urlsafe_b64decode(payload)).get("roles", [])
    except Exception:
        pass

    site_ok = False
    site_error = ""
    try:
        get_site_id(token)
        site_ok = True
    except SharePointError as e:
        site_error = str(e)

    return {
        "roles": roles,
        "has_permissions": bool(roles),
        "site_accessible": site_ok,
        "site_error": site_error,
    }
