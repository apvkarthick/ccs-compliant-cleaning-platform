"""Site-level SDS/Risk document distribution based on client-supplied mapping files."""
from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from .distribution import (
    _render_branded_html,
    email_open_pixel_url,
    tracking_url,
)

_BATCH = 500


# ---------------------------------------------------------------------------
# Excel parsers
# ---------------------------------------------------------------------------

def parse_mapping_excel(data: bytes) -> list[dict[str, Any]]:
    df = pd.read_excel(io.BytesIO(data), dtype=str)
    sites: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        accno = str(row.get("ACCNO", "")).strip()
        if not accno or accno == "nan":
            continue
        emails = [
            e.strip() for e in str(row.get("EMAIL") or row.get("CONT_EMAIL") or "").split(";")
            if e.strip() and e.strip() != "nan"
        ]
        stockcodes = [
            s.strip() for s in str(row.get("STOCKCODES", "")).split(",")
            if s.strip() and s.strip() != "nan"
        ]
        sites.append({
            "accno": accno,
            "ho_accno": str(row.get("HO_ACCNO", "")).strip(),
            "ho_name": str(row.get("HO_NAME", "")).strip(),
            "name": str(row.get("NAME", "")).strip(),
            "emails": emails,
            "stockcodes": stockcodes,
        })
    return sites


def parse_sds_links(sds_data: bytes, risk_data: bytes) -> list[dict[str, Any]]:
    """Parse SDS URL file + Risk URL file → merged list of {stock_code, sds_url, risk_url}."""
    sds_map: dict[str, str] = {}
    risk_map: dict[str, str] = {}

    df_sds = pd.read_excel(io.BytesIO(sds_data), header=None, dtype=str)
    for url in df_sds[0]:
        url = str(url).strip()
        if not url or url == "nan":
            continue
        fname = url.split("/")[-1]
        m = re.match(r"([A-Z0-9]+)_", fname)
        if m:
            sds_map[m.group(1)] = url

    df_risk = pd.read_excel(io.BytesIO(risk_data), header=None, dtype=str)
    for url in df_risk[0]:
        url = str(url).strip()
        if not url or url == "nan":
            continue
        fname = url.split("/")[-1]
        m = re.match(r"RISK_([A-Z0-9]+)_", fname)
        if m:
            risk_map[m.group(1)] = url

    all_codes = sorted(set(sds_map) | set(risk_map))
    return [
        {
            "stock_code": code,
            "sds_url": sds_map.get(code),
            "risk_url": risk_map.get(code),
        }
        for code in all_codes
    ]


def parse_chemical_register(data: bytes) -> list[dict[str, Any]]:
    """Parse Chemical Register xlsx → full product records including metadata columns."""
    df = pd.read_excel(io.BytesIO(data), header=None, dtype=str)
    header_row = None
    for i, row in df.iterrows():
        if any(str(v).strip().upper() == "PRODUCT CODE" for v in row):
            header_row = i
            break
    if header_row is None:
        raise ValueError("Chemical Register: 'PRODUCT CODE' header row not found")
    df.columns = [str(v).strip().upper() for v in df.iloc[header_row]]
    df = df.iloc[header_row + 1:].reset_index(drop=True)

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    name_col = _col("PRODUCT NAME", "CHEMICAL NAME", "PRODUCT / CHEMICAL NAME", "PRODUCT/CHEMICAL NAME")
    hazard_col = _col("HAZARD CLASSIFICATION", "HAZARD CLASS", "GHS CLASSIFICATION", "CLASSIFICATION")
    use_col = _col("PRIMARY USE", "APPLICATION", "USE", "PRIMARY USE / APPLICATION", "PRIMARY USE/APPLICATION")
    signal_col = _col("SIGNAL WORD", "SIGNAL")
    un_col = _col("UN NO", "UN NUMBER", "UN #", "UN#", "UN NO.")
    risk_col = _col("RISK ASSESSMENT", "RISK ASSESS", "RISK ASSESSMENT REQUIRED")
    expiry_col = _col("SDS REVIEW DATE", "SDS EXPIRY", "SDS REVIEW", "REVIEW DATE", "EXPIRY DATE")

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        code = str(row.get("PRODUCT CODE", "")).strip()
        if not code or code == "nan":
            continue

        risk_required = str(row.get(risk_col, "") if risk_col else "").strip().upper() == "YES"

        raw_expiry = str(row.get(expiry_col, "") if expiry_col else "").strip()
        sds_expiry = None
        if raw_expiry and raw_expiry != "nan":
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
                try:
                    from datetime import datetime as _dt
                    sds_expiry = _dt.strptime(raw_expiry.split(" ")[0], fmt).date().isoformat()
                    break
                except ValueError:
                    continue

        def _val(col: str | None) -> str | None:
            if not col:
                return None
            v = str(row.get(col, "")).strip()
            return v if v and v != "nan" else None

        records.append({
            "stock_code": code,
            "risk_assessment_required": risk_required,
            "sds_expiry": sds_expiry,
            "product_name": _val(name_col),
            "hazard_classification": _val(hazard_col),
            "primary_use": _val(use_col),
            "signal_word": _val(signal_col),
            "un_number": _val(un_col),
        })
    return records


