"""Issue 05: GPX upload, render-time parsing, map data."""

import math
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from trips.gpx import map_data, track_summary
from trips.models import Entry, Track

from .helpers import MediaRootTestCase


def make_gpx(points=200, start=(6.93, 79.85)):
    begin = datetime(2026, 12, 23, 6, 0, tzinfo=dt_timezone.utc)
    rows = []
    for i in range(points):
        # a gently curving line ~3 m between points
        lat = start[0] + i * 0.00002
        lon = start[1] + 0.001 * math.sin(i / 500)
        stamp = (begin + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}"><ele>{10 + i % 7}</ele><time>{stamp}</time></trkpt>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><name>Morning ride</name><trkseg>{"".join(rows)}</trkseg></trk></gpx>')


class GPXTests(MediaRootTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("createcachetable", verbosity=0)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.trip = self.make_trip()
        self.client.force_login(self.user)

    def test_upload_stores_verbatim(self):
        """protects=AC5: the stored gpx_text is byte-identical to the upload;
        fails_when=the file is reformatted, re-encoded or truncated on save;
        no_claim=non-UTF-8 GPX (rejected with a message)."""
        text = make_gpx(50)
        response = self.client.post(f"/trips/{self.trip.pk}/tracks/new/", {
            "name": "Ride", "mode": "bike",
            "gpx_file": SimpleUploadedFile("ride.gpx", text.encode(), "application/gpx+xml"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Track.objects.get().gpx_text, text)

    def test_invalid_gpx_rejected(self):
        """protects=unreadable files are refused with the parser error;
        fails_when=a broken file is stored and the map crashes later;
        no_claim=GPX with only waypoints (refused: no track/route points)."""
        response = self.client.post(f"/trips/{self.trip.pk}/tracks/new/", {
            "mode": "hike", "gpx_file": SimpleUploadedFile("x.gpx", b"<gpx><trk>broken", "text/xml"),
        })
        self.assertContains(response, "Not a readable GPX file")
        self.assertFalse(Track.objects.exists())

    def test_large_track_renders_fast_and_is_cached(self):
        """protects=AC5: a 100k-point GPX renders in < 3 s first and < 300 ms cached;
        fails_when=parsing is too slow, the cache is not used, or the cache survives an edit;
        no_claim=browser rendering time of the map itself."""
        track = Track.objects.create(trip=self.trip, mode="sail", gpx_text=make_gpx(100_000),
                                     uploaded_by=self.user)
        started = time.perf_counter()
        first = self.client.get(f"/trips/{self.trip.pk}/map.json")
        cold = time.perf_counter() - started
        started = time.perf_counter()
        second = self.client.get(f"/trips/{self.trip.pk}/map.json")
        warm = time.perf_counter() - started
        self.assertEqual(first.json(), second.json())
        self.assertLess(cold, 3.0)
        self.assertLess(warm, 0.3)
        feature = first.json()["features"][0]
        points = sum(len(line) for line in feature["geometry"]["coordinates"])
        self.assertLess(points, 20_000)  # simplified for the browser
        self.assertGreater(feature["properties"]["distance_km"], 200)
        print(f"\n  100k-point GPX: cold {cold:.2f}s, cached {warm * 1000:.0f}ms, {points} points drawn")

        summary = track_summary(track)
        track.gpx_text = make_gpx(10)
        track.save()
        self.assertNotEqual(track_summary(track), summary)

    def test_map_data_checkins_and_privacy(self):
        """protects=entry check-ins become points and a path; private ones stay off the public map;
        fails_when=private locations leak to map data for the share link;
        no_claim=photo-GPS fallback positions (same code path, covered by AC4 data)."""
        Entry.objects.create(trip=self.trip, author=self.user, occurred_at="2026-12-22T10:00Z",
                             latitude=6.9, longitude=79.8, place_name="Colombo")
        Entry.objects.create(trip=self.trip, author=self.user, occurred_at="2026-12-23T10:00Z",
                             latitude=7.29, longitude=80.63, place_name="Kandy", is_public=False)
        everything = map_data(self.trip, public_only=False)["features"]
        public = map_data(self.trip, public_only=True)["features"]
        self.assertEqual([f["properties"]["kind"] for f in everything], ["entry", "entry", "path"])
        self.assertEqual([f["properties"].get("title") for f in public], ["Colombo"])
