import Foundation
import Testing
@testable import TripsKit

@Suite struct PhotoFilterTests {
    let cal = TripCalendar(timeZoneID: "Asia/Colombo", startDay: "2026-12-21", endDay: "2027-01-03")!

    @Test func tripDaysAreInTheTripsTimeZone() {
        #expect(cal.days.count == 14)
        // 2026-12-21 00:00 in Colombo is 2026-12-20 18:30 UTC
        #expect(cal.days[0] == Date(timeIntervalSince1970: 1_797_791_400))
        #expect(cal.dayNumber(of: cal.days[5].addingTimeInterval(3600))! == (6, 14))
        #expect(cal.dayNumber(of: cal.end) == nil)
    }

    @Test func dayTimeAndAreaFilters() {
        let day3 = cal.days[2]
        let photos = [
            PhotoCandidate(id: "temple", takenAt: day3.addingTimeInterval(15 * 3600), latitude: 7.29, longitude: 80.64),
            PhotoCandidate(id: "morning", takenAt: day3.addingTimeInterval(8 * 3600), latitude: 7.29, longitude: 80.64),
            PhotoCandidate(id: "beach", takenAt: day3.addingTimeInterval(16 * 3600), latitude: 6.03, longitude: 80.21),
            PhotoCandidate(id: "nodate", takenAt: nil),
        ]
        let area = MapRegion(minLatitude: 7.2, maxLatitude: 7.4, minLongitude: 80.5, maxLongitude: 80.8)
        let filter = PhotoFilter(day: day3, fromMinute: 14 * 60, toMinute: 18 * 60, region: area)
        #expect(filter.apply(photos).map(\.id) == ["temple"])
        #expect(PhotoFilter(day: day3).apply(photos).count == 3)
    }

    @Test func photosWithoutGPSArePlacedOnThePath() {
        let path = [fix(0, lat: 7.0, lon: 80.0), fix(600, lat: 7.1, lon: 80.0)]
        let placed = PathPlacement.place([
            PhotoCandidate(id: "mid", takenAt: t0.addingTimeInterval(300)),
            PhotoCandidate(id: "late", takenAt: t0.addingTimeInterval(4000)),
            PhotoCandidate(id: "gps", takenAt: t0.addingTimeInterval(300), latitude: 1, longitude: 2),
        ], on: path)
        #expect(abs(placed[0].latitude! - 7.05) < 1e-9)
        #expect(placed[0].placedFromPath)
        #expect(!placed[1].hasLocation)
        #expect(placed[2].latitude == 1 && !placed[2].placedFromPath)
    }

    @Test func distanceIgnoresLongSilences() {
        let path = [fix(0, lat: 7.0), fix(60, lat: 7.01), fix(7200, lat: 8.0), fix(7260, lat: 8.01)]
        #expect(abs(PathPlacement.kilometres(path) - 2.224) < 0.01)
    }
}
