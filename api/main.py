import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .distribution import process_distribution
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
    name: str = ""
    email: str


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


@app.get("/documents/source/{filename:path}")
def get_source_document(filename: str) -> FileResponse:
    path = (SOURCE_DIR / filename).resolve()
    source_root = SOURCE_DIR.resolve()
    if source_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(path)
