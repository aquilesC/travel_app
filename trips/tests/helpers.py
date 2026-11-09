import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from trips.models import Trip


class MediaRootTestCase(TestCase):
    """Each test gets its own empty MEDIA_ROOT."""

    def setUp(self):
        super().setUp()
        self.media_root = Path(tempfile.mkdtemp(prefix="trips-media-"))
        override = override_settings(MEDIA_ROOT=self.media_root, BACKUP_DIR=self.media_root / "backups")
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.user = get_user_model().objects.create_user("aquiles", password="pw")
        self.other_user = get_user_model().objects.create_user("partner", password="pw")

    def make_trip(self, **kwargs):
        defaults = dict(title="Sri Lanka", start_date=date(2026, 12, 21), end_date=date(2027, 1, 10),
                        timezone="Asia/Colombo", created_by=self.user)
        defaults.update(kwargs)
        return Trip.objects.create(**defaults)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True, capture_output=True)


def make_video(path, seconds=2, size="1920x1080", metadata=()):
    extra = []
    for item in metadata:
        extra += ["-metadata", item]
    ffmpeg("-f", "lavfi", "-i", f"testsrc=size={size}:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
           "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
           *extra, str(path))
    return path


def make_audio(path, seconds=2):
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440", "-t", str(seconds), "-c:a", "libopus", str(path))
    return path
