"""Uploads (v4 #25) and the write API (v4 #24), as the iPhone app uses them."""

import hashlib
import shutil
import tempfile
import uuid
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path

from django.test import Client, override_settings

from api.tests import ApiTestCase
from trips.models import Chapter, Entry, Media, Trip, Upload
from trips.services.uploads import delete_stale_uploads
from trips.tests.test_gpx import make_gpx

WHEN = "2026-12-23T08:00:00+05:30"


class AppTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.media_root = Path(tempfile.mkdtemp(prefix="trips-media-"))
        override = override_settings(MEDIA_ROOT=self.media_root, UPLOAD_CHUNK_MAX_BYTES=1024)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.trip = Trip.objects.create(title="Sri Lanka", start_date=date(2026, 12, 21),
                                        end_date=date(2027, 1, 10), timezone="Asia/Colombo",
                                        created_by=self.user)
        self.trip.travellers.add(self.user)
        self.tok = self.token()

    def call(self, method, path, data=None, **extra):
        return self.api(method, path, token=self.tok, data=data, **extra)

    def upload(self, data, filename="voice.m4a", sha=None, **target):
        target.setdefault("trip_id", self.trip.pk)
        start = self.call("post", "/uploads", {"filename": filename, "size": len(data),
                                               "sha256": sha or hashlib.sha256(data).hexdigest(), **target})
        self.assertIn(start.status_code, (200, 201), start.content)
        upload_id = start.json()["id"]
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 1024]
            response = Client().put(f"/api/v1/uploads/{upload_id}/chunk?offset={offset}", chunk,
                                    content_type="application/octet-stream", HTTP_X_SESSION_TOKEN=self.tok)
            self.assertEqual(response.status_code, 200, response.content)
            offset = response.json()["received"]
        return upload_id, self.call("post", f"/uploads/{upload_id}/complete")


class UploadTests(AppTestCase):
    def test_resume_after_interruption(self):
        data = bytes(range(256)) * 12  # 3 chunks of 1024
        start = self.call("post", "/uploads", {"filename": "a.m4a", "size": len(data), "trip_id": self.trip.pk})
        upload_id = start.json()["id"]
        Client().put(f"/api/v1/uploads/{upload_id}/chunk?offset=0", data[:1024],
                     content_type="application/octet-stream", HTTP_X_SESSION_TOKEN=self.tok)
        # the app restarts: ask where we are, continue from there
        received = self.call("get", f"/uploads/{upload_id}").json()["received"]
        self.assertEqual(received, 1024)
        stale = Client().put(f"/api/v1/uploads/{upload_id}/chunk?offset=0", data[:1024],
                             content_type="application/octet-stream", HTTP_X_SESSION_TOKEN=self.tok)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["received"], 1024)
        for offset in (1024, 2048):
            Client().put(f"/api/v1/uploads/{upload_id}/chunk?offset={offset}", data[offset:offset + 1024],
                         content_type="application/octet-stream", HTTP_X_SESSION_TOKEN=self.tok)
        done = self.call("post", f"/uploads/{upload_id}/complete").json()
        self.assertEqual(done["sha256"], hashlib.sha256(data).hexdigest())

    def test_sha_mismatch_is_rejected(self):
        _, done = self.upload(b"hello world", sha="0" * 64)
        self.assertError(done, 422, "invalid")
        self.assertFalse(Upload.objects.exists())

    def test_client_id_returns_the_same_upload(self):
        client_id = str(uuid.uuid4())
        body = {"filename": "a.m4a", "size": 10, "trip_id": self.trip.pk, "client_id": client_id}
        first = self.call("post", "/uploads", body)
        again = self.call("post", "/uploads", body)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()["id"], again.json()["id"])

    def test_media_exists_only_reports_own_trips(self):
        entry = Entry.objects.create(trip=self.trip, author=self.user, occurred_at=WHEN)
        Media.objects.create(entry=entry, kind="photo", sha256="a" * 64, size_bytes=1, original="o.jpg")
        stranger_trip = Trip.objects.create(title="Other", start_date=date(2026, 1, 1),
                                            end_date=date(2026, 1, 2), created_by=self.user)
        other = Entry.objects.create(trip=stranger_trip, author=self.user, occurred_at=WHEN)
        Media.objects.create(entry=other, kind="photo", sha256="b" * 64, size_bytes=1, original="p.jpg")
        response = self.call("post", "/media/exists", {"sha256": ["a" * 64, "b" * 64, "c" * 64]})
        self.assertEqual(response.json(), {"existing": ["a" * 64]})

    def test_unclaimed_detached_uploads_expire(self):
        upload_id, _ = self.upload(b"abc")
        self.assertEqual(delete_stale_uploads(), 0)
        later = datetime(2030, 1, 1, tzinfo=dt_timezone.utc)
        self.assertEqual(delete_stale_uploads(now=later), 1)
        self.assertFalse(Upload.objects.filter(pk=upload_id).exists())


