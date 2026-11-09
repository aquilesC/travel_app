"""Nightly database dump into the media volume (backed up off-site with restic)."""

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection

log = logging.getLogger(__name__)
PATTERN = "trips-*.dump"


def dump_database(backup_dir=None, keep=None, now=None):
    backup_dir = Path(backup_dir or settings.BACKUP_DIR)
    keep = keep or settings.BACKUP_KEEP
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"trips-{stamp}.dump"
    partial = target.with_suffix(".partial")

    db = connection.settings_dict
    env = {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}
    cmd = [
        "pg_dump", "--format=custom", "--no-owner",
        "--host", db.get("HOST") or "localhost",
        "--port", str(db.get("PORT") or 5432),
        "--username", db.get("USER") or "",
        "--file", str(partial),
        db["NAME"],
    ]
    subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=3600)
    partial.rename(target)
    removed = prune(backup_dir, keep)
    log.info("Database dumped to %s (%d bytes); pruned %d old dumps",
             target, target.stat().st_size, len(removed))
    return target


def prune(backup_dir, keep):
    dumps = sorted(Path(backup_dir).glob(PATTERN))  # timestamped names sort by age
    old = dumps[:-keep] if keep else dumps
    for path in old:
        path.unlink()
    return old
