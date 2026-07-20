import os

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

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
    beat_schedule={
        # Daily at 06:00 UTC (16:00 AEST / 17:00 AEDT)
        "run-scheduled-distributions": {
            "task": "ccs.run_scheduled_distributions",
            "schedule": crontab(hour=6, minute=0),
        },
        # Daily at 07:00 UTC — detect new product–site pairs
        "detect-new-products": {
            "task": "ccs.detect_new_products",
            "schedule": crontab(hour=7, minute=0),
        },
        # Daily at 23:00 UTC (9am AEST) — task self-guards: only sends on first weekday of month
        "send-sds-expiry-alerts": {
            "task": "ccs.send_sds_expiry_alerts",
            "schedule": crontab(hour=23, minute=0),
        },
        # Daily at 23:15 UTC (9:15am AEST) — task self-guards: only sends on first weekday of month
        "send-hold-list-notification": {
            "task": "ccs.send_hold_list_notification",
            "schedule": crontab(hour=23, minute=15),
        },
    },
)
