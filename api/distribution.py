from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def build_test_distribution(
    *,
    preview: dict[str, Any],
    contacts: list[dict[str, str]],
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
            },
        }
        for message in messages
    ]

    return {
        "dry_run": dry_run,
        "summary": {
            "contacts": len(valid_contacts),
            "products": len(products),
            "messages": len(messages),
        },
        "messages": messages,
        "audit_events": audit_events,
    }


def process_distribution(
    *,
    preview: dict[str, Any],
    contacts: list[dict[str, str]],
    dry_run: bool = True,
) -> dict[str, Any]:
    distribution = build_test_distribution(preview=preview, contacts=contacts, dry_run=dry_run)

    if dry_run:
        distribution["ghl"] = {"status": "skipped", "reason": "dry_run"}
        distribution["supabase"] = {"status": "skipped", "reason": "dry_run"}
        return distribution

    distribution["ghl"] = _send_messages_via_ghl(distribution["messages"])
    distribution["supabase"] = _log_events_to_supabase(distribution["audit_events"])
    return distribution


def _compose_message(
    preview: dict[str, Any],
    contact: dict[str, str],
    products: list[dict[str, Any]],
) -> dict[str, str]:
    customer = preview.get("customer", {})
    product_names = ", ".join(product.get("name", "") for product in products if product.get("name"))
    subject_product = product_names if len(product_names) <= 72 else f"{len(products)} selected products"
    subject = f"CCS SDS pack: {subject_product}"
    html_lines = [
        f"<p>Hi {contact['name'] or 'there'},</p>",
        f"<p>Please find the SDS and risk assessment links for {customer.get('company', 'your site')}.</p>",
        "<ul>",
    ]

    for product in products:
        html_lines.append("<li>")
        html_lines.append(f"<strong>{product.get('code', '')} - {product.get('name', '')}</strong><br>")
        html_lines.append(_doc_link("SDS", product.get("sds", {})))
        risk_link = _doc_link("Risk Assessment", product.get("risk_assessment", {}))
        if risk_link:
            html_lines.append("<br>")
            html_lines.append(risk_link)
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
        "subject": subject,
        "html": "".join(html_lines),
    }


def _doc_link(label: str, document: dict[str, Any]) -> str:
    if not document.get("matched") or not document.get("url"):
        return f"{label}: missing"
    return f'{label}: <a href="{document["url"]}">{document.get("filename") or "Open"}</a>'


def _normalize_contact(contact: dict[str, str]) -> dict[str, str]:
    return {
        "name": str(contact.get("name", "")).strip(),
        "email": str(contact.get("email", "")).strip(),
    }


def _send_messages_via_ghl(messages: list[dict[str, str]]) -> dict[str, Any]:
    token = os.getenv("GHL_ACCESS_TOKEN") or os.getenv("GHL_API_KEY")
    endpoint = os.getenv("GHL_EMAIL_ENDPOINT")
    if not token or not endpoint:
        return {"status": "skipped", "reason": "GHL_ACCESS_TOKEN and GHL_EMAIL_ENDPOINT required"}

    results = []
    for message in messages:
        payload = {
            "to": message["to"],
            "subject": message["subject"],
            "html": message["html"],
        }
        results.append(_post_json(endpoint, payload, {"Authorization": f"Bearer {token}"}))
    return {"status": "sent", "results": results}


def _log_events_to_supabase(events: list[dict[str, Any]]) -> dict[str, Any]:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    table = os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distribution_events")
    if not supabase_url or not service_key:
        return {"status": "skipped", "reason": "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required"}

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


def _post_json(url: str, payload: Any, headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="POST",
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
