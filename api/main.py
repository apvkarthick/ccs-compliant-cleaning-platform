from fastapi import FastAPI

from .tasks import ping_task


app = FastAPI(title="CCS Compliant Cleaning Platform")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ccs-api"}


@app.post("/tasks/ping")
def enqueue_ping() -> dict[str, str]:
    task = ping_task.delay()
    return {"task_id": task.id, "status": "queued"}
