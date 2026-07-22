from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
import re
from urllib.parse import quote, urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE)


def build_test_distribution(
    *,
    preview: dict[str, Any],
    contacts: list[dict[str, Any]],
    dry_run: bool = True,
    batch_id: str = "",
) -> dict[str, Any]:
    valid_contacts = [_normalize_contact(contact) for contact in contacts]
    valid_contacts = [contact for contact in valid_contacts if contact["email"]]
    products = preview.get("products", [])
    messages = [_compose_message(preview, contact, products, batch_id=batch_id) for contact in valid_contacts]
    audit_events = [
        {
            "event_type": "dry_run_email_prepared" if dry_run else "email_send_requested",
            "contact_email": message["to"],
            "customer_company": preview.get("customer", {}).get("company", ""),
            "product_codes": [product.get("code", "") for product in products],
            "created_at": _now(),
            "metadata": {
                "subject": message["subject"],
                "dry_run": dry_run,
                "documents": message["documents"],
            },
        }
        for message in messages
    ]
    distribution_rows = _distribution_rows(messages, dry_run=dry_run)

    return {
        "dry_run": dry_run,
        "summary": {
            "contacts": len(valid_contacts),
            "products": len(products),
            "messages": len(messages),
            "documents": sum(len(message["documents"]) for message in messages),
        },
        "messages": messages,
        "audit_events": audit_events,
        "distribution_rows": distribution_rows,
    }


def process_distribution(
    *,
    preview: dict[str, Any],
    contacts: list[dict[str, Any]],
    dry_run: bool = True,
    batch_id: str = "",
) -> dict[str, Any]:
    selected_contacts = contacts or _filter_contacts_by_products(_fetch_ghl_contacts(), preview.get("products", []))
    if not dry_run:
        selected_contacts = [_with_ghl_contact_id(contact) for contact in selected_contacts]
    distribution = build_test_distribution(preview=preview, contacts=selected_contacts, dry_run=dry_run, batch_id=batch_id)

    if dry_run:
        distribution["ghl"] = {"status": "skipped", "reason": "dry_run"}
        distribution["supabase"] = {"status": "skipped", "reason": "dry_run"}
        return distribution

    distribution["ghl"] = _send_messages_via_ghl(distribution["messages"])
    _ensure_documents_in_supabase(distribution["messages"])
    distribution["distribution_rows"] = distribution_rows_for_supabase(
        distribution["messages"],
        dry_run=False,
        table=os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distributions"),
        batch_id=batch_id,
    )
    distribution["supabase"] = _log_events_to_supabase(distribution["distribution_rows"])
    return distribution


