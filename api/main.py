import html
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .distribution import process_distribution, record_download_acknowledgement, validate_tracking_signature
from .excel_parser import list_source_documents, parse_client_workbook
from .tasks import ping_task


load_dotenv()

APP_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = APP_ROOT / "storage" / "source"

app = FastAPI(title="CCS Compliant Cleaning Platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ccs-api"}


@app.post("/tasks/ping")
def enqueue_ping() -> dict[str, str]:
    task = ping_task.delay()
    return {"task_id": task.id, "status": "queued"}


@app.post("/workbook/preview")
async def preview_workbook(file: UploadFile = File(...)) -> dict[str, Any]:
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
async def preview_register(file: UploadFile = File(...)) -> dict[str, Any]:
    return await preview_workbook(file)


@app.post("/distribution/test-send")
def test_send_distribution(request: DistributionRequest) -> dict[str, Any]:
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
    page = f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>CCS Safety Document</title>
      <style>
        body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #17212b; background: #f5f8fa; }}
        header {{ background: #2C6B33; color: white; padding: 20px 28px; }}
        main {{ max-width: 860px; margin: 36px auto; background: white; border: 1px solid #d9e1e8; border-radius: 8px; padding: 28px; }}
        a.button {{ display: inline-block; margin-top: 14px; background: #2C6B33; color: white; padding: 12px 16px; border-radius: 6px; text-decoration: none; font-weight: 700; }}
        .muted {{ color: #607080; }}
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
    </html>
    """
    response = HTMLResponse(page)
    response.headers["X-CCS-Acknowledgement"] = str(acknowledgement)
    return response


@app.get("/documents/source/{filename:path}")
def get_source_document(filename: str) -> FileResponse:
    path = (SOURCE_DIR / filename).resolve()
    source_root = SOURCE_DIR.resolve()
    if source_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(path)
