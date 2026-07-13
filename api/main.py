import base64
import html
import json as _json
import os
import uuid
from pathlib import Path
from typing import Any

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from .distribution import (
    fetch_distribution_batches,
    fetch_document_opens,
    fetch_email_opens,
    process_distribution,
    record_download_acknowledgement,
    record_email_open,
    validate_email_open_signature,
    validate_tracking_signature,
)
from .excel_parser import list_source_documents, parse_client_workbook
from .rebrand import rebrand_sds
from .rebrand_pdf import rebrand_pdf
from .celery_app import celery_app
from .tasks import bulk_distribute_task, ping_task
from .workbooks import (
    disable_schedule,
    get_schedule,
    list_workbooks,
    load_workbook,
    make_customer_id,
    save_schedule,
    save_workbook,
)

load_dotenv()

APP_ROOT = Path(__file__).resolve().parents[1]
_TRACKING_GIF = base64.b64decode("R0lGODlhAQABAIAAAP///wAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw==")
SOURCE_DIR = APP_ROOT / "storage" / "source"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

def _load_jwt_secret(raw: str) -> tuple:
    """Return (key, algorithms) from a plain HS256 string or Supabase JWK JSON blob."""
    raw = raw.strip()
    if not raw or not raw.startswith("{"):
        return raw, ["HS256"]
    try:
        jwk = _json.loads(raw)
        key_obj = jwk.get("keys", [jwk])[0]
        kty = key_obj.get("kty", "")
        alg = key_obj.get("alg", "HS256")
        if kty == "EC":
            from jwt.algorithms import ECAlgorithm
            return ECAlgorithm.from_jwk(_json.dumps(key_obj)), [alg]
        if kty == "oct":
            k = key_obj.get("k", "")
            if k:
                pad = 4 - len(k) % 4
                return base64.urlsafe_b64decode(k + "=" * (pad % 4)), [alg]
    except Exception:
        pass
    return raw, ["HS256"]


_JWT_SECRET, _JWT_ALGORITHMS = _load_jwt_secret(os.getenv("SUPABASE_JWT_SECRET", ""))
_ALLOWED_EMAILS: set[str] = set(filter(None, os.getenv("ALLOWED_EMAILS", "").split(",")))

app = FastAPI(title="CCS Compliant Cleaning Platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_auth(authorization: str = Header(default="")) -> dict:
    if not _JWT_SECRET:
        return {}
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=_JWT_ALGORITHMS, audience="authenticated")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session — please log in again")
    if _ALLOWED_EMAILS and payload.get("email") not in _ALLOWED_EMAILS:
        raise HTTPException(status_code=403, detail="Access restricted to authorised users")
    return payload


class Contact(BaseModel):
    id: str = ""
    contactId: str = ""
    name: str = ""
    email: str
    tags: list[str] = Field(default_factory=list)
    customFields: list[dict[str, Any]] = Field(default_factory=list)


class DistributionRequest(BaseModel):
    preview: dict[str, Any]
    contacts: list[Contact] = Field(default_factory=list)
    dry_run: bool = True


class BulkDistributionRequest(BaseModel):
    preview: dict[str, Any]
    dry_run: bool = True


class ScheduleRequest(BaseModel):
    customer_id: str
    customer_name: str
    frequency: str  # weekly | biweekly | monthly | custom
    custom_interval_days: int | None = None
    dry_run: bool = True
    start_from: str | None = None  # ISO datetime for first send; omit to calculate from now


@app.get("/rebrand", response_class=HTMLResponse)
def rebrand_ui() -> HTMLResponse:
    return HTMLResponse((ASSETS_DIR / "rebrand.html").read_text(encoding="utf-8"))


