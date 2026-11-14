import Foundation
import Testing
import TripsAPI
@testable import TripsKit

/// End-to-end against a running website (a dev server, never production): the generated
/// client, login, positions, a post with media and a photo import, exactly as the app does it.
/// Runs only when TRIPS_E2E_URL, TRIPS_E2E_EMAIL and TRIPS_E2E_PASSWORD are set (ios/test.sh e2e).
let e2e = ProcessInfo.processInfo.environment

@Suite(.enabled(if: e2e["TRIPS_E2E_URL"] != nil), .serialized)
struct LiveServerTests {
    let server = URL(string: e2e["TRIPS_E2E_URL"] ?? "http://localhost")!
    let tokens = InMemoryTokenStore()

    func loggedIn() async throws -> Client {
        let auth = AuthService(server: server, tokens: tokens, userAgent: "TripsKit-e2e/1.0")
        try await auth.login(email: e2e["TRIPS_E2E_EMAIL"]!, password: e2e["TRIPS_E2E_PASSWORD"]!)
        return APIFactory.client(server: server, tokens: tokens, userAgent: "TripsKit-e2e/1.0")
    }

    func currentTrip(_ client: Client) async throws -> Components.Schemas.TripOut {
        let trips = try await client.listTrips().ok.body.json.items
        guard let trip = trips.first(where: { $0.current }) else {
            throw TripsError.server(status: 0, message: "Seed a trip that includes today (.gstack/tmp/seed.py).")
        }
        return trip
    }

    @Test func wrongPasswordIsReported() async throws {
        let auth = AuthService(server: server, tokens: tokens, userAgent: "TripsKit-e2e/1.0")
        await #expect(throws: TripsError.self) { try await auth.login(email: e2e["TRIPS_E2E_EMAIL"]!, password: "nope") }
        #expect(tokens.load() == nil)
    }

    @Test func entriesDecode() async throws {
        let client = try await loggedIn()
        let trip = try await currentTrip(client)
        let page = try await client.listEntries(path: .init(tripId: trip.id), query: .init(limit: 200)).ok.body.json
        #expect(!page.items.isEmpty)  // the seeded entry has a whole-second timestamp
    }

    @Test func positionsRoundTrip() async throws {
        let client = try await loggedIn()
        let trip = try await currentTrip(client)
        let store = PositionStore(directory: tempDir(), tripID: trip.id)
        let now = Date()
        try await store.append((0..<10).map { i in
            LocationFix(recordedAt: now.addingTimeInterval(Double(i - 10) * 60), latitude: 6.9 + Double(i) * 0.001,
                        longitude: 79.85, accuracy: 12)
        })
        let uploader = PositionUploader(store: store, sender: APIPositionSender(client: client), tripID: trip.id,
                                        uploadInterval: 900)
        #expect(await uploader.tick(force: true) == 10)
        let live = try await client.tripLive(path: .init(tripId: trip.id)).ok.body.json
        #expect(!live.travellers.isEmpty)
    }

    @Test func postWithVoiceNoteAndPhoto() async throws {
        let client = try await loggedIn()
        let trip = try await currentTrip(client)
        let outbox = Outbox(directory: tempDir(), uploads: APIUploads(client: client), api: APIOutbox(client: client),
                            settings: AppSettings())
        let voice = try await outboxFile(outbox, name: "voice.m4a", bytes: Data((0..<3000).map { UInt8($0 % 251) }))
        let photo = try await outboxFile(outbox, name: "IMG_\(UUID().uuidString.prefix(6)).jpg",
                                         bytes: Data((0..<5000).map { UInt8($0 % 241) }))
        let marker = "e2e \(UUID().uuidString)"
        try await outbox.add(OutboxItem(tripID: trip.id, kind: .post(PostDraft(body: marker, placeName: "Ella",
                                                                                latitude: 6.866, longitude: 81.046)),
                                        files: [voice, photo]))
        #expect(await outbox.process(onWifi: true) == 1)
        guard case .done(let entryID) = await outbox.all[0].state else { Issue.record("\(await outbox.all)"); return }
        let entry = try await client.entryDetail(path: .init(entryId: Int(entryID)!)).ok.body.json
        #expect(entry.body == marker)
        #expect(entry.source == "app")
        #expect(entry.media.map(\.kind) == ["audio", "photo"])
    }

    @Test func photoImportIsOpenForReview() async throws {
        let client = try await loggedIn()
        let trip = try await currentTrip(client)
        let outbox = Outbox(directory: tempDir(), uploads: APIUploads(client: client), api: APIOutbox(client: client),
                            settings: AppSettings())
        // the server skips files it can't read as photos; that's fine here, the batch flow is what's tested
        let file = try await outboxFile(outbox, name: "IMG_\(UUID().uuidString.prefix(6)).jpg", bytes: Data(repeating: 7, count: 64))
        try await outbox.add(OutboxItem(tripID: trip.id, kind: .photoImport(batchID: nil, makePublic: true), files: [file]))
        await outbox.process(onWifi: true)
        let state = await outbox.all[0].state
        guard case .done(let batch) = state else { Issue.record("\(state)"); return }
        let detail = try await client.importDetail(path: .init(batchId: batch)).ok.body.json
        #expect(detail.status == "open")
        #expect(detail.reviewUrl?.hasSuffix("/imports/\(batch)/review/") == true)
    }
}