class EntryWriteTests(AppTestCase):
    def test_app_post_with_media_is_idempotent(self):
        voice, _ = self.upload(b"voice-bytes", "voice.m4a")
        photo, _ = self.upload(b"photo-bytes", "IMG_1.jpg")
        client_id = str(uuid.uuid4())
        body = {"occurred_at": WHEN, "body": "Tea in Ella", "latitude": 6.866, "longitude": 81.046,
                "place_name": "Ella", "upload_ids": [voice, photo], "client_id": client_id}
        first = self.call("post", f"/trips/{self.trip.pk}/entries", body)
        self.assertEqual(first.status_code, 201, first.content)
        entry = first.json()
        self.assertEqual(entry["source"], "app")
        self.assertEqual([m["kind"] for m in entry["media"]], ["audio", "photo"])
        again = self.call("post", f"/trips/{self.trip.pk}/entries", body)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["id"], entry["id"])
        self.assertEqual(Entry.objects.count(), 1)
        self.assertFalse(Upload.objects.exists())

    def test_web_session_post_is_web_source(self):
        self.client.force_login(self.user)
        response = self.client.post(f"/api/v1/trips/{self.trip.pk}/entries", {"occurred_at": WHEN, "body": "x"},
                                    content_type="application/json")
        self.assertEqual(response.json()["source"], "web")

    def test_new_posts_go_into_the_current_chapter(self):
        chapter = self.call("post", f"/trips/{self.trip.pk}/chapters", {"title": "Hills", "make_current": True}).json()
        entry = self.call("post", f"/trips/{self.trip.pk}/entries", {"occurred_at": WHEN, "body": "x"}).json()
        self.assertEqual(entry["chapter_id"], chapter["id"])
        self.call("put", f"/trips/{self.trip.pk}/current-chapter", {"chapter_id": None})
        entry = self.call("post", f"/trips/{self.trip.pk}/entries", {"occurred_at": WHEN, "body": "y"}).json()
        self.assertIsNone(entry["chapter_id"])

    def test_private_post_stays_off_the_share_page(self):
        self.call("post", f"/trips/{self.trip.pk}/entries",
                  {"occurred_at": WHEN, "body": "Just for us", "is_public": False})
        self.assertNotContains(Client().get(f"/s/{self.trip.share_token}/"), "Just for us")

    def test_validation(self):
        bad = [{"occurred_at": WHEN, "latitude": 95, "longitude": 10},
               {"occurred_at": "2026-06-01T10:00:00+00:00"},
               {"occurred_at": WHEN, "upload_ids": [str(uuid.uuid4())]},
               {"occurred_at": WHEN, "chapter_id": 999999}]
        for body in bad:
            with self.subTest(body=body):
                self.assertError(self.call("post", f"/trips/{self.trip.pk}/entries", body), 422, "invalid")
        self.assertFalse(Entry.objects.exists())

    def test_patch_and_delete(self):
        entry = self.call("post", f"/trips/{self.trip.pk}/entries", {"occurred_at": WHEN, "body": "a"}).json()
        patched = self.call("patch", f"/entries/{entry['id']}", {"body": "b", "is_public": False}).json()
        self.assertEqual((patched["body"], patched["is_public"]), ("b", False))
        self.assertEqual(self.call("delete", f"/entries/{entry['id']}").status_code, 204)
        self.assertFalse(Entry.objects.exists())

    def test_chapters(self):
        a = self.call("post", f"/trips/{self.trip.pk}/chapters", {"title": "A"}).json()
        b = self.call("post", f"/trips/{self.trip.pk}/chapters", {"title": "B"}).json()
        order = self.call("post", f"/chapters/{b['id']}/move", {"direction": "up"}).json()
        self.assertEqual([c["title"] for c in order], ["B", "A"])
        self.call("patch", f"/chapters/{a['id']}", {"title": "Alpha"})
        self.assertEqual(Chapter.objects.get(pk=a["id"]).title, "Alpha")
        self.assertEqual(self.call("delete", f"/chapters/{a['id']}").status_code, 204)

    def test_gpx_track_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = Client().post(f"/api/v1/trips/{self.trip.pk}/tracks",
                                 {"file": SimpleUploadedFile("ride.gpx", make_gpx(20).encode()), "mode": "bike"},
                                 HTTP_X_SESSION_TOKEN=self.tok)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.trip.tracks.get().gpx_text, make_gpx(20))
        response = Client().post(f"/api/v1/trips/{self.trip.pk}/tracks",
                                 {"file": SimpleUploadedFile("x.gpx", b"nope")}, HTTP_X_SESSION_TOKEN=self.tok)
        self.assertError(response, 422, "invalid")
