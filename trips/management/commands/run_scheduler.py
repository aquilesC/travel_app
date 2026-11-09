"""Enqueue periodic tasks at fixed local times, at most once per day.

Runs forever in the `scheduler` container. State lives in ScheduledRun, so a
restart after 03:00 still runs the backup once, and never twice.
"""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils.module_loading import import_string

from trips.models import ScheduledRun

log = logging.getLogger(__name__)


def due_jobs(now_local, schedule=None):
    """Names of jobs whose time has passed today and that haven't run today."""
    schedule = schedule if schedule is not None else settings.SCHEDULE
    today = now_local.date()
    last = dict(ScheduledRun.objects.values_list("name", "last_run_date"))
    due = []
    for name, at, path in schedule:
        hour, minute = map(int, at.split(":"))
        if (now_local.hour, now_local.minute) >= (hour, minute) and last.get(name) != today:
            due.append((name, path))
    return due


def run_once(now_local=None, schedule=None):
    now_local = now_local or datetime.now(ZoneInfo(settings.SCHEDULE_TIME_ZONE))
    ran = []
    for name, path in due_jobs(now_local, schedule):
        import_string(path).enqueue()
        ScheduledRun.objects.update_or_create(name=name, defaults={"last_run_date": now_local.date()})
        log.info("Enqueued %s", name)
        ran.append(name)
    return ran


class Command(BaseCommand):
    help = "Enqueue scheduled tasks (backup, digests) at their daily times."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, interval, **options):
        log.info("Scheduler started: %s", [(n, t) for n, t, _ in settings.SCHEDULE])
        while True:
            close_old_connections()
            try:
                run_once()
            except Exception:
                log.exception("Scheduler iteration failed")
            time.sleep(interval)
