import fitz

from .celery_app import celery_app


@celery_app.task(name="ccs.ping")
def ping_task() -> dict[str, str]:
    return {
        "status": "ok",
        "worker": "ccs-worker",
        "pymupdf": fitz.VersionBind,
    }
