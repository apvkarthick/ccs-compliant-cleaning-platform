"""Document Library: ingest raw client PDFs into DO Spaces and map to products.

Separate from the existing workbook flow. Existing code is not modified.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import boto3

from .excel_parser import _normalize, parse_client_workbook
from .workbooks import make_customer_id, save_workbook


# ---------------------------------------------------------------------------
# DO Spaces client
# ---------------------------------------------------------------------------

def _spaces_client():
    return boto3.client(
        "s3",
        region_name=os.getenv("DO_SPACES_REGION", "syd1"),
        endpoint_url=os.getenv("DO_SPACES_ENDPOINT", "https://syd1.digitaloceanspaces.com"),
        aws_access_key_id=os.getenv("DO_SPACES_KEY", ""),
        aws_secret_access_key=os.getenv("DO_SPACES_SECRET", ""),
    )


def _bucket() -> str:
    return os.getenv("DO_SPACES_BUCKET", "simplyrun-media")


def _prefix() -> str:
    return os.getenv("DO_SPACES_PREFIX", "ccs/")


def _public_base() -> str:
    bucket = _bucket()
    region = os.getenv("DO_SPACES_REGION", "syd1")
    return f"https://{bucket}.{region}.digitaloceanspaces.com"


# ---------------------------------------------------------------------------
# Supabase helpers (mirrors workbooks.py pattern — no shared state)
# ---------------------------------------------------------------------------

def _supa_url() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def _supa_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _headers() -> dict[str, str]:
    key = _supa_key()
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _supa_post(url: str, data: Any, extra: dict | None = None) -> dict:
    body = json.dumps(data).encode()
    h = {**_headers(), "Content-Type": "application/json", **(extra or {})}
    req = Request(url, data=body, headers=h, method="POST")
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
            return {"status": r.status, "body": json.loads(raw) if raw else {}}
    except HTTPError as e:
        return {"status": e.code, "error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def _supa_patch(url: str, data: Any) -> dict:
    body = json.dumps(data).encode()
    h = {**_headers(), "Content-Type": "application/json", "Prefer": "return=representation"}
    req = Request(url, data=body, headers=h, method="PATCH")
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
            return {"status": r.status, "body": json.loads(raw) if raw else {}}
    except HTTPError as e:
        return {"status": e.code, "error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def _supa_get(url: str) -> dict:
    req = Request(url, headers=_headers())
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
            return {"status": r.status, "body": json.loads(raw) if raw else []}
    except HTTPError as e:
        return {"status": e.code, "error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def _supa_delete(url: str) -> dict:
    req = Request(url, headers=_headers(), method="DELETE")
    try:
        with urlopen(req, timeout=15) as r:
            return {"status": r.status}
    except HTTPError as e:
        return {"status": e.code, "error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"status": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# DO Spaces upload
# ---------------------------------------------------------------------------

def upload_to_spaces(file_bytes: bytes, filename: str, s3_client, ingest_date: str) -> str:
    """Upload a PDF to DO Spaces under ccs/{ingest_date}/{filename}. Returns public URL."""
    key = f"{_prefix()}{ingest_date}/{filename}"
    s3_client.put_object(
        Bucket=_bucket(),
        Key=key,
        Body=file_bytes,
        ACL="public-read",
        ContentType="application/pdf",
    )
    return f"{_public_base()}/{key}"


def list_spaces_files(ingest_date: str | None = None) -> list[str]:
    """List all object keys under the ccs/ prefix (or a specific date subfolder)."""
    s3 = _spaces_client()
    prefix = f"{_prefix()}{ingest_date}/" if ingest_date else _prefix()
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def delete_spaces_files(keys: list[str]) -> dict:
    """Delete specific object keys from DO Spaces. Guards against deleting current versions."""
    if not keys:
        return {"deleted": [], "errors": []}
    # Fetch current URLs to guard against deleting active versions
    current_urls = _get_current_urls()
    current_keys = {url.replace(f"{_public_base()}/", "") for url in current_urls}
    blocked = [k for k in keys if k in current_keys]
    if blocked:
        return {"deleted": [], "errors": [f"Cannot delete current version: {k}" for k in blocked]}
    s3 = _spaces_client()
    deleted, errors = [], []
    for key in keys:
        try:
            s3.delete_object(Bucket=_bucket(), Key=key)
            deleted.append(key)
        except Exception as e:
            errors.append(f"{key}: {e}")
    return {"deleted": deleted, "errors": errors}


def _get_current_urls() -> set[str]:
    base = _supa_url()
    if not base:
        return set()
    url = f"{base}/rest/v1/ccs_document_library?select=sds_url,risk_url"
    rows = _supa_get(url).get("body", [])
    urls: set[str] = set()
    if isinstance(rows, list):
        for r in rows:
            if r.get("sds_url"):
                urls.add(r["sds_url"])
            if r.get("risk_url"):
                urls.add(r["risk_url"])
    return urls


# ---------------------------------------------------------------------------
# Product/file matching
# ---------------------------------------------------------------------------

def _code_aliases(code: str) -> list[str]:
    """Normalize code + optional trailing-F variant (matches existing excel_parser logic)."""
    norm = _normalize(code)
    aliases = [norm]
    if norm.endswith("f"):
        aliases.append(norm[:-1])
    return aliases


def match_by_code(code: str, filenames: list[str], *, risk: bool) -> str | None:
    aliases = _code_aliases(code)
    if risk:
        aliases = [f"risk_{a}" for a in aliases]
    for filename in filenames:
        norm = _normalize(filename)
        is_risk = norm.startswith("risk_") or "risk" in norm
        if risk != is_risk:
            continue
        if any(norm.startswith(alias) for alias in aliases):
            return filename
    return None


def match_by_name(name: str, filenames: list[str], *, risk: bool) -> str | None:
    if not name:
        return None
    name_norm = _normalize(name)
    for filename in filenames:
        norm = _normalize(filename)
        is_risk = "risk" in norm
        if risk != is_risk:
            continue
        if name_norm in norm:
            return filename
    return None


def _match(code: str, name: str, filenames: list[str], *, risk: bool) -> tuple[str | None, str]:
    """Returns (matched_filename, match_method)."""
    m = match_by_code(code, filenames, risk=risk)
    if m:
        return m, "code"
    m = match_by_name(name, filenames, risk=risk)
    if m:
        return m, "name"
    return None, ""


# ---------------------------------------------------------------------------
# Supabase library table operations
# ---------------------------------------------------------------------------

def _upsert_library_row(
    product_code: str,
    product_name: str,
    sds_filename: str | None,
    sds_url: str | None,
    risk_filename: str | None,
    risk_url: str | None,
    match_method: str,
    customer_id: str,
    ingest_date: str,
    existing: dict | None,
) -> None:
    base = _supa_url()
    if not base:
        return
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        row: dict[str, Any] = {"updated_at": now, "customer_id": customer_id}
        if sds_url and sds_url != existing.get("sds_url"):
            row["sds_url_previous"] = existing.get("sds_url")
            row["sds_url"] = sds_url
            row["sds_filename"] = sds_filename
            row["sds_version"] = (existing.get("sds_version") or 1) + 1
            row["sds_uploaded_at"] = now
        if risk_url and risk_url != existing.get("risk_url"):
            row["risk_url_previous"] = existing.get("risk_url")
            row["risk_url"] = risk_url
            row["risk_filename"] = risk_filename
            row["risk_version"] = (existing.get("risk_version") or 1) + 1
            row["risk_uploaded_at"] = now
        if len(row) > 2:  # has changes beyond updated_at and customer_id
            _supa_patch(
                f"{base}/rest/v1/ccs_document_library?product_code=eq.{quote(product_code)}",
                row,
            )
    else:
        _supa_post(
            f"{base}/rest/v1/ccs_document_library",
            {
                "product_code": product_code,
                "product_name": product_name,
                "sds_filename": sds_filename,
                "sds_url": sds_url,
                "sds_version": 1,
                "sds_uploaded_at": now if sds_url else None,
                "sds_url_previous": None,
                "risk_filename": risk_filename,
                "risk_url": risk_url,
                "risk_version": 1,
                "risk_uploaded_at": now if risk_url else None,
                "risk_url_previous": None,
                "match_method": match_method,
                "customer_id": customer_id,
                "updated_at": now,
            },
            {"Prefer": "resolution=merge-duplicates,return=minimal"},
        )


def _append_version_rows(version_rows: list[dict]) -> None:
    base = _supa_url()
    if not base or not version_rows:
        return
    _supa_post(
        f"{base}/rest/v1/ccs_document_versions",
        version_rows,
        {"Prefer": "return=minimal"},
    )


def _load_existing_library(product_codes: list[str]) -> dict[str, dict]:
    base = _supa_url()
    if not base or not product_codes:
        return {}
    codes_csv = ",".join(quote(c) for c in product_codes)
    url = f"{base}/rest/v1/ccs_document_library?product_code=in.({codes_csv})&select=*"
    rows = _supa_get(url).get("body", [])
    if not isinstance(rows, list):
        return {}
    return {r["product_code"]: r for r in rows}


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest_library(
    register_bytes: bytes,
    pdf_files: list[tuple[str, bytes]],
    customer_id: str,
    public_base_url: str = "",
) -> dict:
    """
    Upload PDFs to DO Spaces, match to products from Chemical Register Excel,
    persist to ccs_document_library, and create/update a ccs_workbooks row
    so the existing distribution flow can use the library documents.

    pdf_files: list of (filename, content_bytes) from multipart upload.
    Returns summary dict.
    """
    ingest_date = date.today().isoformat()
    s3 = _spaces_client()

    # 1. Upload all PDFs to DO Spaces
    filename_to_url: dict[str, str] = {}
    upload_errors: list[str] = []
    for filename, content in pdf_files:
        try:
            url = upload_to_spaces(content, filename, s3, ingest_date)
            filename_to_url[filename] = url
        except Exception as e:
            upload_errors.append(f"{filename}: {e}")

    uploaded_filenames = list(filename_to_url.keys())

    # 2. Parse Chemical Register to get product list
    parsed = parse_client_workbook(register_bytes, source_files=None, public_base_url="")
    products_raw = parsed.get("products", [])
    customer_name = parsed.get("customer", {}).get("name", customer_id)
    if not customer_id:
        customer_id = make_customer_id(customer_name)

    # 3. Load existing library rows for these product codes
    all_codes = [p.get("code", "") for p in products_raw if p.get("code")]
    existing_map = _load_existing_library(all_codes)

    # 4. Match each product to a PDF
    matched: list[dict] = []
    unmatched: list[dict] = []
    version_rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for product in products_raw:
        code = product.get("code", "")
        name = product.get("name", "")
        if not code and not name:
            continue

        sds_file, sds_method = _match(code, name, uploaded_filenames, risk=False)
        risk_file, risk_method = _match(code, name, uploaded_filenames, risk=True)

        sds_url = filename_to_url.get(sds_file) if sds_file else None
        risk_url = filename_to_url.get(risk_file) if risk_file else None
        method = sds_method or risk_method or "none"
        existing = existing_map.get(code)

        _upsert_library_row(
            product_code=code,
            product_name=name,
            sds_filename=sds_file,
            sds_url=sds_url,
            risk_filename=risk_file,
            risk_url=risk_url,
            match_method=method,
            customer_id=customer_id,
            ingest_date=ingest_date,
            existing=existing,
        )

        # Track version history for newly uploaded files
        if sds_url:
            v = (existing.get("sds_version") or 1) + 1 if existing and existing.get("sds_url") and existing["sds_url"] != sds_url else 1
            version_rows.append({
                "product_code": code,
                "document_type": "sds",
                "version": v,
                "filename": sds_file,
                "url": sds_url,
                "ingest_batch": ingest_date,
                "uploaded_at": now,
            })
        if risk_url:
            v = (existing.get("risk_version") or 1) + 1 if existing and existing.get("risk_url") and existing["risk_url"] != risk_url else 1
            version_rows.append({
                "product_code": code,
                "document_type": "risk",
                "version": v,
                "filename": risk_file,
                "url": risk_url,
                "ingest_batch": ingest_date,
                "uploaded_at": now,
            })

        if sds_url or risk_url:
            matched.append({
                "code": code,
                "name": name,
                "sds_filename": sds_file,
                "sds_url": sds_url,
                "risk_filename": risk_file,
                "risk_url": risk_url,
                "match_method": method,
            })
        else:
            unmatched.append({"code": code, "name": name})

    _append_version_rows(version_rows)

    # 5. Build synthetic parsed_json for ccs_workbooks (same shape as existing flow)
    synthetic_products = []
    for product in products_raw:
        code = product.get("code", "")
        # Find the match result
        match_result = next((m for m in matched if m["code"] == code), None)
        sds_url = match_result["sds_url"] if match_result else None
        risk_url = match_result["risk_url"] if match_result else None
        synthetic_products.append({
            **product,
            "sds": {
                "matched": bool(sds_url),
                "filename": match_result["sds_filename"] if match_result else None,
                "url": sds_url,
            },
            "risk_assessment": {
                "matched": bool(risk_url),
                "filename": match_result["risk_filename"] if match_result else None,
                "url": risk_url,
            },
        })

    missing_docs = [{"code": u["code"], "name": u["name"]} for u in unmatched]
    synthetic_json = {
        "customer": parsed.get("customer", {"name": customer_name}),
        "products": synthetic_products,
        "missing_documents": missing_docs,
        "_library_source": True,
        "_ingest_date": ingest_date,
    }
    save_workbook(customer_id, customer_name, "library_ingest", synthetic_json)

    # 6. Compute orphaned files (uploaded but matched to no product)
    matched_filenames = {m["sds_filename"] for m in matched if m["sds_filename"]}
    matched_filenames |= {m["risk_filename"] for m in matched if m["risk_filename"]}
    orphaned = [f for f in uploaded_filenames if f not in matched_filenames]

    return {
        "ingest_date": ingest_date,
        "customer_id": customer_id,
        "uploaded_count": len(uploaded_filenames),
        "matched_count": len(matched),
        "unmatched_products": unmatched,
        "orphaned_filenames": orphaned,
        "upload_errors": upload_errors,
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_library_status() -> dict:
    base = _supa_url()
    library_rows: list[dict] = []
    if base:
        url = f"{base}/rest/v1/ccs_document_library?select=*&order=product_code.asc"
        library_rows = _supa_get(url).get("body", []) or []

    # List all files in DO Spaces under ccs/ prefix
    try:
        spaces_keys = list_spaces_files()
    except Exception:
        spaces_keys = []

    matched_urls: set[str] = set()
    for r in library_rows:
        for field in ("sds_url", "risk_url", "sds_url_previous", "risk_url_previous"):
            if r.get(field):
                matched_urls.add(r[field])

    orphaned_keys = [
        k for k in spaces_keys
        if f"{_public_base()}/{k}" not in matched_urls
    ]

    unmatched = [
        {"code": r["product_code"], "name": r["product_name"]}
        for r in library_rows
        if not r.get("sds_url") and not r.get("risk_url")
    ]

    return {
        "spaces_file_count": len(spaces_keys),
        "library_product_count": len(library_rows),
        "matched_sds_count": sum(1 for r in library_rows if r.get("sds_url")),
        "matched_risk_count": sum(1 for r in library_rows if r.get("risk_url")),
        "unmatched_products": unmatched,
        "orphaned_space_keys": orphaned_keys,
        "library": library_rows,
    }


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------

def get_versions(product_code: str) -> list[dict]:
    base = _supa_url()
    if not base:
        return []
    url = (
        f"{base}/rest/v1/ccs_document_versions"
        f"?product_code=eq.{quote(product_code)}"
        f"&order=uploaded_at.desc"
    )
    return _supa_get(url).get("body", []) or []


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def rollback_version(product_code: str, document_type: str) -> dict:
    """Swap current URL with previous URL for sds or risk."""
    base = _supa_url()
    if not base:
        return {"error": "Supabase not configured"}

    url = f"{base}/rest/v1/ccs_document_library?product_code=eq.{quote(product_code)}&select=*"
    rows = _supa_get(url).get("body", [])
    if not isinstance(rows, list) or not rows:
        return {"error": "Product not found"}
    row = rows[0]

    if document_type == "sds":
        if not row.get("sds_url_previous"):
            return {"error": "No previous SDS version to roll back to"}
        patch = {
            "sds_url": row["sds_url_previous"],
            "sds_url_previous": row["sds_url"],
            "sds_version": max(1, (row.get("sds_version") or 1) - 1),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    elif document_type == "risk":
        if not row.get("risk_url_previous"):
            return {"error": "No previous Risk version to roll back to"}
        patch = {
            "risk_url": row["risk_url_previous"],
            "risk_url_previous": row["risk_url"],
            "risk_version": max(1, (row.get("risk_version") or 1) - 1),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        return {"error": "document_type must be 'sds' or 'risk'"}

    result = _supa_patch(
        f"{base}/rest/v1/ccs_document_library?product_code=eq.{quote(product_code)}",
        patch,
    )
    # Also update the ccs_workbooks synthetic row
    _refresh_workbook_urls(product_code, row.get("customer_id", ""), document_type, patch)
    return result


def _refresh_workbook_urls(product_code: str, customer_id: str, doc_type: str, patch: dict) -> None:
    """Best-effort: update the library-sourced workbook row so distribution uses the rolled-back URL."""
    if not customer_id:
        return
    base = _supa_url()
    if not base:
        return
    url = f"{base}/rest/v1/ccs_workbooks?customer_id=eq.{quote(customer_id)}&select=parsed_json"
    rows = _supa_get(url).get("body", [])
    if not isinstance(rows, list) or not rows:
        return
    parsed_json = rows[0].get("parsed_json", {})
    if not parsed_json.get("_library_source"):
        return
    new_url = patch.get(f"{doc_type}_url")
    key = "sds" if doc_type == "sds" else "risk_assessment"
    for product in parsed_json.get("products", []):
        if product.get("code") == product_code:
            product[key]["url"] = new_url
            product[key]["matched"] = bool(new_url)
            break
    _supa_patch(
        f"{base}/rest/v1/ccs_workbooks?customer_id=eq.{quote(customer_id)}",
        {"parsed_json": parsed_json, "uploaded_at": datetime.now(timezone.utc).isoformat()},
    )
