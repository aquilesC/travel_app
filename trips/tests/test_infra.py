"""Issue 01: scheduler, nightly backup, protected media serving."""

import subprocess
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import override_settings

from trips import backup
from trips.management.commands import run_scheduler
from trips.models import Entry, Media, ScheduledRun

from .helpers import MediaRootTestCase

AMS = ZoneInfo("Europe/Amsterdam")
SCHEDULE = [("job_a", "03:00", "trips.tasks.nightly_backup"),
            ("job_b", "20:00", "trips.tasks.send_daily_digests")]


class SchedulerTests(MediaRootTestCase):
    def test_runs_due_jobs_once_per_day(self):
        """protects=each job is enqueued once per day after its time;
        fails_when=a job runs before its time, or twice the same day (restart / next tick);
        no_claim=the 60 s loop itself or worker pickup."""
        with mock.patch("trips.tasks.nightly_backup") as backup_task, \
             mock.patch("trips.tasks.send_daily_digests") as digest_task:
            self.assertEqual(run_scheduler.run_once(datetime(2026, 12, 1, 2, 59, tzinfo=AMS), SCHEDULE), [])
            self.assertEqual(run_scheduler.run_once(datetime(2026, 12, 1, 3, 0, tzinfo=AMS), SCHEDULE), ["job_a"])
            self.assertEqual(run_scheduler.run_once(datetime(2026, 12, 1, 3, 1, tzinfo=AMS), SCHEDULE), [])
            self.assertEqual(run_scheduler.run_once(datetime(2026, 12, 1, 21, 0, tzinfo=AMS), SCHEDULE), ["job_b"])
            self.assertEqual(run_scheduler.run_once(datetime(2026, 12, 2, 3, 5, tzinfo=AMS), SCHEDULE), ["job_a"])
        self.assertEqual(backup_task.enqueue.call_count, 2)
        self.assertEqual(digest_task.enqueue.call_count, 1)
        self.assertEqual(ScheduledRun.objects.get(name="job_a").last_run_date.isoformat(), "2026-12-02")


class BackupTests(MediaRootTestCase):
    def test_retention_keeps_newest(self):
        """protects=AC12 retention: only the newest N dumps remain;
        fails_when=old dumps pile up or the newest is deleted;
        no_claim=dump contents (see test_dump_restores)."""
        folder = self.media_root / "backups"
        folder.mkdir()
        for day in range(1, 18):
            (folder / f"trips-202612{day:02d}-030000.dump").write_text("x")
        removed = backup.prune(folder, keep=14)
        remaining = sorted(p.name for p in folder.glob("trips-*.dump"))
        self.assertEqual(len(removed), 3)
        self.assertEqual(len(remaining), 14)
        self.assertEqual(remaining[0], "trips-20261204-030000.dump")

    def test_dump_restores(self):
        """protects=AC12: the nightly dump is a valid custom-format archive pg_restore reads;
        fails_when=pg_dump fails (e.g. client/server version mismatch) or writes garbage;
        no_claim=a full restore into a fresh database (verified manually, see README)."""
        target = backup.dump_database(now=datetime(2026, 12, 1, 3, 0))
        self.assertTrue(target.exists())
        self.assertFalse(list(target.parent.glob("*.partial")))
        listing = subprocess.run(["pg_restore", "--list", str(target)], capture_output=True, text=True)
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn("trips_trip", listing.stdout)
        self.assertIn(connection.settings_dict["NAME"], listing.stdout)


class MediaServingTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()
        self.entry = Entry.objects.create(trip=self.trip, author=self.user,
                                          occurred_at="2026-12-22T10:00Z", is_public=False)
        self.media = Media.objects.create(entry=self.entry, kind=Media.PHOTO, sha256="x", size_bytes=1,
                                          derivatives={"md": "derived/1/1_md.webp"})
        self.media.original.name = "originals/1/a.jpg"
        self.media.save()

    def test_owner_gets_accel_redirect(self):
        """protects=nginx serves files only via X-Accel-Redirect after Django's check;
        fails_when=the header is missing/wrong or Django streams the file itself;
        no_claim=nginx config (verified against the running stack)."""
        self.client.force_login(self.user)
        response = self.client.get(f"/m/{self.media.pk}/md/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Accel-Redirect"], "/protected/derived/1/1_md.webp")
        self.assertEqual(response["Content-Type"], "image/webp")

    def test_anonymous_and_unknown_variant(self):
        """protects=private media need a login; unknown variants 404;
        fails_when=anonymous users get a file, or 'lg' of a photo without one leaks a path;
        no_claim=share-token access (test_share)."""
        response = self.client.get(f"/m/{self.media.pk}/md/")
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f"/m/{self.media.pk}/lg/").status_code, 404)
        self.assertEqual(self.client.get(f"/m/{self.media.pk}/mp4/").status_code, 404)

    @override_settings(MEDIA_ACCEL_REDIRECT=False)
    def test_direct_serving_without_nginx(self):
        """protects=local runs without nginx still show media;
        fails_when=the fallback path breaks or escapes MEDIA_ROOT;
        no_claim=range requests (only nginx handles those)."""
        path = Path(self.media_root, "derived/1/1_md.webp")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"webp")
        self.client.force_login(self.user)
        response = self.client.get(f"/m/{self.media.pk}/md/")
        self.assertEqual(b"".join(response.streaming_content), b"webp")
