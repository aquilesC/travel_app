"""Positions (v4 #26)."""

from datetime import date, datetime, timedelta, timezone as dt_timezone

import gpxpy

from api.tests import ApiTestCase
from trips.models import Position, Trip
from trips.services.positions import day_km

START = datetime(2026, 12, 23, 6, 0, tzinfo=dt_timezone.utc)


def batch(n=100, start=START, step=timedelta(minutes=1), lat=6.93, lon=79.85):
    return [{"recorded_at": (start + i * step).isoformat(), "latitude": lat + i * 0.0005,
             "longitude": lon, "accuracy_m": 15} for i in range(n)]


class PositionTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.trip = Trip.objects.create(title="Sri Lanka", start_date=date(2026, 12, 21),
                                        end_date=date(2027, 1, 10), timezone="Asia/Colombo",
                                        created_by=self.user)
        self.trip.travellers.add(self.user)
        self.token_value = self.token()

    def post(self, points, trip=None):
        return self.api("post", f"/trips/{(trip or self.trip).pk}/positions", token=self.token_value,
                        data={"points": points})


class PositionTests(PositionTestCase):
    def test_batch_is_idempotent(self):
        first = self.post(batch())
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json(), {"accepted": 100, "duplicates": 0, "rejected": []})
        again = self.post(batch())
        self.assertEqual(again.json(), {"accepted": 0, "duplicates": 100, "rejected": []})
        self.assertEqual(Position.objects.count(), 100)

    def test_bad_points_are_rejected_individually(self):
        points = batch()
        points[3]["accuracy_m"] = 900
        points[10]["recorded_at"] = "2026-11-01T10:00:00+00:00"  # weeks before the trip
        points[20]["latitude"] = 95
        response = self.post(points)
        body = response.json()
        self.assertEqual(body["accepted"], 97)
        self.assertEqual([r["index"] for r in body["rejected"]], [3, 10, 20])

    def test_non_member_gets_404(self):
        other = Trip.objects.create(title="Not mine", start_date=date(2026, 12, 21),
                                    end_date=date(2027, 1, 10), created_by=self.user)
        self.assertError(self.post(batch(), trip=other), 404, "not_found")

    def test_list_with_cursor(self):
        self.post(batch(30))
        url = f"/trips/{self.trip.pk}/positions?limit=20"
        page = self.api("get", url, token=self.token_value).json()
        self.assertEqual(len(page["items"]), 20)
        rest = self.api("get", f"{url}&cursor={page['next_cursor'].replace('+', '%2B')}",
                        token=self.token_value).json()
        self.assertEqual(len(rest["items"]), 10)
        self.assertIsNone(rest["next_cursor"])

    def test_gpx_export_round_trips(self):
        self.post(batch(50))
        response = self.api("get", f"/trips/{self.trip.pk}/positions.gpx?day=2026-12-23",
                            token=self.token_value)
        self.assertEqual(response.status_code, 200, response.content)
        gpx = gpxpy.parse(response.content.decode())
        self.assertEqual(sum(len(s.points) for t in gpx.tracks for s in t.segments), 50)

    def test_members_map_shows_recorded_path_share_map_does_not(self):
        self.post(batch(50))
        self.client.force_login(self.user)
        members = self.client.get(f"/api/v1/trips/{self.trip.pk}/map").json()
        recorded = [f for f in members["features"] if f["properties"]["kind"] == "recorded"]
        self.assertEqual(len(recorded), 1)
        shared = self.client.get(f"/api/v1/share/{self.trip.share_token}/map").json()
        self.assertFalse([f for f in shared["features"] if f["properties"]["kind"] == "recorded"])

    def test_gaps_break_the_line_and_distance(self):
        points = batch(10) + batch(10, start=START + timedelta(hours=2), lat=7.5)
        self.post(points)
        self.client.force_login(self.user)
        feature = next(f for f in self.client.get(f"/api/v1/trips/{self.trip.pk}/map").json()["features"]
                       if f["properties"]["kind"] == "recorded")
        self.assertEqual(len(feature["geometry"]["coordinates"]), 2)
        # 2 × 9 steps of 0.0005° latitude ≈ 2 × 0.5 km; the 2-hour jump isn't counted.
        self.assertAlmostEqual(day_km(self.trip, self.user, date(2026, 12, 23)), 1.0, delta=0.05)

    def test_trip_page_shows_km_today(self):
        now = datetime.now(dt_timezone.utc).replace(microsecond=0)
        self.trip.start_date, self.trip.end_date = now.date() - timedelta(days=1), now.date() + timedelta(days=1)
        self.trip.save()
        self.post(batch(10, start=now - timedelta(minutes=12)))
        self.client.force_login(self.user)
        self.assertContains(self.client.get(f"/trips/{self.trip.pk}/"), "Recorded by app today")


class PhotoPlacementTests(PositionTestCase):
    def test_photo_without_gps_is_placed_from_recorded_positions(self):
        from trips.importing import gpx_position, location_series

        self.post(batch(60))
        series = location_series(self.trip, self.user)
        lat, lon = gpx_position(series, START + timedelta(minutes=5, seconds=30))
        self.assertAlmostEqual(lat, 6.93 + 5.5 * 0.0005, places=5)
        self.assertEqual(location_series(self.trip), [])  # no user → GPX tracks only