def _render_branded_html(
    contact_name: str,
    company: str,
    products_in_email: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    tracking_pixel_url: str = "",
    logo_url: str = "",
    cover_notice: str = "",
) -> str:
    """Branded HTML email template — table-based for email client compatibility."""
    product_cards: list[str] = []
    for product in products_in_email:
        product_docs = [d for d in documents if d["product_code"] == product.get("code", "")]
        if not product_docs:
            continue
        buttons: list[str] = []
        for doc in product_docs:
            is_sds = doc["label"] == "SDS"
            bg = "#2C6B33" if is_sds else "#ffffff"
            fg = "#ffffff" if is_sds else "#2C6B33"
            border = "" if is_sds else "border:1.5px solid #2C6B33;"
            icon = "SDS" if is_sds else doc["label"].replace(" Assessment", "")
            url = html.escape(doc["delivery_url"], quote=True)
            buttons.append(
                f'<a href="{url}" style="display:inline-block;background:{bg};color:{fg};{border}'
                f'text-decoration:none;padding:9px 16px;border-radius:5px;font-size:13px;'
                f'font-weight:bold;margin:0 8px 8px 0;font-family:Arial,Helvetica,sans-serif;">'
                f'{icon}</a>'
            )
        code = html.escape(product.get("code", ""))
        name = html.escape(product.get("name", ""))
        title = f"{code} — {name}" if code and name else (code or name)
        product_cards.append(
            f'<div style="margin-bottom:14px;border:1px solid #e2eaef;border-radius:6px;overflow:hidden;">'
            f'<div style="background:#f0fdf4;padding:10px 16px;border-bottom:1px solid #e2eaef;">'
            f'<strong style="color:#17202a;font-size:14px;font-family:Arial,Helvetica,sans-serif;">{title}</strong>'
            f'</div>'
            f'<div style="padding:12px 16px;">{"".join(buttons)}</div>'
            f'</div>'
        )

    products_html = "".join(product_cards) if product_cards else (
        '<p style="color:#607080;font-size:14px;">No documents available for this contact.</p>'
    )
    pixel = (
        f'<img src="{html.escape(tracking_pixel_url, quote=True)}" '
        f'width="1" height="1" style="display:none;width:1px;height:1px;" alt="" />'
        if tracking_pixel_url else ""
    )
    safe_name = html.escape(contact_name or "there")
    safe_company = html.escape(company or "your site")
    safe_logo_url = html.escape(logo_url, quote=True) if logo_url else ""

    # Header: logo + wordmark side by side when logo URL is provided
    if safe_logo_url:
        header_inner = (
            '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td width="72" valign="middle" style="padding-right:16px;">'
            f'<img src="{safe_logo_url}" width="64" height="64" '
            f'style="display:block;border-radius:50%;border:2px solid rgba(255,255,255,0.25);" alt="CCS Logo" />'
            f'</td>'
            '<td valign="middle">'
            '<div style="color:#ffffff;font-size:20px;font-weight:800;letter-spacing:0.5px;'
            'font-family:Arial,Helvetica,sans-serif;">COMPLIANT CLEANING SUPPLIES</div>'
            '<div style="color:#a8d5b5;font-size:13px;margin-top:4px;font-family:Arial,Helvetica,sans-serif;">'
            'Safety Document Pack</div>'
            '</td></tr></table>'
        )
    else:
        header_inner = (
            '<div style="color:#ffffff;font-size:20px;font-weight:800;letter-spacing:0.5px;'
            'font-family:Arial,Helvetica,sans-serif;">COMPLIANT CLEANING SUPPLIES</div>'
            '<div style="color:#a8d5b5;font-size:13px;margin-top:4px;font-family:Arial,Helvetica,sans-serif;">'
            'Safety Document Pack</div>'
        )

    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '</head>'
        '<body style="margin:0;padding:0;background:#f0f4f7;font-family:Arial,Helvetica,sans-serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f7;">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table width="600" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(0,0,0,0.08);">'
        # Header
        f'<tr><td style="background:#2C6B33;padding:22px 32px;">{header_inner}</td></tr>'
        # Cover section
        '<tr><td style="background:#f5fbf6;padding:20px 32px 18px;border-bottom:2px solid #2C6B33;text-align:center;">'
        '<div style="font-size:17px;font-weight:800;color:#2C6B33;letter-spacing:0.3px;'
        'font-family:Arial,Helvetica,sans-serif;">Safety Data Sheet &amp; Risk Assessment</div>'
        '<div style="font-size:14px;font-weight:600;color:#17202a;margin-top:3px;'
        'font-family:Arial,Helvetica,sans-serif;">Compliance Pack</div>'
        f'<div style="font-size:12px;color:#607080;margin-top:8px;font-family:Arial,Helvetica,sans-serif;">'
        f'Prepared for: <strong style="color:#17202a;">{safe_name}</strong></div>'
        '</td></tr>'
        # Body
        '<tr><td style="padding:28px 32px;">'
        f'<p style="margin:0 0 14px;color:#17202a;font-size:15px;line-height:1.6;">Hi <strong>{safe_name}</strong>,</p>'
        f'<p style="margin:0 0 22px;color:#17202a;font-size:15px;line-height:1.6;">'
        f'Your Safety Data Sheets and Risk Assessments for <strong>{safe_company}</strong> are ready. '
        f'Click each document link below to acknowledge receipt and access the file.</p>'
        + (f'<div style="background:#fff8e1;border-left:4px solid #f59e0b;border-radius:4px;'
           f'padding:12px 16px;margin-bottom:20px;font-size:14px;color:#17202a;line-height:1.6;">'
           f'{cover_notice}</div>' if cover_notice else '')
        + f'{products_html}'
        '<p style="margin:20px 0 0;color:#607080;font-size:13px;line-height:1.6;">'
        'Questions? Contact us at '
        '<a href="mailto:info@compliantcs.com.au" style="color:#2C6B33;font-weight:bold;">info@compliantcs.com.au</a>'
        ' or call <strong>1300 314 491</strong>.</p>'
        '</td></tr>'
        # Footer
        '<tr><td style="background:#f5f8fa;padding:18px 32px;border-top:1px solid #e2eaef;">'
        '<table width="100%"><tr>'
        '<td style="color:#607080;font-size:12px;line-height:1.8;font-family:Arial,Helvetica,sans-serif;">'
        '<strong style="color:#2C6B33;">Compliant Cleaning Supplies</strong><br>'
        '1300 314 491 &nbsp;&middot;&nbsp; '
        '<a href="https://compliantcs.com.au" style="color:#2C6B33;text-decoration:none;">compliantcs.com.au</a>'
        '</td>'
        '<td align="right" style="font-size:11px;color:#aab8c4;font-family:Arial,Helvetica,sans-serif;">'
        'SDS Compliance Pack</td>'
        '</tr></table>'
        '</td></tr>'
        '</table>'
        '</td></tr></table>'
        f'{pixel}'
        '</body></html>'
    )


