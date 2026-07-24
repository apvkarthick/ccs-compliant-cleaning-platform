import fitz

from .celery_app import celery_app


@celery_app.task(name="ccs.run_scheduled_distributions")
def run_scheduled_distributions() -> dict:
    """Celery Beat task: find due schedules, trigger bulk sends, advance next_send_at."""
    from datetime import datetime, timezone

    from .workbooks import advance_schedule, get_due_schedules, load_workbook

    due = get_due_schedules()
    if not due:
        return {"triggered": 0, "errors": []}

    triggered = 0
    errors: list[dict] = []
    for schedule in due:
        customer_id = schedule.get("customer_id", "")
        try:
            dry_run = schedule.get("dry_run", True)
            batch_id = f"sched_{customer_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            if customer_id == "ccs_sites":
                site_distribution_task.delay(dry_run=dry_run, batch_id=batch_id)
            else:
                wb = load_workbook(customer_id)
                if not wb or not wb.get("parsed_json"):
                    errors.append({"customer_id": customer_id, "error": "No saved workbook found"})
                    continue
                parsed = wb["parsed_json"]
                contacts = parsed.get("contacts", [])
                if not contacts:
                    errors.append({"customer_id": customer_id, "error": "No contacts in workbook"})
                    continue
                preview_slim = {k: v for k, v in parsed.items() if k != "contacts"}
                bulk_distribute_task.delay(preview_slim, contacts, dry_run, batch_id)
            advance_schedule(customer_id, schedule.get("frequency", "weekly"), schedule.get("custom_interval_days"))
            triggered += 1
        except Exception as exc:
            errors.append({"customer_id": customer_id, "error": str(exc)})

    return {"triggered": triggered, "errors": errors}


@celery_app.task(name="ccs.detect_new_products")
def detect_new_products_task() -> dict:
    """Daily beat task: detect and record new product–site pairs.
    No email sent — CCS team reviews and actions via /new-products page."""
    from .site_distribution import detect_and_record_new_products
    return detect_and_record_new_products()


