import Foundation

/// One position from the phone's location service, before or after sampling.
public struct LocationFix: Codable, Sendable, Hashable {
    public var recordedAt: Date
    public var latitude: Double
    public var longitude: Double
    /// Horizontal accuracy in metres (smaller is better). nil when unknown.
    public var accuracy: Double?
    public var altitude: Double?
    public var speed: Double?

    public init(recordedAt: Date, latitude: Double, longitude: Double,
                accuracy: Double? = nil, altitude: Double? = nil, speed: Double? = nil) {
        self.recordedAt = recordedAt
        self.latitude = latitude
        self.longitude = longitude
        self.accuracy = accuracy
        self.altitude = altitude
        self.speed = speed
    }

    /// Great-circle distance in metres.
    public func distance(to other: LocationFix) -> Double {
        let r = 6_371_008.8
        let (lat1, lat2) = (latitude * .pi / 180, other.latitude * .pi / 180)
        let dLat = lat2 - lat1
        let dLon = (other.longitude - longitude) * .pi / 180
        let h = sin(dLat / 2) * sin(dLat / 2) + cos(lat1) * cos(lat2) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * r * asin(min(1, sqrt(h)))
    }
}

/// What the user chooses in Settings (ios #3, #4, #5). Stored as JSON by the app.
public struct AppSettings: Codable, Sendable, Equatable {
    /// Keep at most one position per this many seconds.
    public var recordingInterval: TimeInterval
    /// Send the collected positions at most this often.
    public var uploadInterval: TimeInterval
    /// Files larger than this wait for wifi unless sent manually.
    public var largeFileBytes: Int
    public var largeFilesOnWifiOnly: Bool
    public var autoStartRecording: Bool

    public static let recordingChoices: [TimeInterval] = [30, 60, 120, 300, 900]
    public static let uploadChoices: [TimeInterval] = [300, 900, 1800, 3600]

    public init(recordingInterval: TimeInterval = 60, uploadInterval: TimeInterval = 900,
                largeFileBytes: Int = 20 * 1024 * 1024, largeFilesOnWifiOnly: Bool = true,
                autoStartRecording: Bool = false) {
        self.recordingInterval = recordingInterval
        self.uploadInterval = uploadInterval
        self.largeFileBytes = largeFileBytes
        self.largeFilesOnWifiOnly = largeFilesOnWifiOnly
        self.autoStartRecording = autoStartRecording
    }

    /// Rough battery cost shown next to each recording interval.
    public static func batteryHint(for interval: TimeInterval) -> String {
        switch interval {
        case ..<60: return "Uses the most battery"
        case ..<300: return "Noticeable battery use on a full day"
        case ..<900: return "Light battery use"
        default: return "Very light; the path is coarse"
        }
    }
}

/// Errors TripsKit reports to the app in plain words.
public enum TripsError: Error, Equatable, Sendable {
    case notLoggedIn
    case wrongCredentials(String)
    case server(status: Int, message: String)
    case offline
    case invalidFile(String)
}
