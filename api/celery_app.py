import os

from celery import Celery


redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")

celery_app = Celery(
    "ccs_platform",
    broker=os.getenv("CELERY_BROKER_URL", f"{redis_url}/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", f"{redis_url}/1"),
    include=["api.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
