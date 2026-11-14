import Foundation
import TripsAPI

/// The server side of sending positions; the generated client in the app, a fake in tests.
public protocol PositionSending: Sendable {
    /// Returns the indices the server rejected (they are not retried).
    func send(tripID: Int, points: [LocationFix]) async throws -> (accepted: Int, rejected: [Int])
}

/// Sends recorded points in batches, at most every `uploadInterval` (ios #4). Call
/// `tick()` whenever a location update wakes the app, on foreground, and when the network
/// comes back; it decides whether it's time.
public actor PositionUploader {
    private let store: PositionStore
    private let sender: PositionSending
    private let tripID: Int
    public var uploadInterval: TimeInterval
    private var failures = 0
    private var nextAttempt: Date = .distantPast
    private var running = false

    public init(store: PositionStore, sender: PositionSending, tripID: Int, uploadInterval: TimeInterval) {
        self.store = store
        self.sender = sender
        self.tripID = tripID
        self.uploadInterval = uploadInterval
    }

    public func setUploadInterval(_ value: TimeInterval) { uploadInterval = value }

    /// Returns how many points were accepted (0 when it wasn't time or nothing to send).
    @discardableResult
    public func tick(now: Date = Date(), force: Bool = false) async -> Int {
        guard !running else { return 0 }
        if !force {
            if now < nextAttempt { return 0 }
            if let last = await store.lastUploadAt, now.timeIntervalSince(last) < uploadInterval { return 0 }
        }
        running = true
        defer { running = false }
        var accepted = 0
        while true {
            let batch = await store.unsent()
            if batch.isEmpty { break }
            do {
                let result = try await sender.send(tripID: tripID, points: batch)
                accepted += result.accepted
                try await store.markSent(batch, at: now)  // rejected points are dropped too
                failures = 0
                nextAttempt = .distantPast
                if batch.count < 5000 { break }
            } catch {
                failures += 1
                // 1, 2, 4… minutes, never longer than the upload interval
                let wait = min(uploadInterval, 60 * pow(2, Double(failures - 1)))
                nextAttempt = now.addingTimeInterval(wait)
                try? await store.recordFailure(Self.describe(error))
                break
            }
        }
        return accepted
    }

    static func describe(_ error: Error) -> String {
        if let error = error as? TripsError {
            switch error {
            case .offline: return "Offline; will retry."
            case .server(_, let message): return message
            case .notLoggedIn: return "Not logged in."
            case .wrongCredentials(let m), .invalidFile(let m): return m
            }
        }
        return "Couldn't reach the server; will retry."
    }
}

/// PositionSending over the generated client.
public struct APIPositionSender: PositionSending {
    let client: Client

    public init(client: Client) { self.client = client }

    public func send(tripID: Int, points: [LocationFix]) async throws -> (accepted: Int, rejected: [Int]) {
        let body = Components.Schemas.BatchIn(points: points.map {
            .init(accuracyM: $0.accuracy, altitudeM: $0.altitude, latitude: $0.latitude,
                  longitude: $0.longitude, recordedAt: $0.recordedAt, speedMps: $0.speed)
        })
        let response = try await client.addPositions(path: .init(tripId: tripID), body: .json(body))
        switch response {
        case .ok(let ok):
            let out = try ok.body.json
            return (out.accepted, out.rejected.map(\.index))
        case .undocumented(let status, _):
            throw status == 401 ? TripsError.notLoggedIn
                : TripsError.server(status: status, message: "The server refused the positions (\(status)).")
        }
    }
}
