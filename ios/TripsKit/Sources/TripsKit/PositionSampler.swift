import Foundation

/// Turns the stream of fixes from the location service into at most one point per
/// recording interval (ios #3).
///
/// Time is cut into windows of `interval` seconds. Within a window the most accurate fix
/// wins; it is emitted when the first fix of a later window arrives (or on `flush()`).
/// While standing still (less than `stillRadius` from the last kept point) only one point
/// per `heartbeat` is kept, so a night in a hotel isn't hundreds of identical points.
public struct PositionSampler: Sendable {
    public var interval: TimeInterval
    public var heartbeat: TimeInterval
    public var stillRadius: Double
    public var maxAccuracy: Double

    private var pending: LocationFix?
    private var pendingWindow: Int?
    private var lastKept: LocationFix?

    public init(interval: TimeInterval, heartbeat: TimeInterval = 900, stillRadius: Double = 50,
                maxAccuracy: Double = 500, lastKept: LocationFix? = nil) {
        self.interval = max(1, interval)
        self.heartbeat = heartbeat
        self.stillRadius = stillRadius
        self.maxAccuracy = maxAccuracy
        self.lastKept = lastKept
    }

    private func window(of fix: LocationFix) -> Int {
        Int((fix.recordedAt.timeIntervalSince1970 / interval).rounded(.down))
    }

    private func better(_ a: LocationFix, than b: LocationFix) -> Bool {
        (a.accuracy ?? .infinity) < (b.accuracy ?? .infinity)
    }

    /// Feed one fix; returns the points to keep (zero or one).
    public mutating func add(_ fix: LocationFix) -> [LocationFix] {
        if let accuracy = fix.accuracy, accuracy < 0 || accuracy > maxAccuracy { return [] }
        let w = window(of: fix)
        if let current = pendingWindow, w == current {
            if let pending, !better(fix, than: pending) { return [] }
            pending = fix
            return []
        }
        if let current = pendingWindow, w < current { return [] }  // out of order: ignore
        let emitted = flush()
        pending = fix
        pendingWindow = w
        return emitted
    }

    /// Emit the best fix of the open window (e.g. when recording stops).
    public mutating func flush() -> [LocationFix] {
        defer { pending = nil; pendingWindow = nil }
        guard let candidate = pending else { return [] }
        if let last = lastKept, candidate.distance(to: last) < stillRadius,
           candidate.recordedAt.timeIntervalSince(last.recordedAt) < heartbeat {
            return []
        }
        lastKept = candidate
        return [candidate]
    }
}
