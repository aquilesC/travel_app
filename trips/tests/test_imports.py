"""Issues 11 (bulk upload), 12 (trip from GPX) and 13 (trip from photos)."""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from trips import importing
from trips.models import Entry, ImportBatch, ImportItem, Media, Track, Trip

from .helpers import MediaRootTestCase
from .test_gpx import make_gpx

UTC = dt_timezone.utc
KANDY = (7.2906, 80.6337)


def photo(path, when, gps=None, offset=None, camera=("Apple", "iPhone 15")):
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = camera
    exif.get_ifd(0x8769)[0x9003] = when.strftime("%Y:%m:%d %H:%M:%S")
    if offset:
        exif.get_ifd(0x8769)[0x9011] = offset
    if gps:
        def dms(value):
            value = abs(value)
            d = int(value)
            m = int((value - d) * 60)
            return (float(d), float(m), round((value - d - m / 60) * 3600, 4))
        g = exif.get_ifd(0x8825)
        g[1], g[2] = ("N" if gps[0] >= 0 else "S"), dms(gps[0])
        g[3], g[4] = ("E" if gps[1] >= 0 else "W"), dms(gps[1])
    Image.new("RGB", (64, 48), "olive").save(path, exif=exif.tobytes())
    return path


class ImportTestCase(MediaRootTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.counter = 0

    def upload(self, batch, path):
        data = Path(path).read_bytes()
        upload_id = self.client.post(f"/imports/{batch.pk}/uploads/", {"filename": Path(path).name, "size": len(data)},
                                     content_type="application/json").json()["id"]
        self.client.post(f"/uploads/{upload_id}/chunk/?offset=0", data, content_type="application/octet-stream")
        return self.client.post(f"/uploads/{upload_id}/complete/").json()

    def add_photo(self, batch, when, **kwargs):
        self.counter += 1
        return self.upload(batch, photo(self.media_root / f"IMG_{self.counter:04d}.jpg", when, **kwargs))


class BulkUploadTests(ImportTestCase):
    def setUp(self):
        super().setUp()
        self.trip = self.make_trip()  # Asia/Colombo
        self.client.post(f"/trips/{self.trip.pk}/import/")
        self.batch = ImportBatch.objects.get()

    def test_grouping_by_time_and_distance(self):
        """protects=AC11.1: photos group into entries by 60-min gaps and 2-km radius;
        fails_when=the 4-hour gap or the 5-km jump doesn't start a new entry, or close photos split;
        no_claim=user merge/split afterwards (manual editing)."""
        for minute in (0, 10, 20):
            self.add_photo(self.batch, datetime(2026, 12, 23, 10, minute), gps=KANDY, offset="+05:30")
        for minute in (0, 5):
            self.add_photo(self.batch, datetime(2026, 12, 23, 14, minute), gps=KANDY, offset="+05:30")
        self.add_photo(self.batch, datetime(2026, 12, 23, 14, 10), gps=(7.2906, 80.68), offset="+05:30")
        self.assertEqual(self.batch.items.count(), 6)
        response = self.client.post(f"/imports/{self.batch.pk}/review/",
                                    {"shift_0": "+0:00", "make_public": "on", "create": "1"})
        self.assertRedirects(response, f"/trips/{self.trip.pk}/", fetch_redirect_response=False)
        entries = list(self.trip.entries.order_by("occurred_at"))
        self.assertEqual([e.media.count() for e in entries], [3, 2, 1])
        self.assertEqual(entries[0].occurred_at, datetime(2026, 12, 23, 4, 30, tzinfo=UTC))
        self.assertTrue(all(m.status == Media.READY for m in Media.objects.all()))
        self.assertEqual(ImportItem.objects.count(), 0)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, ImportBatch.DONE)
        media = Media.objects.order_by("taken_at").first()
        self.assertTrue((self.media_root / media.original.name).exists())
        self.assertEqual(media.location_source, "exif")

    def test_camera_shift(self):
        """protects=AC11.2: a camera shift moves that camera's photos before grouping;
        fails_when=the shift is ignored or applied to other cameras;
        no_claim=cameras that change clock mid-trip."""
        self.add_photo(self.batch, datetime(2026, 12, 23, 11, 0), camera=("Fujifilm", "X100V"))
        self.add_photo(self.batch, datetime(2026, 12, 23, 10, 0), camera=("Apple", "iPhone 15"))
        review = self.client.get(f"/imports/{self.batch.pk}/review/")
        cameras = [f.label for f in review.context["form"].shift_fields()]
        fuji = cameras.index("Fujifilm X100V")
        data = {f"shift_{i}": "+0:00" for i in range(len(cameras))}
        data[f"shift_{fuji}"] = "-1:00"
        self.client.post(f"/imports/{self.batch.pk}/review/", {**data, "create": "1"})
        media = Media.objects.order_by("taken_at")
        self.assertEqual({m.taken_at for m in media}, {datetime(2026, 12, 23, 4, 30, tzinfo=UTC)})
        self.assertFalse(Entry.objects.get().is_public)  # make_public unchecked

    def test_duplicates_skipped(self):
        """protects=AC11.3: a photo already in the trip or batch is skipped and reported;
        fails_when=the same file is imported twice;
        no_claim=near-duplicates (edited copies have different bytes)."""
        path = photo(self.media_root / "same.jpg", datetime(2026, 12, 23, 9, 0))
        self.assertIn("item_id", self.upload(self.batch, path))
        self.assertIn("already in this import", self.upload(self.batch, path)["skipped"])
        self.client.post(f"/imports/{self.batch.pk}/review/", {"shift_0": "", "make_public": "on", "create": "1"})
        self.client.post(f"/trips/{self.trip.pk}/import/")
        second = ImportBatch.objects.exclude(pk=self.batch.pk).get()
        self.assertIn("already in this trip", self.upload(second, path)["skipped"])

    def test_discard_deletes_files(self):
        """protects=AC11.4: discarding removes staged files and the batch;
        fails_when=files linger on the volume or the batch remains;
        no_claim=files of finished imports (owned by Media, never discarded)."""
        self.add_photo(self.batch, datetime(2026, 12, 23, 9, 0))
        staged = self.media_root / ImportItem.objects.get().path
        self.assertTrue(staged.exists())
        self.client.post(f"/imports/{self.batch.pk}/discard/")
        self.assertFalse(staged.exists())
        self.assertFalse(ImportBatch.objects.exists())


