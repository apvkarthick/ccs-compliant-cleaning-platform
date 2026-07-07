import base64
import html
import json as _json
import os
from pathlib import Path
from typing import Any

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from .distribution import process_distribution, record_download_acknowledgement, validate_tracking_signature
from .excel_parser import list_source_documents, parse_client_workbook
from .rebrand import rebrand_sds
from .rebrand_pdf import rebrand_pdf
from .tasks import ping_task

load_dotenv()

APP_ROOT = Path(__file__).resolve().parents[1]
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
    return parse_client_workbook(
        workbook_bytes,
        source_files=list_source_documents(SOURCE_DIR),
        public_base_url=os.getenv("CCS_PUBLIC_BASE_URL", ""),
    )


@app.post("/register/preview")
async def preview_register(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    return await preview_workbook(file)


@app.post("/distribution/test-send")
def test_send_distribution(
    request: DistributionRequest,
) -> dict[str, Any]:
    return process_distribution(
        preview=request.preview,
        contacts=[contact.model_dump() for contact in request.contacts],
        dry_run=request.dry_run,
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
    response.headers["X-CCS-Acknowledgement"] = str(acknowledgement)
    return response


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
