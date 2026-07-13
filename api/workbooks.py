from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _supa_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def _supa_url() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def _headers() -> dict[str, str]:
    key = _supa_key()
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _get(url: str) -> dict:
    req = Request(url, headers=_headers())
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
            return {"status": r.status, "body": json.loads(raw) if raw else []}
    except HTTPError as e:
        return {"status": e.code, "error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def _post(url: str, data: Any, extra_headers: dict | None = None) -> dict:
    body = json.dumps(data).encode()
    h = {**_headers(), "Content-Type": "application/json", **(extra_headers or {})}
    req = Request(url, data=body, headers=h, method="POST")
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
            return {"status": r.status, "body": json.loads(raw) if raw else {}}
    except HTTPError as e:
        return {"status": e.code, "error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def _patch(url: str, data: Any) -> dict:
    body = json.dumps(data).encode()
    h = {**_headers(), "Content-Type": "application/json", "Prefer": "return=minimal"}
    req = Request(url, data=body, headers=h, method="PATCH")
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
            return {"status": r.status, "body": json.loads(raw) if raw else {}}
    except HTTPError as e:
        return {"status": e.code, "error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"status": 0, "error": str(e)}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_customer_id(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_-]+", "_", slug)
    return slug.strip("_") or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_send(frequency: str, custom_days: int | None, from_dt: datetime | None = None) -> str:
    base = from_dt or datetime.now(timezone.utc)
    days = {"weekly": 7, "biweekly": 14, "monthly": 30}.get(frequency) or (custom_days or 7)
    return (base + timedelta(days=days)).isoformat()


# ─── Workbooks ────────────────────────────────────────────────────────────────

def save_workbook(customer_id: str, customer_name: str, filename: str, parsed_json: dict) -> dict:
    base = _supa_url()
    if not base or not _supa_key():
        return {"status": "skipped", "reason": "Supabase not configured"}
    return _post(
        f"{base}/rest/v1/ccs_workbooks",
        {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "filename": filename,
            "parsed_json": parsed_json,
            "uploaded_at": _now_iso(),
        },
        {"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def list_workbooks() -> list[dict]:
    base = _supa_url()
    if not base or not _supa_key():
        return []
    url = f"{base}/rest/v1/ccs_workbooks?select=customer_id,customer_name,filename,uploaded_at&order=uploaded_at.desc"
    body = _get(url).get("body", [])
    return body if isinstance(body, list) else []


def load_workbook(customer_id: str) -> dict | None:
    base = _supa_url()
    if not base or not _supa_key():
        return None
    url = f"{base}/rest/v1/ccs_workbooks?customer_id=eq.{quote(customer_id)}&limit=1"
    body = _get(url).get("body", [])
    return body[0] if isinstance(body, list) and body else None


# ─── Schedules ────────────────────────────────────────────────────────────────

def save_schedule(
    customer_id: str,
    customer_name: str,
    frequency: str,
    custom_interval_days: int | None,
    active: bool = True,
    dry_run: bool = True,
    start_from: str | None = None,
) -> dict:
    base = _supa_url()
    if not base or not _supa_key():
        return {"status": "skipped", "reason": "Supabase not configured"}
    now = datetime.now(timezone.utc)
    next_send = start_from or _next_send(frequency, custom_interval_days, now)
    return _post(
        f"{base}/rest/v1/ccs_schedules",
        {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "frequency": frequency,
            "custom_interval_days": custom_interval_days,
            "next_send_at": next_send,
            "active": active,
            "dry_run": dry_run,
            "updated_at": now.isoformat(),
        },
        {"Prefer": "resolution=merge-duplicates,return=representation"},
    )


def get_schedule(customer_id: str) -> dict | None:
    base = _supa_url()
    if not base or not _supa_key():
        return None
    url = f"{base}/rest/v1/ccs_schedules?customer_id=eq.{quote(customer_id)}&limit=1"
    body = _get(url).get("body", [])
    return body[0] if isinstance(body, list) and body else None


def disable_schedule(customer_id: str) -> dict:
    base = _supa_url()
    if not base or not _supa_key():
        return {"status": "skipped"}
    return _patch(
        f"{base}/rest/v1/ccs_schedules?customer_id=eq.{quote(customer_id)}",
        {"active": False, "updated_at": _now_iso()},
    )


def get_due_schedules() -> list[dict]:
    base = _supa_url()
    if not base or not _supa_key():
        return []
    now_iso = quote(datetime.now(timezone.utc).isoformat())
    url = f"{base}/rest/v1/ccs_schedules?active=eq.true&next_send_at=lte.{now_iso}&select=*"
    body = _get(url).get("body", [])
    return body if isinstance(body, list) else []


def advance_schedule(customer_id: str, frequency: str, custom_interval_days: int | None) -> dict:
    base = _supa_url()
    if not base or not _supa_key():
        return {"status": "skipped"}
    now = datetime.now(timezone.utc)
    return _patch(
        f"{base}/rest/v1/ccs_schedules?customer_id=eq.{quote(customer_id)}",
        {
            "last_sent_at": now.isoformat(),
            "next_send_at": _next_send(frequency, custom_interval_days, now),
            "updated_at": now.isoformat(),
        },
    )