@celery_app.task(name="ccs.send_sds_expiry_alerts")
def send_sds_expiry_alerts_task() -> dict:
    """Monthly beat task (first working day of month, 9am AEST): SDS expiry alert."""
    from datetime import datetime, timezone
    from .site_distribution import (
        _is_first_weekday_of_month_aest,
        get_expiring_sds,
        _render_expiry_email,
        send_internal_notification,
    )
    if not _is_first_weekday_of_month_aest():
        return {"skipped": True, "reason": "not first weekday of month"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    expiring = get_expiring_sds(days_ahead=60)
    if expiring:
        html = _render_expiry_email(expiring, today)
        send_internal_notification(
            f"SDS expiry alert — {len(expiring)} product(s) expiring within 60 days ({today})",
            html,
        )
    return {"expiring_count": len(expiring)}


@celery_app.task(name="ccs.send_hold_list_notification")
def send_hold_list_notification_task() -> dict:
    """Monthly beat task (first working day of month, 9am AEST): hold list notification."""
    from datetime import datetime, timezone
    from .site_distribution import (
        _is_first_weekday_of_month_aest,
        get_held_sites,
        get_excluded_sites,
        _render_hold_list_email,
        send_internal_notification,
    )
    if not _is_first_weekday_of_month_aest():
        return {"skipped": True, "reason": "not first weekday of month"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    held = get_held_sites()
    excluded = get_excluded_sites()
    html = _render_hold_list_email(held, today, excluded)
    send_internal_notification(
        f"Monthly Hold & Exclusion List — {len(held)} on hold, {len(excluded)} excluded ({today})", html
    )
    return {"held_count": len(held), "excluded_count": len(excluded)}


@celery_app.task(name="ccs.auto_sharepoint_pull")
def auto_sharepoint_pull_task() -> dict:
    """Beat task: pull latest import files from SharePoint and run full import pipeline.

    Schedule entry exists in celery_app.py but is commented out — activate by
    uncommenting the 'auto-sharepoint-pull' key in beat_schedule.
    """
    from .sharepoint import pull_all_import_files, SharePointError
    from .site_distribution import import_mapping

    try:
        files = pull_all_import_files()
    except SharePointError as e:
        return {"ok": False, "error": f"SharePoint: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Unexpected: {e}"}

    sp_errors = files.pop("_errors", {})

    def _bytes(key: str) -> bytes | None:
        entry = files.get(key)
        return entry[1] if isinstance(entry, tuple) else None

    pulled = {k: v[0] if isinstance(v, tuple) else None for k, v in files.items()}
    try:
        result = import_mapping(
            mapping_bytes=_bytes("mapping"),
            sds_bytes=_bytes("sds_links"),
            risk_bytes=_bytes("risk_links"),
            grouping_bytes=_bytes("stock_groups"),
            register_bytes=_bytes("chemical_register"),
        )
    except Exception as e:
        return {"ok": False, "pulled_files": pulled, "error": f"Import failed: {e}"}

    return {"ok": True, "pulled_files": pulled, "sp_errors": sp_errors, **result}


@celery_app.task(name="ccs.ping")
def ping_task() -> dict[str, str]:
    return {
        "status": "ok",
        "worker": "ccs-worker",
        "pymupdf": fitz.VersionBind,
    }


@celery_app.task(bind=True, name="ccs.site_distribute", max_retries=2, time_limit=7200)
def site_distribution_task(
    self,
    dry_run: bool = True,
    batch_id: str = "",
    skip_sent_since: str = "",
    daily_cap: int = 0,
    batch_start: str = "",
) -> dict:
    """Send SDS/Risk compliance emails to all non-excluded sites from ccs_site_mapping.

    daily_cap: max emails to send today (0 = no cap). Reads CCS_DAILY_EMAIL_CAP env var
               as default if not passed. Remaining sites auto-scheduled for next day.
    batch_start: ISO datetime of the original bulk-send trigger — used as skip_sent_since
                 for continuation tasks so already-sent sites are always excluded.
    skip_sent_since: ISO datetime — skip sites with last_sent_at >= this value (resume mode).
    """
    import os
    import time
    from datetime import datetime, timezone

    from .site_distribution import (
        _update_last_sent_at,
        compose_site_email,
        load_lookup_maps,
        resolve_docs_for_site,
        _sb_get_all,
    )
    from .distribution import _find_or_create_ghl_contact_id, _send_messages_via_ghl

    public_base = os.getenv("CCS_PUBLIC_BASE_URL", "").rstrip("/")
    tracking_secret = os.getenv("CCS_TRACKING_HMAC_SECRET", "")

    # Resolve daily cap: param > env var > 0 (uncapped)
    if daily_cap <= 0:
        daily_cap = int(os.getenv("CCS_DAILY_EMAIL_CAP", "0") or 0)

    # batch_start is the anchor for "already sent in this campaign" — set once on first run
    if not batch_start:
        batch_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # skip_sent_since defaults to batch_start for continuation runs
    effective_skip = skip_sent_since or batch_start

    excl_set = {r["accno"] for r in _sb_get_all("ccs_site_exclusions", "select=accno")}
    held_set = {r["accno"] for r in _sb_get_all("ccs_site_holds", "select=accno")}
    skip_set = excl_set | held_set
    all_sites = _sb_get_all("ccs_site_mapping", "select=*&order=name.asc")
    sites = [s for s in all_sites if s.get("accno") not in skip_set]

    # Exclude sites already sent in this campaign
    sites = [s for s in sites if not s.get("last_sent_at") or s["last_sent_at"] < batch_start]

    # Also apply manual resume filter if explicitly set
    if skip_sent_since and skip_sent_since != batch_start:
        sites = [s for s in sites if not s.get("last_sent_at") or s["last_sent_at"] < skip_sent_since]

    # Count emails already sent today (for cap enforcement)
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    sent_today_already = sum(
        1 for s in all_sites
        if (s.get("last_sent_at") or "") >= today_start
    )

    # Determine how many we can send right now
    if daily_cap > 0:
        remaining_today = max(0, daily_cap - sent_today_already)
        sites_this_run = sites[:remaining_today]
        sites_queued = sites[remaining_today:]
    else:
        sites_this_run = sites
        sites_queued = []

    sds_map, risk_map, group_fallback, risk_required_set, register_codes = load_lookup_maps()

    summary: dict = {
        "sent": 0, "failed": 0, "skipped": 0, "dry_run": dry_run,
        "total": len(sites_this_run), "done": 0,
        "queued_for_tomorrow": len(sites_queued),
        "daily_cap": daily_cap, "sent_today_already": sent_today_already,
        "batch_start": batch_start,
    }
    self.update_state(state="PROGRESS", meta=dict(summary))

    for i, site in enumerate(sites_this_run):
        accno = site.get("accno", "")
        try:
            stockcodes = site.get("stockcodes") or []
            docs = resolve_docs_for_site(stockcodes, sds_map, risk_map, group_fallback, risk_required_set, register_codes)
            emails = [e for e in (site.get("emails") or []) if e]

            if not docs or not emails:
                summary["skipped"] += 1
            else:
                for email_addr in emails:
                    msg = compose_site_email(
                        site, docs, email_addr,
                        batch_id=batch_id,
                        public_base_url=public_base,
                        tracking_secret=tracking_secret,
                    )
                    if dry_run:
                        summary["sent"] += 1
                        continue
                    contact_id = _find_or_create_ghl_contact_id({"email": email_addr, "name": site.get("name", "")})
                    if contact_id:
                        msg["contact_id"] = contact_id
                    ghl = _send_messages_via_ghl([msg])
                    if ghl.get("status") == "sent":
                        summary["sent"] += 1
                        _update_last_sent_at(accno)
                    else:
                        summary["failed"] += 1
                    time.sleep(0.3)
        except Exception as exc:
            summary["failed"] += 1
            summary.setdefault("exceptions", []).append({"accno": accno, "error": str(exc)})

        summary["done"] = i + 1
        if (i + 1) % 25 == 0 or i == len(sites_this_run) - 1:
            self.update_state(state="PROGRESS", meta=dict(summary))

    # Schedule continuation for tomorrow if sites remain and not a dry run
    if sites_queued and not dry_run:
        site_distribution_task.apply_async(
            kwargs={
                "dry_run": False,
                "batch_id": batch_id,
                "daily_cap": daily_cap,
                "batch_start": batch_start,
            },
            countdown=86400,  # 24 hours
        )
        summary["continuation_scheduled"] = True

    return dict(summary)


@celery_app.task(bind=True, name="ccs.bulk_distribute", max_retries=2, time_limit=3600)
def bulk_distribute_task(self, preview: dict, contacts: list, dry_run: bool = True, batch_id: str = "") -> dict:
    import os
    import time

    from .distribution import (
        _ensure_documents_in_supabase,
        _log_events_to_supabase,
        _normalize_contact,
        _send_messages_via_ghl,
        _with_ghl_contact_id,
        build_test_distribution,
        distribution_rows_for_supabase,
    )

    contacts = [_normalize_contact(c) for c in contacts]
    contacts = [c for c in contacts if c.get("email")]
    total = len(contacts)
    summary = {"sent": 0, "failed": 0, "dry_run": dry_run, "total": total, "done": 0}
    self.update_state(state="PROGRESS", meta=summary)

    # Pre-group products by contact email for O(1) lookup — avoids O(contacts × products) per iteration
    all_products = preview.get("products", [])
    universal = [p for p in all_products if not p.get("site_emails")]
    by_email: dict[str, list] = {}
    for p in all_products:
        for em in (p.get("site_emails") or []):
            by_email.setdefault(str(em).strip().lower(), []).append(p)

    for i, contact in enumerate(contacts):
        try:
            email_key = str(contact.get("email", "")).strip().lower()
            contact_products = universal + by_email.get(email_key, [])
            contact_preview = {**preview, "products": contact_products}

            if not dry_run:
                contact = _with_ghl_contact_id(contact)
            dist = build_test_distribution(preview=contact_preview, contacts=[contact], dry_run=dry_run, batch_id=batch_id)
            if not dry_run and dist.get("messages"):
                ghl_result = _send_messages_via_ghl(dist["messages"])
                if ghl_result.get("status") == "skipped":
                    summary["failed"] += 1
                    summary.setdefault("ghl_errors", []).append({
                        "email": contact.get("email"),
                        "errors": [{"reason": ghl_result.get("reason", "GHL skipped — check GHL_ACCESS_TOKEN and GHL_LOCATION_ID env vars on the worker")}],
                    })
                else:
                    ghl_errors = [r for r in (ghl_result.get("results") or []) if r.get("status") == "error"]
                    if ghl_errors:
                        summary["failed"] += 1
                        summary.setdefault("ghl_errors", []).append({
                            "email": contact.get("email"),
                            "errors": ghl_errors,
                        })
                    else:
                        _ensure_documents_in_supabase(dist["messages"])
                        rows = distribution_rows_for_supabase(
                            dist["messages"],
                            dry_run=False,
                            table=os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distributions"),
                            batch_id=batch_id,
                        )
                        if rows:
                            _log_events_to_supabase(rows)
                        summary["sent"] += 1
                # Rate limit: pause between GHL calls (skip after last contact)
                if i < total - 1:
                    time.sleep(0.5)
            else:
                summary["sent"] += 1
        except Exception as exc:
            summary["failed"] += 1
            summary.setdefault("exceptions", []).append({"email": contact.get("email"), "error": str(exc)})
        summary["done"] = i + 1
        if (i + 1) % 50 == 0 or i == total - 1:
            self.update_state(state="PROGRESS", meta=dict(summary))

    return dict(summary)