class InterpolationTests(MediaRootTestCase):
    def point(self, hour, lat=None, lon=None):
        item = ImportItem(pk=hour * 100)
        p = importing.Point(item=item, utc=datetime(2026, 12, 23, 0, tzinfo=UTC) + timedelta(hours=hour),
                            lat=lat, lon=lon, source="exif" if lat is not None else "")
        return p

    def test_midpoint_between_neighbours(self):
        """protects=AC13.1: a photo between two located ones gets the time-weighted position;
        fails_when=it copies one side or stays empty;
        no_claim=great-circle accuracy (linear in lat/lon is fine at trip scale)."""
        points = [self.point(10, 7.0, 80.0), self.point(11), self.point(12, 7.2, 80.4)]
        importing.fill_locations(points, [])
        self.assertAlmostEqual(points[1].lat, 7.1)
        self.assertAlmostEqual(points[1].lon, 80.2)
        self.assertEqual(points[1].source, "interpolated")

    def test_gpx_wins_and_far_photos_stay_empty(self):
        """protects=AC13.2-3: GPX position beats neighbours; photos far from everything get none;
        fails_when=neighbour interpolation overrides GPX, or a photo 8 h away gets a guessed spot;
        no_claim=GPX gaps longer than the 10-minute tolerance."""
        begin = datetime(2026, 12, 23, 10, 30, tzinfo=UTC)
        series = [[(begin, 6.0, 81.0), (begin + timedelta(hours=1), 6.2, 81.2)]]
        points = [self.point(10, 7.0, 80.0), self.point(11), self.point(12, 7.2, 80.4), self.point(20)]
        importing.fill_locations(points, series)
        self.assertAlmostEqual(points[1].lat, 6.1)
        self.assertEqual(points[1].source, "gpx")
        self.assertIsNone(points[3].lat)

    def test_copy_single_close_neighbour(self):
        """protects=only one neighbour within 1 h → copy its position; beyond 1 h on one side only → none;
        fails_when=a lone neighbour 3 h away is copied;
        no_claim=tuning of the 1 h / 6 h windows."""
        points = [self.point(10, 7.0, 80.0), self.point(10.5), self.point(13)]
        importing.fill_locations(points, [])
        self.assertEqual((points[1].lat, points[1].source), (7.0, "interpolated"))
        self.assertIsNone(points[2].lat)


