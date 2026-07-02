from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def build_test_distribution(
    *,
    preview: dict[str, Any],
    contacts: list[dict[str, Any]],
    dry_run: bool = True,
) -> dict[str, Any]:
    valid_contacts = [_normalize_contact(contact) for contact in contacts]
    valid_contacts = [contact for contact in valid_contacts if contact["email"]]
    products = preview.get("products", [])
    messages = [_compose_message(preview, contact, products) for contact in valid_contacts]
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
) -> dict[str, Any]:
    selected_contacts = contacts or _filter_contacts_by_products(_fetch_ghl_contacts(), preview.get("products", []))
    if not dry_run:
        selected_contacts = [_with_ghl_contact_id(contact) for contact in selected_contacts]
    distribution = build_test_distribution(preview=preview, contacts=selected_contacts, dry_run=dry_run)

    if dry_run:
        distribution["ghl"] = {"status": "skipped", "reason": "dry_run"}
        distribution["supabase"] = {"status": "skipped", "reason": "dry_run"}
        return distribution

    distribution["ghl"] = _send_messages_via_ghl(distribution["messages"])
    distribution["supabase"] = _log_events_to_supabase(distribution["distribution_rows"])
    return distribution


def _compose_message(
    preview: dict[str, Any],
    contact: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    customer = preview.get("customer", {})
    product_names = ", ".join(product.get("name", "") for product in products if product.get("name"))
    subject_product = product_names if len(product_names) <= 72 else f"{len(products)} selected products"
    subject = f"CCS SDS pack: {subject_product}"
    documents = _message_documents(contact, products, preview)
    html_lines = [
        f"<p>Hi {html.escape(contact['name'] or 'there')},</p>",
        f"<p>Please find the SDS, chemical-register, and risk-assessment links for {html.escape(customer.get('company', 'your site'))}.</p>",
        "<ul>",
    ]

    for product in products:
        html_lines.append("<li>")
        html_lines.append(f"<strong>{html.escape(product.get('code', ''))} - {html.escape(product.get('name', ''))}</strong>")
        product_docs = [doc for doc in documents if doc["product_code"] == product.get("code", "")]
        if product_docs:
            html_lines.append("<ul>")
            for document in product_docs:
                html_lines.append(
                    f'<li>{html.escape(document["label"])}: '
                    f'<a href="{html.escape(document["delivery_url"], quote=True)}">'
                    f'{html.escape(document["filename"] or "Open document")}</a></li>'
                )
            html_lines.append("</ul>")
        else:
            html_lines.append("<br>Documents: missing")
        html_lines.append("</li>")

    html_lines.extend(
        [
            "</ul>",
            "<p>Regards,<br>Compliant Cleaning Supplies</p>",
        ]
    )

    return {
        "to": contact["email"],
        "name": contact["name"],
        "contact_id": contact.get("id", ""),
        "subject": subject,
        "html": "".join(html_lines),
        "documents": documents,
    }


def _message_documents(
    contact: dict[str, Any],
    products: list[dict[str, Any]],
    preview: dict[str, Any],
) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    public_base_url = os.getenv("CCS_PUBLIC_BASE_URL", "").rstrip("/")
    secret = os.getenv("CCS_TRACKING_HMAC_SECRET", "")
    contact_id = contact.get("id") or contact["email"]

    for product in products:
        for label, key in [("SDS", "sds"), ("Risk Assessment", "risk_assessment")]:
            document = product.get(key, {})
            if document.get("matched") and document.get("url"):
                documents.append(
                    _tracked_document(
                        label=label,
                        document=document,
                        product=product,
                        contact_id=contact_id,
                        public_base_url=public_base_url,
                        secret=secret,
                    )
                )
        register = preview.get("register", {})
        register_url = register.get("url")
        if register_url:
            documents.append(
                _tracked_document(
                    label="Chemical Register",
                    document={"filename": register_url.rsplit("/", 1)[-1] or "Chemical Register", "url": register_url},
                    product=product,
                    contact_id=contact_id,
                    public_base_url=public_base_url,
                    secret=secret,
                )
            )
    return documents


def _tracked_document(
    *,
    label: str,
    document: dict[str, Any],
    product: dict[str, Any],
    contact_id: str,
    public_base_url: str,
    secret: str,
) -> dict[str, str]:
    document_id = str(document.get("id") or product.get("code") or product.get("name") or document.get("url"))
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
    contact_id = _find_ghl_contact_id_by_email(email)
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
    endpoint = os.getenv("GHL_EMAIL_ENDPOINT") or "https://services.leadconnectorhq.com/conversations/messages"
    if not token or not endpoint:
        return {"status": "skipped", "reason": "GHL_ACCESS_TOKEN and GHL_EMAIL_ENDPOINT required"}

    results = []
    for message in messages:
        contact_id = message.get("contact_id") or _find_ghl_contact_id_by_email(message.get("to", ""))
        if contact_id:
            message["contact_id"] = contact_id
        payload = {
            "type": "Email",
            "subject": message["subject"],
            "html": message["html"],
        }
        if contact_id:
            payload["contactId"] = contact_id
        if message.get("to"):
            payload["emailTo"] = message["to"]
        if not contact_id:
            results.append({"status": "error", "reason": "GHL contact id required", "email": message.get("to", "")})
            continue
        results.append(_post_json(endpoint, payload, _ghl_headers(token)))
    return {"status": "sent", "results": results}


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
    rows = []
    for message in messages:
        for document in message["documents"]:
            rows.append(
                {
                    "document_id": document["document_id"],
                    "customer_email": message["to"],
                    "ghl_contact_id": message.get("contact_id") or document.get("contact_id", ""),
                    "status": "dry_run" if dry_run else "sent",
                }
            )
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
            "Prefer": "return=representation",
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


def _find_ghl_contact_id_by_email(email: str) -> str:
    token = os.getenv("GHL_ACCESS_TOKEN") or os.getenv("GHL_API_KEY")
    location_id = os.getenv("GHL_LOCATION_ID")
    base_url = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
    if not token or not location_id or not email:
        return ""

    response = _post_json(
        f"{base_url}/contacts/search",
        {"locationId": location_id, "query": email, "pageLimit": 10},
        _ghl_headers(token),
    )
    body = response.get("body") or {}
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


def _ghl_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Version": os.getenv("GHL_API_VERSION", "2021-07-28"),
    }


def _post_json(url: str, payload: Any, headers: dict[str, str]) -> dict[str, Any]:
    return _request_json(url, payload, headers, method="POST")


def _request_json(url: str, payload: Any, headers: dict[str, str], *, method: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
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
