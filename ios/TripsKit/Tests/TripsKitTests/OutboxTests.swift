import Foundation
import Testing
@testable import TripsKit

/// A fake server that stores chunks in memory and can drop the connection once.
final class FakeServer: UploadAPI, OutboxAPI, @unchecked Sendable {
    struct Upload { var size: Int; var data = Data(); var target: UploadTarget; var sha: String }
    var uploads: [String: Upload] = [:]
    var byClientID: [String: String] = [:]
    var entries: [String: (Int, [String])] = [:]   // client id → (entry id, upload ids)
    var chapters: [String] = []
    var imports: [String: String] = [:]
    var dropAfterChunks: Int? = nil
    var chunkCalls = 0
    var offline = false
    let chunkSize = 4

    func start(filename: String, size: Int, sha256: String, target: UploadTarget, clientID: String)
        async throws -> (id: String, received: Int, chunkSize: Int) {
        if offline { throw TripsError.offline }
        if let id = byClientID[clientID] { return (id, uploads[id]!.data.count, chunkSize) }
        let id = UUID().uuidString
        uploads[id] = Upload(size: size, target: target, sha: sha256)
        byClientID[clientID] = id
        return (id, 0, chunkSize)
    }

    func status(id: String) async throws -> Int { uploads[id]!.data.count }

    func chunk(id: String, offset: Int, data: Data) async throws -> Int {
        chunkCalls += 1
        if let limit = dropAfterChunks, chunkCalls > limit { dropAfterChunks = nil; throw TripsError.offline }
        if offset != uploads[id]!.data.count { return uploads[id]!.data.count }
        uploads[id]!.data.append(data)
        return uploads[id]!.data.count
    }

    func complete(id: String) async throws -> UploadOutcome {
        let upload = uploads[id]!
        guard upload.data.count == upload.size else { throw TripsError.server(status: 409, message: "incomplete") }
        if case .batch = upload.target { return .staged(itemID: 1) }
        return .uploaded(uploadID: id)
    }

    func existing(hashes: [String], tripID: Int?) async throws -> Set<String> { [] }

    func createChapter(tripID: Int, title: String) async throws -> Int { chapters.append(title); return chapters.count }

    func createEntry(tripID: Int, draft: PostDraft, uploadIDs: [String], clientID: String) async throws -> Int {
        if offline { throw TripsError.offline }
        if let existing = entries[clientID] { return existing.0 }
        entries[clientID] = (entries.count + 1, uploadIDs)
        return entries.count
    }

    func startImport(tripID: Int, clientID: String) async throws -> String {
        if let id = imports[clientID] { return id }
        imports[clientID] = UUID().uuidString
        return imports[clientID]!
    }
}

func outboxFile(_ outbox: Outbox, name: String, bytes: Data) async throws -> OutboxFile {
    let path = "files/\(UUID().uuidString)-\(name)"
    let url = await outbox.fileURL(for: path)
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try bytes.write(to: url)
    return OutboxFile(relativePath: path, filename: name, size: bytes.count)
}

