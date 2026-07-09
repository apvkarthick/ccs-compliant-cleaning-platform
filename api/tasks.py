import fitz

from .celery_app import celery_app


@celery_app.task(name="ccs.ping")
def ping_task() -> dict[str, str]:
    return {
        "status": "ok",
        "worker": "ccs-worker",
        "pymupdf": fitz.VersionBind,
    }


@celery_app.task(bind=True, name="ccs.bulk_distribute", max_retries=2, time_limit=1800)
def bulk_distribute_task(self, preview: dict, dry_run: bool = True) -> dict:
    import os

    from .distribution import (
        _ensure_documents_in_supabase,
        _log_events_to_supabase,
        _normalize_contact,
        _send_messages_via_ghl,
        build_test_distribution,
        distribution_rows_for_supabase,
    )

    contacts = [_normalize_contact(c) for c in preview.get("contacts", [])]
    contacts = [c for c in contacts if c.get("email")]
    total = len(contacts)
    summary = {"sent": 0, "failed": 0, "dry_run": dry_run, "total": total, "done": 0}
    self.update_state(state="PROGRESS", meta=summary)

    for i, contact in enumerate(contacts):
        try:
            dist = build_test_distribution(preview=preview, contacts=[contact], dry_run=dry_run)
            if not dry_run and dist.get("messages"):
                _send_messages_via_ghl(dist["messages"])
                _ensure_documents_in_supabase(dist["messages"])
                rows = distribution_rows_for_supabase(
                    dist["messages"],
                    dry_run=False,
                    table=os.getenv("SUPABASE_DISTRIBUTION_TABLE", "ccs_distributions"),
                )
                if rows:
                    _log_events_to_supabase(rows)
            summary["sent"] += 1
        except Exception:
            summary["failed"] += 1
        summary["done"] = i + 1
        if (i + 1) % 50 == 0 or i == total - 1:
            self.update_state(state="PROGRESS", meta=dict(summary))

    return dict(summary)