def _compose_message(
    preview: dict[str, Any],
    contact: dict[str, Any],
    products: list[dict[str, Any]],
    *,
    batch_id: str = "",
) -> dict[str, Any]:
    customer = preview.get("customer", {})
    contact_products = _products_for_contact(contact, products)
    documents = _message_documents(contact, contact_products, preview)
    # Only include products that have at least one document — skip silently if missing
    products_in_email = [
        p for p in contact_products
        if any(doc["product_code"] == p.get("code", "") for doc in documents)
    ]
    product_names = ", ".join(p.get("name", "") for p in products_in_email if p.get("name"))
    subject_product = product_names if len(product_names) <= 72 else f"{len(products_in_email)} selected products"
    subject = f"Your SDS Compliance Pack — {subject_product}"

    _base = os.getenv("CCS_PUBLIC_BASE_URL", "").rstrip("/")
    _secret = os.getenv("CCS_TRACKING_HMAC_SECRET", "")
    _contact_id = contact.get("id") or contact["email"]
    pixel_url = ""
    if _base and _secret and contact["email"]:
        pixel_url = email_open_pixel_url(
            public_base_url=_base,
            email=contact["email"],
            contact_id=_contact_id,
            secret=_secret,
            batch_id=batch_id,
        )

    logo_url = f"{_base}/api/assets/ccs_logo.png" if _base else ""
    email_html = _render_branded_html(
        contact_name=contact["name"],
        company=customer.get("company", ""),
        products_in_email=products_in_email,
        documents=documents,
        tracking_pixel_url=pixel_url,
        logo_url=logo_url,
    )

    return {
        "to": contact["email"],
        "name": contact["name"],
        "contact_id": contact.get("id", ""),
        "subject": subject,
        "html": email_html,
        "documents": documents,
    }


def _message_documents(
    contact: dict[str, Any],
    products: list[dict[str, Any]],
    preview: dict[str, Any],
) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    public_base_url = os.getenv("CCS_PUBLIC_BASE_URL", "").rstrip("/")
    secret = os.getenv("CCS_TRACKING_HMAC_SECRET", "")
    contact_id = contact.get("id") or contact["email"]

    for product in products:
        for label, key in [("SDS", "sds"), ("Risk Assessment", "risk_assessment")]:
            document = product.get(key, {})
            if document.get("matched") and document.get("url"):
                tracked = _tracked_document(
                    label=label,
                    document=document,
                    product=product,
                    contact_id=contact_id,
                    public_base_url=public_base_url,
                    secret=secret,
                )
                doc_key = (tracked["product_code"], tracked["label"], tracked["source_url"])
                if doc_key not in seen:
                    documents.append(tracked)
                    seen.add(doc_key)
        register = preview.get("register", {})
        register_url = register.get("url")
        if register_url:
            tracked = _tracked_document(
                label="Chemical Register",
                document={"filename": register_url.rsplit("/", 1)[-1] or "Chemical Register", "url": register_url},
                product=product,
                contact_id=contact_id,
                public_base_url=public_base_url,
                secret=secret,
            )
            doc_key = (tracked["product_code"], tracked["label"], tracked["source_url"])
            if doc_key not in seen:
                documents.append(tracked)
                seen.add(doc_key)
    return documents