def fetch_product_metadata(stock_codes: list[str]) -> dict[str, dict]:
    """Return product metadata keyed by stock_code.

    For codes with no direct metadata, falls back to any other code in the same
    stock-group row (col A, B, C, D... in the size-mapping sheet) that does have
    metadata.  The customer's own code is preserved as the dict key so the
    Chemical Register always shows the customer's actual stock code.
    """
    if not stock_codes:
        return {}

    _FIELDS = (
        "stock_code,product_name,hazard_classification,primary_use,"
        "signal_word,un_number,risk_assessment_required,sds_expiry"
    )

    # Direct lookup
    codes_csv = ",".join(stock_codes)
    rows = _sb_get("ccs_sds_links", f"select={_FIELDS}&stock_code=in.({codes_csv})")
    result: dict[str, dict] = {r["stock_code"]: r for r in rows if r.get("product_name")}

    missing = [c for c in stock_codes if c not in result]
    if not missing:
        return result

    # Build group membership map: code → all codes in the same group row
    groups = _sb_get("ccs_stock_groups", "select=primary_code,related_codes")
    group_members: dict[str, list[str]] = {}
    for g in groups:
        members = [g["primary_code"]] + (g.get("related_codes") or [])
        for code in members:
            group_members[code] = members

    # Collect all alternative codes to fetch in one query
    alt_needed: set[str] = set()
    for code in missing:
        for alt in group_members.get(code, []):
            if alt != code:
                alt_needed.add(alt)

    if alt_needed:
        alt_csv = ",".join(alt_needed)
        alt_rows = _sb_get("ccs_sds_links", f"select={_FIELDS}&stock_code=in.({alt_csv})")
        alt_meta: dict[str, dict] = {r["stock_code"]: r for r in alt_rows if r.get("product_name")}

        for code in missing:
            for alt in group_members.get(code, []):
                if alt in alt_meta:
                    result[code] = alt_meta[alt]  # use alt's metadata, but key stays as customer code
                    break

    return result