@Suite struct OutboxTests {
    @Test func postWithMediaSurvivesADroppedConnection() async throws {
        let server = FakeServer()
        let dir = tempDir()
        let outbox = Outbox(directory: dir, uploads: server, api: server, settings: AppSettings())
        let voice = try await outboxFile(outbox, name: "voice.m4a", bytes: Data("0123456789".utf8))
        let photo = try await outboxFile(outbox, name: "IMG_1.heic", bytes: Data("abcdefgh".utf8))
        try await outbox.add(OutboxItem(tripID: 1, kind: .post(PostDraft(body: "Tea in Ella")), files: [voice, photo]))

        server.dropAfterChunks = 2            // the network drops during the first file
        #expect(await outbox.process(onWifi: true) == 0)
        #expect(await outbox.all.first?.lastError == "Offline; will retry.")

        // the app restarts: a new Outbox reads the same directory and resumes
        let again = Outbox(directory: dir, uploads: server, api: server, settings: AppSettings())
        #expect(await again.process(onWifi: true) == 1)
        let entry = try #require(server.entries.values.first)
        #expect(entry.1.count == 2)
        #expect(server.uploads.values.map(\.data).sorted { $0.count < $1.count }
                == [Data("abcdefgh".utf8), Data("0123456789".utf8)])
        // voice (10 bytes, 4-byte chunks): 2 sent, the 3rd dropped, then resumed from byte 8; photo: 2
        #expect(server.chunkCalls == 2 + 1 + 1 + 2)
        // files are deleted from the phone once sent
        #expect(!FileManager.default.fileExists(atPath: dir.appending(path: voice.relativePath).path))
    }

    @Test func retryAfterLostResponseDoesNotDuplicate() async throws {
        let server = FakeServer()
        let outbox = Outbox(directory: tempDir(), uploads: server, api: server, settings: AppSettings())
        let item = OutboxItem(tripID: 1, kind: .post(PostDraft(body: "x")), files: [])
        try await outbox.add(item)
        await outbox.process(onWifi: true)
        // simulate the response being lost: mark pending again and resend
        try await outbox.retry(item.id)
        await outbox.process(onWifi: true)
        #expect(server.entries.count == 1)
    }

    @Test func largeFilesWaitForWifiUnlessForced() async throws {
        let server = FakeServer()
        var settings = AppSettings()
        settings.largeFileBytes = 5
        let outbox = Outbox(directory: tempDir(), uploads: server, api: server, settings: settings)
        let video = try await outboxFile(outbox, name: "clip.mov", bytes: Data(repeating: 1, count: 12))
        let item = OutboxItem(tripID: 1, kind: .post(PostDraft(body: "big")), files: [video])
        try await outbox.add(item)
        try await outbox.add(OutboxItem(tripID: 1, kind: .post(PostDraft(body: "text only")), files: []))
        #expect(await outbox.process(onWifi: false) == 1)        // the text goes, the video waits
        #expect(await outbox.all.first?.lastError == "Waiting for wifi (large files).")
        try await outbox.sendAnyway(item.id)
        #expect(await outbox.process(onWifi: false) == 1)
        #expect(server.entries.count == 2)
    }

    @Test func newChapterIsCreatedOnce() async throws {
        let server = FakeServer()
        let outbox = Outbox(directory: tempDir(), uploads: server, api: server, settings: AppSettings())
        try await outbox.add(OutboxItem(tripID: 1, kind: .post(PostDraft(body: "x", newChapterTitle: "Hills")), files: []))
        server.offline = true
        await outbox.process(onWifi: true)
        server.offline = false
        await outbox.process(onWifi: true)
        #expect(server.chapters == ["Hills"])
        #expect(server.entries.count == 1)
    }

    @Test func missingFileFailsForGood() async throws {
        let server = FakeServer()
        let outbox = Outbox(directory: tempDir(), uploads: server, api: server, settings: AppSettings())
        let file = OutboxFile(relativePath: "files/gone.jpg", filename: "gone.jpg", size: 3)
        try await outbox.add(OutboxItem(tripID: 1, kind: .post(PostDraft(body: "x")), files: [file]))
        await outbox.process(onWifi: true)
        #expect(await outbox.all.first?.state == .failed("gone.jpg is missing from the phone."))
    }

    @Test func photoImportGoesIntoOneBatch() async throws {
        let server = FakeServer()
        let outbox = Outbox(directory: tempDir(), uploads: server, api: server, settings: AppSettings())
        let a = try await outboxFile(outbox, name: "a.jpg", bytes: Data("aaaa".utf8))
        let b = try await outboxFile(outbox, name: "b.jpg", bytes: Data("bbbbbb".utf8))
        try await outbox.add(OutboxItem(tripID: 1, kind: .photoImport(batchID: nil, makePublic: true), files: [a, b]))
        await outbox.process(onWifi: true)
        #expect(server.imports.count == 1)
        let targets = Set(server.uploads.values.map(\.target))
        #expect(targets.count == 1)
        guard case .done(let batch) = await outbox.all.first?.state else { Issue.record("not done"); return }
        #expect(targets.first == .batch(batch))
    }
}
