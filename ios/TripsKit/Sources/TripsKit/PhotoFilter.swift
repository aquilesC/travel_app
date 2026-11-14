import Foundation

/// The trip's days and clock, in the trip's own time zone (not the phone's).
public struct TripCalendar: Sendable {
    public let timeZone: TimeZone
    public let start: Date   // first day, 00:00 local
    public let end: Date     // day after the last day, 00:00 local
    var calendar: Calendar

    /// `startDay`/`endDay` as "YYYY-MM-DD" (the API's trip dates).
    public init?(timeZoneID: String, startDay: String, endDay: String) {
        guard let tz = TimeZone(identifier: timeZoneID) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = tz
        func day(_ text: String) -> Date? {
            let parts = text.split(separator: "-").compactMap { Int($0) }
            guard parts.count == 3 else { return nil }
            return calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2]))
        }
        guard let s = day(startDay), let e = day(endDay), let after = calendar.date(byAdding: .day, value: 1, to: e)
        else { return nil }
        self.timeZone = tz
        self.calendar = calendar
        self.start = s
        self.end = after
    }

    /// Midnight (trip time) of every trip day.
    public var days: [Date] {
        var result: [Date] = []
        var day = start
        while day < end {
            result.append(day)
            day = calendar.date(byAdding: .day, value: 1, to: day)!
        }
        return result
    }

    public func startOfDay(_ date: Date) -> Date { calendar.startOfDay(for: date) }

    /// "Day 6 of 14", or nil outside the trip.
    public func dayNumber(of date: Date) -> (day: Int, of: Int)? {
        guard date >= start, date < end else { return nil }
        let n = calendar.dateComponents([.day], from: start, to: startOfDay(date)).day! + 1
        return (n, days.count)
    }

    /// Whether `date` is on the trip, with a day of slack each side (as the server checks).
    public func covers(_ date: Date) -> Bool {
        date >= start.addingTimeInterval(-86_400) && date < end.addingTimeInterval(86_400)
    }
}

/// A photo or video from the library, reduced to what filtering needs.
public struct PhotoCandidate: Sendable, Hashable, Identifiable {
    public var id: String          // PHAsset.localIdentifier
    public var takenAt: Date?
    public var latitude: Double?
    public var longitude: Double?
    /// True when the location was estimated from the recorded path (no GPS in the photo).
    public var placedFromPath = false

    public init(id: String, takenAt: Date?, latitude: Double? = nil, longitude: Double? = nil) {
        self.id = id
        self.takenAt = takenAt
        self.latitude = latitude
        self.longitude = longitude
    }

    public var hasLocation: Bool { latitude != nil && longitude != nil }
}

public struct MapRegion: Sendable, Equatable {
    public var minLatitude, maxLatitude, minLongitude, maxLongitude: Double

    public init(minLatitude: Double, maxLatitude: Double, minLongitude: Double, maxLongitude: Double) {
        self.minLatitude = minLatitude
        self.maxLatitude = maxLatitude
        self.minLongitude = minLongitude
        self.maxLongitude = maxLongitude
    }

    public func contains(latitude: Double, longitude: Double) -> Bool {
        latitude >= minLatitude && latitude <= maxLatitude && longitude >= minLongitude && longitude <= maxLongitude
    }
}

/// The photo picker's filters (ios #7): a trip day, a time window within it, a map area.
public struct PhotoFilter: Sendable, Equatable {
    public var day: Date?                     // midnight, trip time
    public var fromMinute = 0                 // minutes after midnight
    public var toMinute = 24 * 60
    public var region: MapRegion?

    public init(day: Date? = nil, fromMinute: Int = 0, toMinute: Int = 24 * 60, region: MapRegion? = nil) {
        self.day = day
        self.fromMinute = fromMinute
        self.toMinute = toMinute
        self.region = region
    }

    public func matches(_ photo: PhotoCandidate) -> Bool {
        if let day {
            guard let taken = photo.takenAt else { return false }
            let from = day.addingTimeInterval(Double(fromMinute) * 60)
            let to = day.addingTimeInterval(Double(toMinute) * 60)
            guard taken >= from, taken < to else { return false }
        }
        if let region {
            guard let lat = photo.latitude, let lon = photo.longitude,
                  region.contains(latitude: lat, longitude: lon) else { return false }
        }
        return true
    }

    public func apply(_ photos: [PhotoCandidate]) -> [PhotoCandidate] { photos.filter(matches) }
}

public enum PathPlacement {
    /// Photos without GPS get a position from the recorded path: interpolated between the
    /// points around their time, if one is within `tolerance` (same idea as the server's import).
    public static func place(_ photos: [PhotoCandidate], on path: [LocationFix],
                             tolerance: TimeInterval = 600) -> [PhotoCandidate] {
        let points = path.sorted { $0.recordedAt < $1.recordedAt }
        guard !points.isEmpty else { return photos }
        let times = points.map(\.recordedAt)
        return photos.map { photo in
            guard !photo.hasLocation, let taken = photo.takenAt else { return photo }
            var i = 0, j = times.count
            while i < j { let m = (i + j) / 2; if times[m] < taken { i = m + 1 } else { j = m } }
            let before = i > 0 ? points[i - 1] : nil
            let after = i < points.count ? points[i] : nil
            var placed = photo
            if let b = before, let a = after,
               taken.timeIntervalSince(b.recordedAt) <= tolerance, a.recordedAt.timeIntervalSince(taken) <= tolerance {
                let span = a.recordedAt.timeIntervalSince(b.recordedAt)
                let f = span > 0 ? taken.timeIntervalSince(b.recordedAt) / span : 0
                placed.latitude = b.latitude + (a.latitude - b.latitude) * f
                placed.longitude = b.longitude + (a.longitude - b.longitude) * f
            } else if let near = [before, after].compactMap({ $0 })
                        .min(by: { abs($0.recordedAt.timeIntervalSince(taken)) < abs($1.recordedAt.timeIntervalSince(taken)) }),
                      abs(near.recordedAt.timeIntervalSince(taken)) <= tolerance {
                placed.latitude = near.latitude
                placed.longitude = near.longitude
            } else {
                return photo
            }
            placed.placedFromPath = true
            return placed
        }
    }

    /// Distance in km along a path, ignoring jumps after long silences (as the server does).
    public static func kilometres(_ path: [LocationFix], gap: TimeInterval = 1800) -> Double {
        zip(path, path.dropFirst()).reduce(0) { total, pair in
            pair.1.recordedAt.timeIntervalSince(pair.0.recordedAt) > gap ? total : total + pair.0.distance(to: pair.1) / 1000
        }
    }
}
