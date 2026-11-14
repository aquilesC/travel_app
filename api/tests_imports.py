"""Imports API (v4 #28)."""

import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

from api.tests_positions import batch as position_batch
from api.tests_write import AppTestCase
from trips.models import Entry, ImportBatch, Media
from trips.tests.test_imports import photo

LOCAL = datetime(2026, 12, 23, 9, 0)  # Colombo wall clock (UTC+5:30)


class ImportApiTests(AppTestCase):
    def start(self, **body):
        response = self.call("post", f"/trips/{self.trip.pk}/imports", body)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def add(self, batch_id, name, when, gps=None):
        path = photo(self.media_root / name, when, gps=gps, offset="+05:30")
        data = path.read_bytes()
        _, done = self.upload(data, name, batch_id=batch_id, trip_id=None)
        return done.json()

    def test_pick_photos_review_and_commit(self):
        batch = self.start(client_id=str(uuid.uuid4()))
        self.assertTrue(batch["review_url"].endswith(f"/imports/{batch['id']}/review/"))
        # morning walk: two photos with GPS 5 min apart, one without GPS between them
        self.add(batch["id"], "a.jpg", LOCAL, gps=(6.93, 79.85))
        self.add(batch["id"], "b.jpg", LOCAL + timedelta(minutes=5), gps=(6.931, 79.851))
        # afternoon, 4 h later and far away: a new entry
        self.add(batch["id"], "c.jpg", LOCAL + timedelta(hours=4), gps=(7.29, 80.63))
        detail = self.call("get", f"/imports/{batch['id']}").json()
        self.assertEqual(len(detail["items"]), 3)
        self.assertEqual([len(e["item_ids"]) for e in detail["proposed_entries"]], [2, 1])

        commit = self.call("post", f"/imports/{batch['id']}/commit", {"make_public": False})
        self.assertEqual(commit.status_code, 200, commit.content)
        entry_ids = commit.json()["entry_ids"]
        self.assertEqual(len(entry_ids), 2)
        self.assertEqual(Media.objects.count(), 3)
        self.assertFalse(Entry.objects.filter(is_public=True).exists())
        # committing again (lost response) returns the same entries
        self.assertEqual(self.call("post", f"/imports/{batch['id']}/commit", {}).json()["entry_ids"], entry_ids)
        self.assertEqual(Entry.objects.count(), 2)

    def test_photo_without_gps_placed_from_recorded_positions(self):
        start = datetime(2026, 12, 23, 3, 0, tzinfo=dt_timezone.utc)  # 08:30 in Colombo
        self.api("post", f"/trips/{self.trip.pk}/positions", token=self.tok,
                 data={"points": position_batch(60, start=start)})
        batch = self.start()
        self.add(batch["id"], "nogps.jpg", LOCAL)  # 09:00 local = 03:30 UTC → 30th point
        proposed = self.call("get", f"/imports/{batch['id']}").json()["proposed_entries"]
        self.assertEqual(proposed[0]["located_from"], ["gpx"])
        self.assertAlmostEqual(proposed[0]["latitude"], 6.93 + 30 * 0.0005, places=4)

    def test_client_id_and_privacy(self):
        client_id = str(uuid.uuid4())
        first, again = self.start(client_id=client_id), self.start(client_id=client_id)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(ImportBatch.objects.count(), 1)

    def test_discard(self):
        batch = self.start()
        self.add(batch["id"], "a.jpg", LOCAL, gps=(6.93, 79.85))
        self.assertEqual(self.call("delete", f"/imports/{batch['id']}").status_code, 204)
        self.assertFalse(ImportBatch.objects.exists())

    def test_review_page_opens_app_batch(self):
        batch = self.start()
        self.add(batch["id"], "a.jpg", LOCAL, gps=(6.93, 79.85))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f"/imports/{batch['id']}/review/").status_code, 200)