@app.get("/distribution", response_class=HTMLResponse)
def distribution_ui() -> HTMLResponse:
    return HTMLResponse((ASSETS_DIR / "distribution.html").read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ccs-api"}


@app.post("/tasks/ping")
def enqueue_ping() -> dict[str, str]:
    task = ping_task.delay()
    return {"task_id": task.id, "status": "queued"}


@app.post("/workbook/preview")
async def preview_workbook(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload an .xlsx or .xlsm client workbook")
    workbook_bytes = await file.read()
    if not workbook_bytes:
        raise HTTPException(status_code=400, detail="Uploaded workbook is empty")
    result = parse_client_workbook(
        workbook_bytes,
        source_files=list_source_documents(SOURCE_DIR),
        public_base_url=os.getenv("CCS_PUBLIC_BASE_URL", ""),
    )
    customer_name = (result.get("customer") or {}).get("company", "")
    customer_id = ""
    if customer_name:
        customer_id = make_customer_id(customer_name)
        save_workbook(customer_id, customer_name, file.filename or "", result)
    result["_customer_id"] = customer_id
    return result


@app.get("/workbooks")
def list_saved_workbooks() -> list[dict[str, Any]]:
    return list_workbooks()


@app.get("/workbooks/{customer_id}")
def get_saved_workbook(customer_id: str) -> dict[str, Any]:
    wb = load_workbook(customer_id)
    if not wb:
        raise HTTPException(status_code=404, detail="Workbook not found")
    parsed: dict[str, Any] = wb.get("parsed_json") or {}
    parsed["_customer_id"] = customer_id
    return {
        "customer_id": customer_id,
        "customer_name": wb.get("customer_name", ""),
        "filename": wb.get("filename", ""),
        "uploaded_at": wb.get("uploaded_at", ""),
        "parsed_json": parsed,
    }


@app.post("/schedules")
def upsert_schedule(request: ScheduleRequest) -> dict[str, Any]:
    result = save_schedule(
        customer_id=request.customer_id,
        customer_name=request.customer_name,
        frequency=request.frequency,
        custom_interval_days=request.custom_interval_days,
        dry_run=request.dry_run,
        start_from=request.start_from,
    )
    return result


@app.get("/schedules/{customer_id}")
def get_schedule_endpoint(customer_id: str) -> dict[str, Any]:
    schedule = get_schedule(customer_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="No schedule found")
    return schedule


@app.delete("/schedules/{customer_id}")
def disable_schedule_endpoint(customer_id: str) -> dict[str, Any]:
    return disable_schedule(customer_id)


@app.post("/schedules/{customer_id}/send-now")
def send_schedule_now(customer_id: str) -> dict[str, Any]:
    """Immediately queue a bulk send for this client and advance the schedule's next_send_at."""
    schedule = get_schedule(customer_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="No schedule found for this client")
    wb = load_workbook(customer_id)
    if not wb or not wb.get("parsed_json"):
        raise HTTPException(status_code=404, detail="No saved workbook found — upload and preview first")
    parsed: dict[str, Any] = wb["parsed_json"]
    contacts = parsed.get("contacts", [])
    if not contacts:
        raise HTTPException(status_code=400, detail="Workbook has no contacts to send to")
    preview_slim = {k: v for k, v in parsed.items() if k != "contacts"}
    dry_run = schedule.get("dry_run", True)
    batch_id = f"sendnow_{customer_id}_{uuid.uuid4().hex[:8]}"
    task = bulk_distribute_task.delay(preview_slim, contacts, dry_run, batch_id)
    from .workbooks import advance_schedule as _advance
    _advance(customer_id, schedule.get("frequency", "weekly"), schedule.get("custom_interval_days"))
    return {"task_id": task.id, "status": "queued", "total": len(contacts), "batch_id": batch_id, "dry_run": dry_run}


class StressTestRequest(BaseModel):
    preview: dict[str, Any]
    contact_count: int = 100


@app.post("/distribution/stress-test")
def run_stress_test(request: StressTestRequest) -> dict[str, Any]:
    """Generate N fake contacts and run a dry-run bulk send as a load/stress test."""
    count = max(1, min(request.contact_count, 5000))
    fake_contacts = [
        {
            "id": f"stress-{i}",
            "name": f"Test Contact {i + 1}",
            "email": f"stress-test-{i + 1}@nxai-test.invalid",
            "tags": [],
            "customFields": [],
        }
        for i in range(count)
    ]
    preview_slim = {k: v for k, v in request.preview.items() if k != "contacts"}
    batch_id = f"stress_test_{count}_{uuid.uuid4().hex[:6]}"
    task = bulk_distribute_task.delay(preview_slim, fake_contacts, True, batch_id)
    return {"task_id": task.id, "status": "queued", "total": count, "batch_id": batch_id, "dry_run": True}


@app.post("/register/preview")
async def preview_register(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    return await preview_workbook(file)


@app.post("/distribution/send")
def send_bulk_distribution(request: BulkDistributionRequest) -> dict[str, Any]:
    contacts = request.preview.get("contacts") or []
    if not contacts:
        raise HTTPException(
            status_code=400,
            detail="No contacts found in workbook — parse the workbook first and ensure it has a customer sheet with email addresses",
        )
    batch_id = str(uuid.uuid4())
    # Strip contacts from preview — keeps the Redis task-arg payload small
    preview_slim = {k: v for k, v in request.preview.items() if k != "contacts"}
    task = bulk_distribute_task.delay(preview_slim, contacts, request.dry_run, batch_id)
    return {"task_id": task.id, "status": "queued", "total": len(contacts), "batch_id": batch_id}


@app.get("/distribution/batches")
def list_distribution_batches() -> dict[str, Any]:
    return fetch_distribution_batches()


@app.get("/distribution/status/{task_id}")
def get_distribution_status(task_id: str) -> dict[str, Any]:
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    out: dict[str, Any] = {"task_id": task_id, "state": result.state}
    if result.state == "PROGRESS":
        out["meta"] = result.info or {}
    elif result.successful():
        out["result"] = result.result
    elif result.failed():
        out["error"] = str(result.result)
    return out


@app.post("/distribution/test-send")
def test_send_distribution(
    request: DistributionRequest,
) -> dict[str, Any]:
    batch_id = str(uuid.uuid4()) if not request.dry_run else ""
    return process_distribution(
        preview=request.preview,
        contacts=[contact.model_dump() for contact in request.contacts],
        dry_run=request.dry_run,
        batch_id=batch_id,
    )


@app.get("/ccs-msds-track", response_class=HTMLResponse)
def track_msds_download(
    doc: str = Query(...),
    contact: str = Query(...),
    sig: str = Query(...),
    chem: str = Query(""),
    redirect: str = Query(...),
) -> HTMLResponse:
    if not validate_tracking_signature(doc, contact, sig):
        raise HTTPException(status_code=400, detail="Invalid or expired MSDS link")
    acknowledgement = record_download_acknowledgement(doc, contact, chem)
    safe_chem = html.escape(chem or "this MSDS document")
    safe_redirect = html.escape(redirect, quote=True)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CCS Safety Document</title>
  <style>
    body {{ margin:0;font-family:Arial,Helvetica,sans-serif;color:#17212b;background:#f5f8fa; }}
    header {{ background:#2C6B33;color:white;padding:20px 28px; }}
    main {{ max-width:860px;margin:36px auto;background:white;border:1px solid #d9e1e8;border-radius:8px;padding:28px; }}
    a.button {{ display:inline-block;margin-top:14px;background:#2C6B33;color:white;padding:12px 16px;border-radius:6px;text-decoration:none;font-weight:700; }}
    .muted {{ color:#607080; }}
  </style>
</head>
<body>
  <header><strong>COMPLIANT CLEANING SUPPLIES</strong></header>
  <main>
    <h1>Safety document ready</h1>
    <p>Your acknowledgement has been recorded for {safe_chem}.</p>
    <p><a class="button" href="{safe_redirect}">Open PDF</a></p>
    <p class="muted">1300 314 491 | compliantcs.com.au</p>
  </main>
</body>
</html>"""
    response = HTMLResponse(page)
    # Keep header intentionally small so nginx never rejects oversized upstream headers.
    ack_status = "ok"
    if any(
        isinstance(part, dict) and part.get("status") == "error"
        for part in [acknowledgement.get("supabase"), acknowledgement.get("ghl")]
    ):
        ack_status = "error"
    response.headers["X-CCS-Acknowledgement"] = ack_status
    return response


@app.get("/ccs-email-open")
def track_email_open(
    request: Request,
    email: str = Query(default=""),
    contact: str = Query(default=""),
    sig: str = Query(default=""),
    batch: str = Query(default=""),
) -> Response:
    if email and contact and sig and validate_email_open_signature(email, contact, sig):
        ua = request.headers.get("user-agent", "")
        ip = request.client.host if request.client else ""
        record_email_open(email, contact, ua, ip, batch_id=batch)
    return Response(
        content=_TRACKING_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/document-opens")
def get_document_opens(
    email: str = Query(default=""),
    batch_id: str = Query(default=""),
    limit: int = Query(default=200),
    offset: int = Query(default=0),
) -> dict[str, Any]:
    return fetch_document_opens(email=email, batch_id=batch_id, limit=limit, offset=offset)


@app.get("/email-opens")
def get_email_opens(
    # _: dict = Depends(require_auth),
    batch_id: str = Query(default=""),
    limit: int = Query(default=500),
    offset: int = Query(default=0),
) -> dict[str, Any]:
    return fetch_email_opens(batch_id=batch_id, limit=limit, offset=offset)


@app.post("/rebrand/sds")
async def rebrand_sds_endpoint(
    file: UploadFile = File(...),
    sds_date: str = Query(default="", description="SDS date override DD/MM/YYYY"),
) -> Response:
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Upload a .docx SDS file")
    docx_bytes = await file.read()
    if not docx_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    rebranded_docx, summary = rebrand_sds(docx_bytes, sds_date or None)

    stem = Path(file.filename).stem
    return Response(
        content=rebranded_docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}_ccs_branded.docx"',
            "X-CCS-Changes": str(len(summary.get("changes", []))),
            "X-CCS-Old-Supplier": summary.get("old_supplier", ""),
            "Access-Control-Expose-Headers": "X-CCS-Changes, X-CCS-Old-Supplier",
        },
    )


@app.post("/rebrand/pdf")
async def rebrand_pdf_endpoint(
    file: UploadFile = File(...),
    sds_date: str = Query(default="", description="SDS date override DD/MM/YYYY"),
) -> Response:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a .pdf SDS file")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    rebranded, summary = rebrand_pdf(pdf_bytes, sds_date or None)
    stem = Path(file.filename).stem
    return Response(
        content=rebranded,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}_ccs_branded.pdf"',
            "X-CCS-Changes": str(len(summary.get("changes", []))),
            "X-CCS-Old-Supplier": summary.get("old_supplier", ""),
            "Access-Control-Expose-Headers": "X-CCS-Changes, X-CCS-Old-Supplier",
        },
    )


@app.get("/documents/source/{filename:path}")
def get_source_document(filename: str) -> FileResponse:
    path = (SOURCE_DIR / filename).resolve()
    if SOURCE_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(path)