class TripFromPhotosTests(ImportTestCase):
    def test_create_trip_with_gpx(self):
        """protects=AC13.4: a trip is created from photo dates in the chosen zone, with GPX tracks and entries;
        fails_when=dates are off by the zone, GPX isn't attached, or photos without GPS ignore the track;
        no_claim=the time-zone guess for every offset (checked for +05:30 only)."""
        self.client.post("/imports/new/")
        batch = ImportBatch.objects.get()
        self.add_photo(batch, datetime(2026, 12, 22, 9, 0), gps=KANDY, offset="+05:30")
        self.add_photo(batch, datetime(2026, 12, 23, 12, 0), offset="+05:30")  # no GPS, covered by GPX
        self.add_photo(batch, datetime(2026, 12, 24, 18, 0), gps=(6.03, 80.22), offset="+05:30")
        review = self.client.get(f"/imports/{batch.pk}/review/")
        self.assertEqual(review.context["form"]["timezone"].initial, "Asia/Colombo")

        # GPX starting 2026-12-23 06:00Z = 11:30 local, 1 point/second for 2 hours
        gpx = SimpleUploadedFile("ride.gpx", make_gpx(7200, start=(6.5, 80.0)).encode())
        response = self.client.post(f"/imports/{batch.pk}/review/", {
            "title": "Sri Lanka", "timezone": "Asia/Colombo", "travellers": [self.user.pk],
            "shift_0": "+0:00", "make_public": "on", "gpx_files": gpx, "create": "1",
        })
        trip = Trip.objects.get(title="Sri Lanka")
        self.assertRedirects(response, f"/trips/{trip.pk}/", fetch_redirect_response=False)
        self.assertEqual((trip.start_date, trip.end_date), (date(2026, 12, 22), date(2026, 12, 24)))
        self.assertEqual(trip.timezone, "Asia/Colombo")
        self.assertEqual(list(trip.travellers.all()), [self.user])
        self.assertEqual(trip.tracks.count(), 1)
        self.assertEqual(trip.entries.count(), 3)
        middle = Media.objects.get(taken_at=datetime(2026, 12, 23, 6, 30, tzinfo=UTC))
        self.assertEqual(middle.location_source, "gpx")
        self.assertAlmostEqual(float(middle.latitude), 6.5 + 1800 * 0.00002, places=4)


class TripFromGPXTests(ImportTestCase):
    def test_dates_from_tracks_in_zone(self):
        """protects=AC12.1: dates come from GPX times converted to the trip's zone;
        fails_when=UTC dates are used (the 25th 18:00Z is the 25th 23:30 in Colombo) or a track is lost;
        no_claim=tracks crossing time zones."""
        first = SimpleUploadedFile("a.gpx", make_gpx(100).encode())  # starts 2026-12-23 06:00Z
        late = make_gpx(50).replace("2026-12-23T06:00", "2026-12-25T18:00")  # all 50 s in that minute
        response = self.client.post("/trips/from-gpx/", {
            "gpx_files": [first, SimpleUploadedFile("b.gpx", late.encode())], "mode": "bike",
            "timezone": "Asia/Colombo", "travellers": [self.user.pk],
        })
        trip = Trip.objects.get()
        self.assertRedirects(response, f"/trips/{trip.pk}/", fetch_redirect_response=False)
        self.assertEqual((trip.start_date, trip.end_date), (date(2026, 12, 23), date(2026, 12, 25)))
        self.assertEqual(trip.title, "Morning ride")
        self.assertEqual(sorted(t.mode for t in trip.tracks.all()), ["bike", "bike"])

    def test_no_timestamps_needs_dates_and_broken_file(self):
        """protects=AC12.2-3: untimed GPX needs dates; one broken file blocks the whole import, named;
        fails_when=a trip is created with today's date or with only the valid files;
        no_claim=partial-success imports (deliberately all-or-nothing)."""
        untimed = make_gpx(10).replace("<time>", "<!--").replace("</time>", "-->")
        response = self.client.post("/trips/from-gpx/", {
            "gpx_files": SimpleUploadedFile("u.gpx", untimed.encode()), "mode": "hike", "timezone": "UTC"})
        self.assertContains(response, "no timestamps")
        response = self.client.post("/trips/from-gpx/", {
            "gpx_files": [SimpleUploadedFile("ok.gpx", make_gpx(10).encode()),
                          SimpleUploadedFile("bad.gpx", b"<gpx><trk>")],
            "mode": "hike", "timezone": "UTC"})
        self.assertContains(response, "bad.gpx")
        self.assertFalse(Trip.objects.exists())
        self.assertFalse(Track.objects.exists())
