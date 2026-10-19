from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.pipeline import run_scheduled_report

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if not settings.schedule_enabled or _scheduler:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_scheduled_report,
        CronTrigger(day_of_week=settings.schedule_day_of_week, hour=settings.schedule_hour, minute=0),
        id="weekly_report", max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
