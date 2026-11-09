"""Issue 04: chunked uploads and media processing (real Pillow and ffmpeg)."""

import hashlib
import os
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

from PIL import Image
from pillow_heif import register_heif_opener

from trips.models import Entry, Media, Upload

from .helpers import MediaRootTestCase, make_audio, make_video

register_heif_opener()


def exif_with_gps(orientation=1):
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif.get_ifd(0x8769)[0x9003] = "2026:12:22 18:00:00"   # DateTimeOriginal
    exif.get_ifd(0x8769)[0x9011] = "+05:30"                # OffsetTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (6.0, 1.0, 34.2)                 # 6.026167
    gps[3], gps[4] = "E", (80.0, 13.0, 1.8)                # 80.2172
    return exif


class UploadTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()
        self.entry = Entry.objects.create(trip=self.trip, author=self.user, occurred_at="2026-12-22T10:00Z")
        self.client.force_login(self.user)

    def start(self, filename, size):
        response = self.client.post(f"/entries/{self.entry.pk}/uploads/",
                                    {"filename": filename, "size": size}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["id"]

    def chunk(self, upload_id, offset, data):
        return self.client.post(f"/uploads/{upload_id}/chunk/?offset={offset}", data,
                                content_type="application/octet-stream")

    def test_multi_chunk_upload_is_byte_identical(self):
        """protects=AC3: a file sent in several chunks is stored byte-identical (sha256);
        fails_when=chunks are reordered, duplicated or truncated, or the original is altered;
        no_claim=a 300 MB file through Cloudflare (checked live) or 50 MB chunks (small ones here)."""
        data = os.urandom(3 * 1024 * 1024 + 123)
        upload_id = self.start("clip.mp3", len(data))
        parts = [data[:1_500_000], data[1_500_000:3_000_000], data[3_000_000:]]
        offset = 0
        for part in parts:
            response = self.chunk(upload_id, offset, part)
            self.assertEqual(response.status_code, 200)
            offset = response.json()["received"]
        response = self.client.post(f"/uploads/{upload_id}/complete/")
        self.assertEqual(response.status_code, 200, response.content)
        media = Media.objects.get(pk=response.json()["media_id"])
        stored = (self.media_root / media.original.name).read_bytes()
        self.assertEqual(hashlib.sha256(stored).hexdigest(), hashlib.sha256(data).hexdigest())
        self.assertEqual(media.sha256, hashlib.sha256(data).hexdigest())
        self.assertFalse(Upload.objects.exists())
        self.assertFalse(list((self.media_root / "tmp" / "uploads").iterdir()))

    def test_retried_chunk_is_not_appended_twice(self):
        """protects=resuming after a lost response doesn't duplicate bytes;
        fails_when=a resent chunk at a stale offset gets appended;
        no_claim=browser retry timing."""
        upload_id = self.start("a.mp3", 10)
        self.assertEqual(self.chunk(upload_id, 0, b"12345").status_code, 200)
        retry = self.chunk(upload_id, 0, b"12345")
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json()["received"], 5)
        self.assertEqual(self.client.get(f"/uploads/{upload_id}/").json()["received"], 5)

    def test_incomplete_and_oversized(self):
        """protects=only complete uploads become media; size announced up front is enforced;
        fails_when=a half upload is stored or extra bytes are accepted;
        no_claim=the 50 MB chunk cap (Content-Length check, needs a real large body)."""
        upload_id = self.start("a.mp3", 10)
        self.chunk(upload_id, 0, b"12345")
        self.assertEqual(self.client.post(f"/uploads/{upload_id}/complete/").status_code, 400)
        self.assertEqual(self.chunk(upload_id, 5, b"123456789").status_code, 400)
        self.assertFalse(Media.objects.exists())

    def test_duplicate_rejected_and_unsupported_type(self):
        """protects=the same file can't be attached twice to an entry; odd types are refused;
        fails_when=a duplicate creates a second Media or a .exe is accepted;
        no_claim=duplicates across different entries (allowed on purpose)."""
        for expected in (200, 409):
            upload_id = self.start("song.mp3", 4)
            self.chunk(upload_id, 0, b"abcd")
            response = self.client.post(f"/uploads/{upload_id}/complete/")
            self.assertEqual(response.status_code, expected)
        self.assertEqual(Media.objects.count(), 1)
        response = self.client.post(f"/entries/{self.entry.pk}/uploads/",
                                    {"filename": "virus.exe", "size": 4}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_other_users_upload_is_hidden(self):
        """protects=an upload session can only be continued by the user who started it;
        fails_when=another logged-in user can append chunks to it;
        no_claim=permissions between the two owners elsewhere (both can edit everything)."""
        upload_id = self.start("a.mp3", 4)
        self.client.force_login(self.other_user)
        self.assertEqual(self.chunk(upload_id, 0, b"abcd").status_code, 404)


class ProcessingTests(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()
        self.entry = Entry.objects.create(trip=self.trip, author=self.user, occurred_at="2026-12-22T10:00Z")
        self.client.force_login(self.user)

    def upload(self, path):
        data = Path(path).read_bytes()
        response = self.client.post(f"/entries/{self.entry.pk}/uploads/",
                                    {"filename": Path(path).name, "size": len(data)},
                                    content_type="application/json")
        upload_id = response.json()["id"]
        self.client.post(f"/uploads/{upload_id}/chunk/?offset=0", data,
                         content_type="application/octet-stream")
        response = self.client.post(f"/uploads/{upload_id}/complete/")
        self.assertEqual(response.status_code, 200, response.content)
        return Media.objects.get(pk=response.json()["media_id"])  # processed immediately in tests

    def test_heic_photo(self):
        """protects=AC4: iPhone HEIC gets sm/md/lg WebP derivatives plus EXIF time and GPS;
        fails_when=HEIC can't be decoded, sizes are wrong, or time/GPS are dropped;
        no_claim=every iPhone HEIC variant (synthetic file made with pillow-heif)."""
        source = self.media_root / "IMG_0001.HEIC"
        Image.new("RGB", (3000, 2000), "teal").save(source, format="HEIF", exif=exif_with_gps().tobytes())
        media = self.upload(source)
        self.assertEqual(media.status, Media.READY, media.error)
        self.assertEqual(set(media.derivatives), {"sm", "md", "lg"})
        sizes = {k: Image.open(self.media_root / v).size for k, v in media.derivatives.items()}
        self.assertEqual(sizes, {"sm": (400, 267), "md": (1200, 800), "lg": (2400, 1600)})
        self.assertEqual(media.taken_at, datetime(2026, 12, 22, 12, 30, tzinfo=dt_timezone.utc))
        self.assertEqual(media.latitude, Decimal("6.026167"))
        self.assertEqual(media.longitude, Decimal("80.217167"))
        self.assertEqual((media.width, media.height), (3000, 2000))

    def test_jpeg_orientation_applied(self):
        """protects=AC4: EXIF orientation is applied, so portrait photos aren't sideways;
        fails_when=derivatives keep the sensor orientation;
        no_claim=mirrored orientations (2, 4, 5, 7) individually."""
        source = self.media_root / "portrait.jpg"
        Image.new("RGB", (600, 400), "orange").save(source, exif=exif_with_gps(orientation=6).tobytes())
        media = self.upload(source)
        self.assertEqual(media.status, Media.READY, media.error)
        self.assertEqual(Image.open(self.media_root / media.derivatives["md"]).size, (400, 600))
        self.assertEqual((media.width, media.height), (400, 600))

    def test_video_transcoded_to_720p(self):
        """protects=AC3: a 1080p video gets a playable H.264/AAC 720p MP4 and a poster;
        fails_when=ffmpeg fails, the output is not H.264, or the size isn't 720p;
        no_claim=processing time for long videos (measured live) or iPhone HDR colours."""
        from trips.processing import probe

        source = make_video(self.media_root / "clip.mov",
                            metadata=["location=+07.2906+080.6337/"])
        media = self.upload(source)
        self.assertEqual(media.status, Media.READY, media.error)
        info = probe(self.media_root / media.derivatives["mp4"])
        codecs = {s["codec_type"]: s["codec_name"] for s in info["streams"]}
        self.assertEqual(codecs, {"video": "h264", "audio": "aac"})
        self.assertEqual((media.width, media.height), (1280, 720))
        self.assertTrue((self.media_root / media.derivatives["poster"]).exists())
        self.assertAlmostEqual(media.duration_seconds, 2, delta=0.2)
        self.assertEqual(media.latitude, Decimal("7.290600"))

    def test_voice_note_converted(self):
        """protects=WhatsApp-style ogg/opus audio gets a browser-playable AAC copy;
        fails_when=no audio derivative or the original is overwritten;
        no_claim=AMR voice notes (same ffmpeg path, not tested)."""
        media = self.upload(make_audio(self.media_root / "note.ogg"))
        self.assertEqual(media.status, Media.READY, media.error)
        self.assertTrue(media.derivatives["audio"].endswith(".m4a"))
        self.assertNotEqual(media.derivatives["audio"], media.original.name)

    def test_broken_file_marked_failed_and_retry(self):
        """protects=a file that can't be processed is marked failed with the error, and retry re-runs it;
        fails_when=the task crashes silently and the item stays 'processing' forever;
        no_claim=retry success (the file is still broken here)."""
        source = self.media_root / "broken.jpg"
        source.write_bytes(b"not an image")
        media = self.upload(source)
        self.assertEqual(media.status, Media.FAILED)
        self.assertIn("UnidentifiedImageError", media.error)
        response = self.client.post(f"/media-items/{media.pk}/retry/")
        self.assertEqual(response.status_code, 302)
        media.refresh_from_db()
        self.assertEqual(media.status, Media.FAILED)

    def test_delete_removes_files(self):
        """protects=removing media deletes the original and derivatives from disk;
        fails_when=files are orphaned on the volume;
        no_claim=files of entries deleted via the admin bulk action (same signal)."""
        source = self.media_root / "p.jpg"
        Image.new("RGB", (50, 50)).save(source)
        media = self.upload(source)
        files = [self.media_root / media.original.name] + [self.media_root / p for p in media.derivatives.values()]
        self.assertTrue(all(f.exists() for f in files))
        self.client.post(f"/media-items/{media.pk}/delete/")
        self.assertFalse(any(f.exists() for f in files))
