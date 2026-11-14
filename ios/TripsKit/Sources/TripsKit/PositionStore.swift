import Foundation

/// Recorded points waiting to be sent, kept on disk so nothing is lost offline or when
/// iOS stops the app (ios #3, #4). One file per trip.
public actor PositionStore {
    public struct Point: Codable, Sendable, Equatable {
        public var fix: LocationFix
        public var sent: Bool
    }

    struct State: Codable, Sendable {
        var points: [Point] = []
        var lastUploadAt: Date?
        var lastError: String?
    }

    private let file: JSONFile<State>
    private var state: State
    /// Sent points older than this are dropped from the phone (the server has them).
    public let keepSent: TimeInterval

    public init(directory: URL, tripID: Int, keepSent: TimeInterval = 30 * 86_400) {
        file = JSONFile(url: directory.appending(path: "positions-\(tripID).json"))
        state = file.read() ?? State()
        self.keepSent = keepSent
    }

    public func append(_ fixes: [LocationFix]) throws {
        guard !fixes.isEmpty else { return }
        state.points += fixes.map { Point(fix: $0, sent: false) }
        try save()
    }

    public func unsent(limit: Int = 5000) -> [LocationFix] {
        Array(state.points.lazy.filter { !$0.sent }.prefix(limit).map(\.fix))
    }

    public var unsentCount: Int { state.points.reduce(0) { $0 + ($1.sent ? 0 : 1) } }
    public var lastUploadAt: Date? { state.lastUploadAt }
    public var lastError: String? { state.lastError }
    public var lastPoint: LocationFix? { state.points.last?.fix }

    /// Points recorded since `start` (for today's path and distance on the trip screen).
    public func points(since start: Date) -> [LocationFix] {
        state.points.map(\.fix).filter { $0.recordedAt >= start }
    }

    public func markSent(_ fixes: [LocationFix], at now: Date = Date()) throws {
        let times = Set(fixes.map(\.recordedAt))
        for i in state.points.indices where times.contains(state.points[i].fix.recordedAt) {
            state.points[i].sent = true
        }
        state.lastUploadAt = now
        state.lastError = nil
        state.points.removeAll { $0.sent && now.timeIntervalSince($0.fix.recordedAt) > keepSent }
        try save()
    }

    public func recordFailure(_ message: String) throws {
        state.lastError = message
        try save()
    }

    private func save() throws { try file.write(state) }
}