def generate_chemical_register_excel(
    site_name: str,
    accno: str,
    stock_codes: list[str],
    today: str,
) -> bytes:
    """Generate a per-site Chemical Register Excel filtered to the site's product codes."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    metadata = fetch_product_metadata(stock_codes)

    wb = Workbook()
    ws = wb.active
    ws.title = "Chemical Register"

    GREEN = "2C6B33"
    WHITE = "FFFFFF"

    ws.merge_cells("A1:H1")
    ws["A1"] = "CHEMICAL REGISTER"
    ws["A1"].font = Font(bold=True, size=14, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=GREEN)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24

    ws["A2"] = "Customer:"
    ws["A2"].font = Font(bold=True)
    ws["B2"] = site_name
    ws["E2"] = "Date:"
    ws["E2"].font = Font(bold=True)
    ws["F2"] = today

    ws.append([""])  # spacer

    headers = [
        "Product Code", "Product Name", "Hazard Classification",
        "Primary Use", "Signal Word", "UN No.",
        "Risk Assessment", "SDS Expiry",
    ]
    ws.append(headers)
    hdr_row = ws.max_row
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=hdr_row, column=col_idx)
        cell.font = Font(bold=True, color=WHITE)
        cell.fill = PatternFill("solid", fgColor=GREEN)
        cell.alignment = Alignment(horizontal="center")

    for code in stock_codes:
        m = metadata.get(code, {})
        ws.append([
            code,
            m.get("product_name") or "",
            m.get("hazard_classification") or "",
            m.get("primary_use") or "",
            m.get("signal_word") or "",
            m.get("un_number") or "",
            "YES" if m.get("risk_assessment_required") else "NO",
            m.get("sds_expiry") or "",
        ])

    for col_letter, width in zip("ABCDEFGH", [15, 30, 28, 28, 15, 12, 18, 15]):
        ws.column_dimensions[col_letter].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_register_to_spaces(xlsx_bytes: bytes, accno: str, date_str: str) -> str:
    """Upload per-site Chemical Register Excel to DO Spaces and return its public URL."""
    import boto3

    region = os.getenv("DO_SPACES_REGION", "syd1")
    bucket = os.getenv("DO_SPACES_BUCKET", "simplyrun-media")
    s3 = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=os.getenv("DO_SPACES_ENDPOINT", f"https://{region}.digitaloceanspaces.com"),
        aws_access_key_id=os.getenv("DO_SPACES_KEY", ""),
        aws_secret_access_key=os.getenv("DO_SPACES_SECRET", ""),
    )
    key = f"ccs/registers/{date_str}/{accno}_chemical_register_{date_str}.xlsx"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=xlsx_bytes,
        ACL="public-read",
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return f"https://{bucket}.{region}.digitaloceanspaces.com/{key}"


def parse_stock_groups(data: bytes) -> list[dict[str, Any]]:
    """Parse product-grouping.xlsx → [{primary_code, related_codes[]}]."""
    df = pd.read_excel(io.BytesIO(data), header=0, dtype=str)
    groups: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        codes = [str(v).strip() for v in row if str(v).strip() and str(v).strip() != "nan"]
        if len(codes) >= 2:
            groups.append({"primary_code": codes[0], "related_codes": codes[1:]})
    return groups


# ---------------------------------------------------------------------------
# Supabase REST helpers
# ---------------------------------------------------------------------------

def _sb_url() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def _sb_headers() -> dict[str, str]:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _sb_post_batch(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    url = f"{_sb_url()}/rest/v1/{table}"
    headers = {**_sb_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(rows), _BATCH):
        batch = rows[i : i + _BATCH]
        data = json.dumps(batch).encode()
        req = Request(url, data=data, method="POST", headers=headers)
        try:
            with urlopen(req, timeout=60):
                pass
        except HTTPError as exc:
            body = exc.read().decode()
            raise RuntimeError(f"Supabase upsert to {table} failed ({exc.code}): {body[:300]}")


def _sb_get(table: str, params: str = "") -> list[dict]:
    url = f"{_sb_url()}/rest/v1/{table}?{params}"
    req = Request(url, method="GET", headers=_sb_headers())
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        raise RuntimeError(f"Supabase GET {table} failed ({exc.code}): {exc.read().decode()[:200]}")


def _sb_delete(table: str, filter_param: str) -> None:
    url = f"{_sb_url()}/rest/v1/{table}?{filter_param}"
    req = Request(url, method="DELETE", headers={**_sb_headers(), "Prefer": "return=minimal"})
    try:
        with urlopen(req, timeout=30):
            pass
    except HTTPError as exc:
        raise RuntimeError(f"Supabase DELETE {table} failed ({exc.code}): {exc.read().decode()[:200]}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_mapping(
    mapping_bytes: bytes,
    sds_bytes: bytes,
    risk_bytes: bytes,
    grouping_bytes: bytes | None = None,
    register_bytes: bytes | None = None,
) -> dict[str, int]:
    now = _now()

    sites = parse_mapping_excel(mapping_bytes)
    links = parse_sds_links(sds_bytes, risk_bytes)

    _sb_post_batch("ccs_site_mapping", [{**s, "imported_at": now} for s in sites])
    _sb_post_batch(
        "ccs_sds_links",
        [{**lnk, "imported_at": now} for lnk in links if lnk.get("sds_url") or lnk.get("risk_url")],
    )

    group_count = 0
    if grouping_bytes:
        groups = parse_stock_groups(grouping_bytes)
        _sb_post_batch("ccs_stock_groups", [{**g, "imported_at": now} for g in groups])
        group_count = len(groups)

    register_count = 0
    if register_bytes:
        reg_records = parse_chemical_register(register_bytes)
        # PostgREST PGRST102: all rows in a batch upsert must have identical key sets.
        # Normalize every row to the same register fields — None becomes SQL NULL,
        # which is fine since we only include register-specific columns (not sds_url/risk_url).
        _REGISTER_FIELDS = (
            "stock_code", "risk_assessment_required", "sds_expiry",
            "product_name", "hazard_classification", "primary_use",
            "signal_word", "un_number",
        )
        _sb_post_batch(
            "ccs_sds_links",
            [{k: r.get(k) for k in _REGISTER_FIELDS} for r in reg_records],
        )
        register_count = len(reg_records)

    return {"sites": len(sites), "links": len(links), "groups": group_count, "register": register_count}


# ---------------------------------------------------------------------------
# Sites listing
# ---------------------------------------------------------------------------

def list_sites(search: str = "", page: int = 1, page_size: int = 50) -> dict[str, Any]:
    offset = (page - 1) * page_size
    params = f"select=*&order=name.asc&limit={page_size}&offset={offset}"
    if search:
        enc = quote(search.replace("%", ""), safe="")
        params += f"&or=(name.ilike.*{enc}*,ho_name.ilike.*{enc}*)"

    sites = _sb_get("ccs_site_mapping", params)

    excl_set = {r["accno"] for r in _sb_get("ccs_site_exclusions", "select=accno")}
    held_set = {r["accno"] for r in _sb_get("ccs_site_holds", "select=accno")}
    for site in sites:
        site["excluded"] = site.get("accno") in excl_set
        site["held"] = site.get("accno") in held_set

    return {"sites": sites, "page": page, "page_size": page_size}


def get_stats() -> dict[str, int]:
    try:
        total = len(_sb_get("ccs_site_mapping", "select=accno"))
        excl = len(_sb_get("ccs_site_exclusions", "select=accno"))
        held = len(_sb_get("ccs_site_holds", "select=accno"))
        links = len(_sb_get("ccs_sds_links", "select=stock_code"))
        return {
            "total_sites": total,
            "excluded_sites": excl,
            "held_sites": held,
            "active_sites": total - excl - held,
            "sds_links": links,
        }
    except Exception:
        return {"total_sites": 0, "excluded_sites": 0, "held_sites": 0, "active_sites": 0, "sds_links": 0}


def exclude_site(accno: str, name: str = "") -> dict[str, str]:
    _sb_post_batch("ccs_site_exclusions", [{"accno": accno, "name": name, "excluded_at": _now()}])
    return {"excluded": accno}


def include_site(accno: str) -> dict[str, str]:
    _sb_delete("ccs_site_exclusions", f"accno=eq.{quote(accno, safe='')}")
    return {"included": accno}


def hold_site(accno: str, name: str = "") -> dict[str, str]:
    _sb_post_batch("ccs_site_holds", [{"accno": accno, "name": name, "held_at": _now()}])
    return {"held": accno}


def unhold_site(accno: str) -> dict[str, str]:
    _sb_delete("ccs_site_holds", f"accno=eq.{quote(accno, safe='')}")
    return {"unheld": accno}


def send_manual(
    accno: str,
    stockcodes: list[str],
    email: str,
    dry_run: bool = False,
    *,
    public_base_url: str = "",
    tracking_secret: str = "",
) -> dict[str, Any]:
    """Send SDS/Risk email for a specific site with selected products."""
    sites = _sb_get("ccs_site_mapping", f"select=*&accno=eq.{quote(accno, safe='')}")
    if not sites:
        raise ValueError(f"Site {accno!r} not found")
    site = sites[0]

    use_codes = stockcodes if stockcodes else (site.get("stockcodes") or [])
    if not use_codes:
        raise ValueError(f"No products specified for site {accno!r}")

    sds_map, risk_map, group_fallback, risk_required_set = load_lookup_maps()
    docs = resolve_docs_for_site(use_codes, sds_map, risk_map, group_fallback, risk_required_set)
    if not docs:
        return {"status": "skipped", "reason": "no SDS/Risk documents found for selected products"}

    batch_id = f"manual_{accno}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    msg = compose_site_email(
        site, docs, email,
        batch_id=batch_id,
        public_base_url=public_base_url,
        tracking_secret=tracking_secret,
    )

    if dry_run:
        return {"status": "dry_run", "site": site.get("name"), "email": email, "docs": len(docs)}

    from .distribution import _find_or_create_ghl_contact_id, _send_messages_via_ghl
    contact_id = _find_or_create_ghl_contact_id({"email": email, "name": site.get("name", "")})
    if contact_id:
        msg["contact_id"] = contact_id
    result = _send_messages_via_ghl([msg])
    return {
        "status": result.get("status", "unknown"),
        "site": site.get("name"),
        "email": email,
        "docs": len(docs),
    }


# ---------------------------------------------------------------------------
# Document resolution
# ---------------------------------------------------------------------------

def load_lookup_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str], set[str]]:
    """Load SDS links + stock groups into memory.
    Returns (sds_map, risk_map, group_fallback, risk_required_set) where
    group_fallback maps a related code → its primary code and
    risk_required_set is codes where risk_assessment_required = True."""
    links = _sb_get("ccs_sds_links", "select=stock_code,sds_url,risk_url,risk_assessment_required")
    sds_map = {r["stock_code"]: r["sds_url"] for r in links if r.get("sds_url")}
    risk_map = {r["stock_code"]: r["risk_url"] for r in links if r.get("risk_url")}
    risk_required_set = {r["stock_code"] for r in links if r.get("risk_assessment_required")}

    groups = _sb_get("ccs_stock_groups", "select=primary_code,related_codes")
    group_fallback: dict[str, str] = {}
    for g in groups:
        primary = g.get("primary_code", "")
        for related in g.get("related_codes") or []:
            if related and related not in sds_map and related not in risk_map:
                group_fallback[related] = primary

    return sds_map, risk_map, group_fallback, risk_required_set


def resolve_docs_for_site(
    stockcodes: list[str],
    sds_map: dict[str, str],
    risk_map: dict[str, str],
    group_fallback: dict[str, str],
    risk_required_set: set[str] | None = None,
) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for code in stockcodes:
        sds_url = sds_map.get(code, "")
        # Only include risk URL if Chemical Register marks this product as requiring it.
        # None means register not yet imported — fall back to including risk URL if available.
        risk_url = ""
        if risk_required_set is None or code in risk_required_set:
            risk_url = risk_map.get(code, "")
        if not sds_url and not risk_url:
            primary = group_fallback.get(code, "")
            if primary:
                sds_url = sds_map.get(primary, "")
                if risk_required_set is None or code in risk_required_set:
                    risk_url = risk_map.get(primary, "")
        if sds_url or risk_url:
            docs.append({"code": code, "sds_url": sds_url, "risk_url": risk_url})
    return docs


# ---------------------------------------------------------------------------
# Email composition
# ---------------------------------------------------------------------------

def compose_site_email(
    site: dict[str, Any],
    docs: list[dict[str, str]],
    email_addr: str,
    *,
    batch_id: str = "",
    public_base_url: str = "",
    tracking_secret: str = "",
) -> dict[str, Any]:
    site_name = site.get("name", "")
    ho_name = site.get("ho_name", "") or site_name
    accno = site.get("accno", "")
    contact_id = accno or email_addr

    products_in_email = [{"code": d["code"], "name": d["code"]} for d in docs]
    documents: list[dict[str, str]] = []

    for d in docs:
        for label, url_key in [("SDS", "sds_url"), ("Risk Assessment", "risk_url")]:
            raw_url = d.get(url_key, "")
            if not raw_url:
                continue
            doc_id = f"site_{accno}_{d['code']}_{label.replace(' ', '_').lower()}"
            delivery_url = raw_url
            if public_base_url and tracking_secret:
                delivery_url = tracking_url(
                    public_base_url=public_base_url,
                    document_id=doc_id,
                    contact_id=contact_id,
                    chemical_name=d["code"],
                    redirect_url=raw_url,
                    secret=tracking_secret,
                )
            documents.append({
                "label": label,
                "product_code": d["code"],
                "chemical_name": d["code"],
                "source_url": raw_url,
                "delivery_url": delivery_url,
                "document_id": doc_id,
                "filename": raw_url.split("/")[-1],
            })

    pixel_url = ""
    if public_base_url and tracking_secret:
        pixel_url = email_open_pixel_url(
            public_base_url=public_base_url,
            email=email_addr,
            contact_id=contact_id,
            secret=tracking_secret,
            batch_id=batch_id,
        )

    logo_url = f"{public_base_url}/api/assets/ccs_logo.png" if public_base_url else ""

    html_body = _render_branded_html(
        contact_name=site_name,
        company=ho_name,
        products_in_email=products_in_email,
        documents=documents,
        tracking_pixel_url=pixel_url,
        logo_url=logo_url,
    )

    # Generate per-site Chemical Register Excel and upload to DO Spaces
    register_url = ""
    stock_codes = site.get("stockcodes") or [d["code"] for d in docs]
    if stock_codes:
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            xlsx = generate_chemical_register_excel(site_name, accno, stock_codes, today)
            register_url = upload_register_to_spaces(xlsx, accno, today)
        except Exception:
            pass  # non-fatal: email sends without attachment if generation fails

    msg: dict[str, Any] = {
        "to": email_addr,
        "name": site_name,
        "contact_id": contact_id,
        "accno": accno,
        "subject": f"Your SDS Compliance Pack — {site_name}",
        "html": html_body,
        "documents": documents,
    }
    if register_url:
        msg["attachments"] = [register_url]
        msg["register_url"] = register_url
    return msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
