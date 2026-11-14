import Foundation
import Testing
@testable import TripsKit

let t0 = Date(timeIntervalSince1970: 1_798_000_020)  // 2026-12-23, on a minute boundary

func fix(_ seconds: TimeInterval, lat: Double = 6.9, lon: Double = 79.85, accuracy: Double = 10) -> LocationFix {
    LocationFix(recordedAt: t0.addingTimeInterval(seconds), latitude: lat, longitude: lon, accuracy: accuracy)
}

func tempDir() -> URL {
    let url = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
    try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}

@Suite struct SamplerTests {
    @Test func walkingOneFixPerSecondKeepsOnePerMinute() {
        var sampler = PositionSampler(interval: 60)
        var kept: [LocationFix] = []
        for s in 0..<1800 { kept += sampler.add(fix(Double(s), lat: 6.9 + Double(s) * 0.00002)) }
        kept += sampler.flush()
        #expect(kept.count == 30)  // ios #3 AC1: 30 minutes at 1/min → 28–31 points
    }

    @Test func mostAccurateFixInTheWindowWins() {
        var sampler = PositionSampler(interval: 60)
        _ = sampler.add(fix(0, accuracy: 50))
        _ = sampler.add(fix(20, lat: 6.95, accuracy: 5))
        _ = sampler.add(fix(40, accuracy: 30))
        let kept = sampler.add(fix(61, lat: 7.0))
        #expect(kept.map(\.accuracy) == [5])
    }

    @Test func standingStillKeepsAHeartbeatOnly() {
        var sampler = PositionSampler(interval: 300, heartbeat: 900)
        var kept: [LocationFix] = []
        for s in stride(from: 0.0, to: 3600, by: 10) { kept += sampler.add(fix(s)) }
        kept += sampler.flush()
        #expect(kept.count <= 5)  // ios #3 AC2: an hour standing still at 5-min interval
        #expect(kept.count >= 4)
    }

    @Test func badAccuracyIsIgnored() {
        var sampler = PositionSampler(interval: 60)
        #expect(sampler.add(fix(0, accuracy: 900)).isEmpty)
        #expect(sampler.flush().isEmpty)
    }
}

struct FakeSender: PositionSending {
    let log: Log
    final class Log: @unchecked Sendable {
        var batches: [[LocationFix]] = []
        var fail = false
    }

    func send(tripID: Int, points: [LocationFix]) async throws -> (accepted: Int, rejected: [Int]) {
        if log.fail { throw TripsError.offline }
        log.batches.append(points)
        return (points.count, [])
    }
}

@Suite struct UploaderTests {
    @Test func storeSurvivesRestart() async throws {
        let dir = tempDir()
        try await PositionStore(directory: dir, tripID: 1).append([fix(0), fix(60)])
        let reopened = PositionStore(directory: dir, tripID: 1)
        #expect(await reopened.unsentCount == 2)
    }

    @Test func uploadsOnlyWhenIntervalHasPassed() async throws {
        let store = PositionStore(directory: tempDir(), tripID: 1)
        let log = FakeSender.Log()
        let uploader = PositionUploader(store: store, sender: FakeSender(log: log), tripID: 1, uploadInterval: 900)
        try await store.append([fix(0), fix(60)])
        #expect(await uploader.tick(now: t0.addingTimeInterval(100)) == 2)
        try await store.append([fix(120)])
        #expect(await uploader.tick(now: t0.addingTimeInterval(200)) == 0)  // too soon
        #expect(await uploader.tick(now: t0.addingTimeInterval(200), force: true) == 1)  // "Send now"
        #expect(log.batches.map(\.count) == [2, 1])
        #expect(await store.unsentCount == 0)
    }

    @Test func offlinePointsPileUpAndGoInOneBatch() async throws {
        let store = PositionStore(directory: tempDir(), tripID: 1)
        let log = FakeSender.Log()
        log.fail = true
        let uploader = PositionUploader(store: store, sender: FakeSender(log: log), tripID: 1, uploadInterval: 900)
        for minute in 0..<120 { try await store.append([fix(Double(minute) * 60)]) }
        #expect(await uploader.tick(now: t0.addingTimeInterval(7200)) == 0)
        #expect(await store.lastError == "Offline; will retry.")
        log.fail = false
        // backoff: the next attempt waits a minute
        #expect(await uploader.tick(now: t0.addingTimeInterval(7210)) == 0)
        #expect(await uploader.tick(now: t0.addingTimeInterval(7270)) == 120)
        #expect(log.batches.count == 1)
        #expect(await store.lastError == nil)
    }
}

@Suite struct DateTests {
    @Test func acceptsDjangoDateFormats() throws {
        let t = FlexibleISO8601()
        let whole = try t.decode("2026-12-23T08:00:05Z")
        #expect(try t.decode("2026-12-23T08:00:05.250000Z").timeIntervalSince(whole) == 0.25)
        #expect(try t.decode("2026-12-23T13:30:05+05:30") == whole)
        #expect(try t.decode("2026-12-23T13:30:05.000001+05:30").timeIntervalSince(whole) < 0.001)
        #expect(throws: (any Error).self) { try t.decode("yesterday") }
        #expect(try t.decode(t.encode(whole)) == whole)
    }
}