def _products_for_contact(contact: dict[str, Any], products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    email = str(contact.get("email", "")).strip().lower()
    filtered: list[dict[str, Any]] = []
    for product in products:
        site_emails = product.get("site_emails")
        if not site_emails:
            filtered.append(product)
            continue
        normalized = {str(item).strip().lower() for item in site_emails if str(item).strip()}
        if email in normalized:
            filtered.append(product)
    return filtered


def _tracked_document(
    *,
    label: str,
    document: dict[str, Any],
    product: dict[str, Any],
    contact_id: str,
    public_base_url: str,
    secret: str,
) -> dict[str, str]:
    _url = str(document.get("url", ""))
    _url_uuid = (m.group(0) if (m := _UUID_RE.search(_url)) else "")
    document_id = str(document.get("id") or _url_uuid or product.get("code") or product.get("name") or _url)
    redirect_url = str(document.get("url", ""))
    chemical_name = str(product.get("name") or product.get("code") or "")
    delivery_url = redirect_url
    if public_base_url and secret:
        delivery_url = tracking_url(
            public_base_url=public_base_url,
            document_id=document_id,
            contact_id=contact_id,
            chemical_name=chemical_name,
            redirect_url=redirect_url,
            secret=secret,
        )
    return {
        "label": label,
        "document_id": document_id,
        "product_code": str(product.get("code", "")),
        "chemical_name": chemical_name,
        "filename": str(document.get("filename") or ""),
        "source_url": redirect_url,
        "delivery_url": delivery_url,
    }


def _normalize_contact(contact: dict[str, Any]) -> dict[str, Any]:
    first_name = str(contact.get("firstName") or contact.get("first_name") or "").strip()
    last_name = str(contact.get("lastName") or contact.get("last_name") or "").strip()
    fallback_name = " ".join(part for part in [first_name, last_name] if part).strip()
    return {
        "id": str(contact.get("id") or contact.get("contactId") or "").strip(),
        "name": str(contact.get("name") or fallback_name or "").strip(),
        "email": str(contact.get("email", "")).strip(),
        "tags": contact.get("tags") or [],
        "customFields": contact.get("customFields") or [],
    }


def _with_ghl_contact_id(contact: dict[str, Any]) -> dict[str, Any]:
    if contact.get("id") or contact.get("contactId"):
        return contact
    email = str(contact.get("email", "")).strip()
    contact_id = _find_or_create_ghl_contact_id(contact)
    if not contact_id:
        return contact
    return {**contact, "id": contact_id}


def contact_matches_product(contact: dict[str, Any], chemical_name: str) -> bool:
    needle = _compact_match_text(chemical_name)
    if not needle:
        return False

    tags = contact.get("tags") or []
    tag_text = " ".join(str(tag) for tag in tags)
    if needle in _compact_match_text(tag_text):
        return True

    custom_field_values = []
    for custom_field in contact.get("customFields") or []:
        value = custom_field.get("value") if isinstance(custom_field, dict) else custom_field
        if isinstance(value, list):
            custom_field_values.extend(str(item) for item in value)
        else:
            custom_field_values.append(str(value or ""))
    return needle in _compact_match_text(" ".join(custom_field_values))


def tag_slug_for_chemical(chemical_name: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in chemical_name).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"msds_{slug}"


def tracking_signature(document_id: str, contact_id: str, secret: str) -> str:
    payload = f"{document_id}:{contact_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()[:16]


def email_open_signature(email: str, contact_id: str, secret: str) -> str:
    payload = f"open:{email}:{contact_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()[:16]


def email_open_pixel_url(
    *,
    public_base_url: str,
    email: str,
    contact_id: str,
    secret: str,
    batch_id: str = "",
) -> str:
    params: dict[str, str] = {"email": email, "contact": contact_id, "sig": email_open_signature(email, contact_id, secret)}
    if batch_id:
        params["batch"] = batch_id
    return f"{public_base_url.rstrip('/')}/api/ccs-email-open?{urlencode(params)}"


def validate_email_open_signature(email: str, contact_id: str, signature: str) -> bool:
    secret = os.getenv("CCS_TRACKING_HMAC_SECRET", "")
    if not secret:
        return False
    expected = email_open_signature(email, contact_id, secret)
    return hmac.compare_digest(expected, signature)


def record_email_open(email: str, contact_id: str, user_agent: str, ip_address: str, *, batch_id: str = "") -> dict[str, Any]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        return {"status": "skipped", "reason": "Supabase not configured"}
    payload: dict[str, Any] = {
        "customer_email": email,
        "contact_id": contact_id,
        "opened_at": _now(),
        "user_agent": (user_agent or "")[:500],
        "ip_address": ip_address or "",
    }
    if batch_id:
        payload["batch_id"] = batch_id
    return _post_json(
        f"{supabase_url}/rest/v1/ccs_email_opens",
        payload,
        {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Prefer": "return=minimal",
        },
    )


def fetch_distribution_batches() -> dict[str, Any]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        return {"batches": [], "error": "Supabase not configured"}
    endpoint = f"{supabase_url}/rest/v1/ccs_distribution_batches?order=sent_at.desc"
    response = _get_json(endpoint, {"apikey": service_key, "Authorization": f"Bearer {service_key}"})
    body = response.get("body") or []
    return {"batches": body if isinstance(body, list) else []}


def fetch_document_opens(*, email: str = "", batch_id: str = "", limit: int = 200, offset: int = 0) -> dict[str, Any]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    table = os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distributions")
    if not supabase_url or not service_key:
        return {"rows": [], "error": "Supabase not configured"}
    filters = "&status=neq.dry_run"
    if email:
        filters += f"&customer_email=ilike.*{quote(email, safe='')}*"
    if batch_id:
        filters += f"&batch_id=eq.{quote(batch_id, safe='')}"
    endpoint = (
        f"{supabase_url}/rest/v1/{table}"
        f"?select=customer_email,ghl_contact_id,document_id,chemical_name,product_code,status,downloaded_at,batch_id"
        f"{filters}"
        f"&order=customer_email.asc,downloaded_at.desc.nullslast"
        f"&limit={limit}&offset={offset}"
    )
    response = _get_json(endpoint, {"apikey": service_key, "Authorization": f"Bearer {service_key}"})
    body = response.get("body") or []
    return {"rows": body if isinstance(body, list) else []}


def fetch_email_opens(*, batch_id: str = "", limit: int = 500, offset: int = 0) -> dict[str, Any]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        return {"opens": [], "error": "Supabase not configured"}
    filters = ""
    if batch_id:
        filters = f"&batch_id=eq.{quote(batch_id, safe='')}"
    endpoint = f"{supabase_url}/rest/v1/ccs_email_opens?order=opened_at.desc{filters}&limit={limit}&offset={offset}"
    response = _get_json(endpoint, {"apikey": service_key, "Authorization": f"Bearer {service_key}"})
    body = response.get("body") or []
    return {"opens": body if isinstance(body, list) else []}


def tracking_url(
    *,
    public_base_url: str,
    document_id: str,
    contact_id: str,
    chemical_name: str,
    redirect_url: str,
    secret: str,
) -> str:
    query = urlencode(
        {
            "doc": document_id,
            "contact": contact_id,
            "sig": tracking_signature(document_id, contact_id, secret),
            "chem": chemical_name,
            "redirect": redirect_url,
        }
    )
    return f"{public_base_url.rstrip('/')}/api/ccs-msds-track?{query}"


def validate_tracking_signature(document_id: str, contact_id: str, signature: str) -> bool:
    secret = os.getenv("CCS_TRACKING_HMAC_SECRET", "")
    if not secret:
        return False
    expected = tracking_signature(document_id, contact_id, secret)
    return hmac.compare_digest(expected, signature)


def record_download_acknowledgement(document_id: str, contact_id: str, chemical_name: str) -> dict[str, Any]:
    return {
        "supabase": _mark_distribution_downloaded(document_id, contact_id),
        "ghl": _tag_ghl_contact(contact_id, ["msds_acknowledged", tag_slug_for_chemical(chemical_name)]),
    }


def _compact_match_text(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _filter_contacts_by_products(contacts: list[dict[str, Any]], products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    product_names = [str(product.get("name") or product.get("code") or "") for product in products]
    return [
        contact
        for contact in contacts
        if any(contact_matches_product(contact, product_name) for product_name in product_names)
    ]


def _fetch_ghl_contacts() -> list[dict[str, Any]]:
    token = os.getenv("GHL_ACCESS_TOKEN") or os.getenv("GHL_API_KEY")
    location_id = os.getenv("GHL_LOCATION_ID")
    base_url = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
    if not token or not location_id:
        return []

    response = _post_json(
        f"{base_url}/contacts/search",
        {"locationId": location_id, "pageLimit": 100},
        _ghl_headers(token),
    )
    body = response.get("body") or {}
    if isinstance(body, dict):
        for key in ["contacts", "data", "items"]:
            if isinstance(body.get(key), list):
                return body[key]
    return body if isinstance(body, list) else []


def _send_messages_via_ghl(messages: list[dict[str, Any]]) -> dict[str, Any]:
    token = os.getenv("GHL_ACCESS_TOKEN") or os.getenv("GHL_API_KEY")
    location_id = os.getenv("GHL_LOCATION_ID", "")
    from_email = os.getenv("GHL_FROM_EMAIL", "")
    endpoint = os.getenv("GHL_EMAIL_ENDPOINT") or "https://services.leadconnectorhq.com/conversations/messages"
    if not token or not endpoint:
        return {"status": "skipped", "reason": "GHL_ACCESS_TOKEN and GHL_EMAIL_ENDPOINT required"}

    results = []
    for message in messages:
        contact_id = message.get("contact_id") or _find_or_create_ghl_contact_id({
            "email": message.get("to", ""),
            "name": message.get("name", ""),
        })
        if not contact_id:
            results.append({"status": "error", "reason": "GHL contact id required — contact upsert failed", "email": message.get("to", "")})
            continue
        message["contact_id"] = contact_id
        payload = {
            "type": "Email",
            "contactId": contact_id,
            "subject": message["subject"],
            "html": message["html"],
        }
        if message.get("attachments"):
            payload["attachments"] = message["attachments"]
        if location_id:
            payload["locationId"] = location_id
        if from_email:
            payload["emailFrom"] = from_email
        results.append(_post_json(endpoint, payload, _ghl_headers(token)))
    return {"status": "sent", "results": results}


def _ensure_documents_in_supabase(messages: list[dict[str, Any]]) -> None:
    """Upsert document stubs into ccs_documents so the FK on ccs_distributions is satisfied."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        return
    seen: set[str] = set()
    docs = []
    for message in messages:
        for doc in message.get("documents", []):
            url = str(doc.get("source_url", ""))
            m = _UUID_RE.search(url)
            if not m:
                continue
            doc_id = m.group(0)
            if doc_id in seen:
                continue
            seen.add(doc_id)
            docs.append({
                "id": doc_id,
                "product_code": doc.get("product_code", ""),
                "chemical_name": doc.get("chemical_name", ""),
                "branded_url": url,
            })
    if not docs:
        return
    _post_json(
        f"{supabase_url}/rest/v1/ccs_documents",
        docs,
        {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Prefer": "resolution=ignore-duplicates,return=minimal",
        },
    )


def _log_events_to_supabase(events: list[dict[str, Any]]) -> dict[str, Any]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    table = os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distributions")
    if not supabase_url or not service_key:
        return {"status": "skipped", "reason": "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required"}
    if not events:
        return {"status": "skipped", "reason": "no_events"}

    endpoint = f"{supabase_url}/rest/v1/{table}"
    return _post_json(
        endpoint,
        events,
        {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Prefer": "return=representation",
        },
    )


def _distribution_rows(messages: list[dict[str, Any]], *, dry_run: bool) -> list[dict[str, Any]]:
    return distribution_rows_for_supabase(
        messages,
        dry_run=dry_run,
        table=os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distributions"),
    )


def distribution_rows_for_supabase(
    messages: list[dict[str, Any]],
    *,
    dry_run: bool,
    table: str,
    batch_id: str = "",
) -> list[dict[str, Any]]:
    rows = []
    for message in messages:
        for document in message["documents"]:
            document_id = document["document_id"]
            row: dict[str, Any] = {
                "document_id": document_id,
                "customer_email": message["to"],
                "ghl_contact_id": message.get("contact_id") or document.get("contact_id", ""),
                "status": "dry_run" if dry_run else "sent",
                "chemical_name": document.get("chemical_name", ""),
                "product_code": document.get("product_code", ""),
            }
            if batch_id:
                row["batch_id"] = batch_id
            rows.append(row)
    return rows


def _mark_distribution_downloaded(document_id: str, contact_id: str) -> dict[str, Any]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    table = os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distributions")
    if not supabase_url or not service_key:
        return {"status": "skipped", "reason": "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required"}

    endpoint = (
        f"{supabase_url}/rest/v1/{table}"
        f"?document_id=eq.{quote(document_id, safe='')}"
        f"&ghl_contact_id=eq.{quote(contact_id, safe='')}"
    )
    return _request_json(
        endpoint,
        {"status": "downloaded", "downloaded_at": _now()},
        {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            # We don't need row payloads here; keeping responses minimal reduces noise and header bloat risk.
            "Prefer": "return=minimal",
        },
        method="PATCH",
    )


def _tag_ghl_contact(contact_id: str, tags: list[str]) -> dict[str, Any]:
    if not contact_id or "@" in contact_id:
        return {"status": "skipped", "reason": "GHL contact id required"}
    token = os.getenv("GHL_ACCESS_TOKEN") or os.getenv("GHL_API_KEY")
    base_url = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
    if not token:
        return {"status": "skipped", "reason": "GHL_ACCESS_TOKEN required"}
    return _post_json(f"{base_url}/contacts/{contact_id}/tags", {"tags": tags}, _ghl_headers(token))


def _find_or_create_ghl_contact_id(contact: dict[str, Any]) -> str:
    email = str(contact.get("email", "")).strip()
    existing_id = _find_ghl_contact_id_by_email(email)
    if existing_id:
        return existing_id
    token = os.getenv("GHL_ACCESS_TOKEN") or os.getenv("GHL_API_KEY")
    location_id = os.getenv("GHL_LOCATION_ID")
    base_url = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
    if not token or not location_id or not email:
        return ""

    name_parts = str(contact.get("name", "")).split()
    payload = {
        "locationId": location_id,
        "email": email,
        "firstName": name_parts[0] if name_parts else "",
        "lastName": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
    }
    response = _post_json(f"{base_url}/contacts/upsert", payload, _ghl_headers(token))
    body = response.get("body") or {}
    if isinstance(body, dict):
        contact_body = body.get("contact") if isinstance(body.get("contact"), dict) else body
        return str(contact_body.get("id") or contact_body.get("contactId") or "")
    return ""


def _find_ghl_contact_id_by_email(email: str) -> str:
    token = os.getenv("GHL_ACCESS_TOKEN") or os.getenv("GHL_API_KEY")
    location_id = os.getenv("GHL_LOCATION_ID")
    base_url = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
    if not token or not location_id or not email:
        return ""

    duplicate_url = f"{base_url}/contacts/search/duplicate?{urlencode({'locationId': location_id, 'email': email})}"
    response = _get_json(duplicate_url, _ghl_headers(token))
    body = response.get("body") or {}
    if isinstance(body, dict) and isinstance(body.get("contact"), dict):
        contact = body["contact"]
        return str(contact.get("id") or contact.get("contactId") or "")

    contacts: list[dict[str, Any]] = []
    if isinstance(body, dict):
        for key in ["contacts", "data", "items"]:
            if isinstance(body.get(key), list):
                contacts = body[key]
                break
    elif isinstance(body, list):
        contacts = body
    for contact in contacts:
        if str(contact.get("email", "")).strip().lower() == email.strip().lower():
            return str(contact.get("id") or contact.get("contactId") or "")
    return ""


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _ghl_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Version": os.getenv("GHL_API_VERSION", "2021-07-28"),
    }


def _post_json(url: str, payload: Any, headers: dict[str, str]) -> dict[str, Any]:
    return _request_json(url, payload, headers, method="POST")


def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "ccs-compliant-cleaning-platform/1.0",
            "Accept": "application/json",
            **headers,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return {
                "status": "ok",
                "status_code": response.status,
                "body": json.loads(body) if body else None,
            }
    except HTTPError as exc:
        return {"status": "error", "status_code": exc.code, "body": exc.read().decode("utf-8")}
    except URLError as exc:
        return {"status": "error", "reason": str(exc.reason)}


def _request_json(url: str, payload: Any, headers: dict[str, str], *, method: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": "ccs-compliant-cleaning-platform/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **headers,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return {
                "status": "ok",
                "status_code": response.status,
                "body": json.loads(body) if body else None,
            }
    except HTTPError as exc:
        return {"status": "error", "status_code": exc.code, "body": exc.read().decode("utf-8")}
    except URLError as exc:
        return {"status": "error", "reason": str(exc.reason)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
