import Foundation
import TripsAPI

/// A file waiting to be sent. The app copies it into the outbox directory first, so it
/// survives the photo library changing and app restarts.
public struct OutboxFile: Codable, Sendable, Equatable, Identifiable {
    public var id: UUID                 // also the upload's client_id: retries resume
    public var relativePath: String     // inside the outbox directory
    public var filename: String
    public var size: Int
    public var sha256: String?
    public var uploadID: String?        // set once the server has the whole file
    public var done = false

    public init(id: UUID = UUID(), relativePath: String, filename: String, size: Int) {
        self.id = id
        self.relativePath = relativePath
        self.filename = filename
        self.size = size
    }
}

/// A post written in the app (ios #6).
public struct PostDraft: Codable, Sendable, Equatable {
    public var occurredAt: Date
    public var body: String
    public var placeName: String
    public var latitude: Double?
    public var longitude: Double?
    public var isPublic: Bool
    /// Start a new chapter first (and make it the current one), like WhatsApp's #chapter.
    public var newChapterTitle: String?
    public var createdChapterID: Int?

    public init(occurredAt: Date = Date(), body: String, placeName: String = "", latitude: Double? = nil,
                longitude: Double? = nil, isPublic: Bool = true, newChapterTitle: String? = nil) {
        self.occurredAt = occurredAt
        self.body = body
        self.placeName = placeName
        self.latitude = latitude
        self.longitude = longitude
        self.isPublic = isPublic
        self.newChapterTitle = newChapterTitle
    }
}

public struct OutboxItem: Codable, Sendable, Equatable, Identifiable {
    public enum Kind: Codable, Sendable, Equatable {
        case post(PostDraft)
        /// Photos picked in the app → an import the server groups into draft entries (ios #7).
        case photoImport(batchID: String?, makePublic: Bool)
    }

    public enum State: Codable, Sendable, Equatable {
        case pending
        case done(resultID: String)     // entry id, or import batch id
        case failed(String)             // needs the user (e.g. a file the server refuses)
    }

    public var id: UUID                 // client_id for the entry / import: retries are safe
    public var tripID: Int
    public var kind: Kind
    public var files: [OutboxFile]
    public var state: State = .pending
    public var lastError: String?
    public var sendAnyway = false       // "Send now anyway" over cellular
    public var createdAt: Date

    public init(id: UUID = UUID(), tripID: Int, kind: Kind, files: [OutboxFile], createdAt: Date = Date()) {
        self.id = id
        self.tripID = tripID
        self.kind = kind
        self.files = files
        self.createdAt = createdAt
    }

    public var totalBytes: Int { files.reduce(0) { $0 + $1.size } }
    public var isPending: Bool { state == .pending }
}

/// The server calls the outbox makes besides uploads.
public protocol OutboxAPI: Sendable {
    func createChapter(tripID: Int, title: String) async throws -> Int
    /// Returns the entry id. Same client id → same entry.
    func createEntry(tripID: Int, draft: PostDraft, uploadIDs: [String], clientID: String) async throws -> Int
    /// Returns the batch id. Same client id → same batch.
    func startImport(tripID: Int, clientID: String) async throws -> String
}

/// Everything the app sends except positions, in order, offline-first (ios #5).
///
/// Items are saved on disk the moment they're added. `process(onWifi:)` sends what it can:
/// files are uploaded in chunks and resumed after interruptions; large files wait for wifi
/// unless the user says otherwise; every create carries a client id so a retry after a
/// lost response never duplicates anything.
public actor Outbox {
    private let directory: URL
    private let file: JSONFile<[OutboxItem]>
    private let uploads: UploadAPI
    private let api: OutboxAPI
    private var items: [OutboxItem]
    private var processing = false
    public var settings: AppSettings
    /// Progress per file id, 0…1, for the outbox screen.
    public private(set) var progress: [UUID: Double] = [:]

    public init(directory: URL, uploads: UploadAPI, api: OutboxAPI, settings: AppSettings) {
        self.directory = directory
        file = JSONFile(url: directory.appending(path: "outbox.json"))
        items = file.read() ?? []
        self.uploads = uploads
        self.api = api
        self.settings = settings
    }

    public var all: [OutboxItem] { items }
    public var pendingCount: Int { items.filter(\.isPending).count }

    public func update(settings: AppSettings) { self.settings = settings }

    /// Where the app should copy files for a new item.
    public func fileURL(for relativePath: String) -> URL { directory.appending(path: relativePath) }

    public func add(_ item: OutboxItem) throws {
        items.append(item)
        try save()
    }

    public func sendAnyway(_ id: UUID) throws {
        guard let i = items.firstIndex(where: { $0.id == id }) else { return }
        items[i].sendAnyway = true
        try save()
    }

    public func retry(_ id: UUID) throws {
        guard let i = items.firstIndex(where: { $0.id == id }) else { return }
        items[i].state = .pending
        items[i].lastError = nil
        try save()
    }

    public func remove(_ id: UUID) throws {
        guard let i = items.firstIndex(where: { $0.id == id }) else { return }
        deleteFiles(of: items[i])
        items.remove(at: i)
        try save()
    }

    /// Forget finished items older than a day (the trip screen shows recent ones).
    public func pruneDone(now: Date = Date()) throws {
        items.removeAll { item in
            if case .done = item.state { return now.timeIntervalSince(item.createdAt) > 86_400 }
            return false
        }
        try save()
    }

    func waitsForWifi(_ item: OutboxItem, onWifi: Bool) -> Bool {
        !onWifi && settings.largeFilesOnWifiOnly && !item.sendAnyway
            && item.files.contains { !$0.done && $0.size > settings.largeFileBytes }
    }

    /// Send pending items in order. Returns how many finished. Safe to call often.
    @discardableResult
    public func process(onWifi: Bool) async -> Int {
        guard !processing else { return 0 }
        processing = true
        defer { processing = false }
        var finished = 0
        for index in items.indices where items[index].isPending {
            if waitsForWifi(items[index], onWifi: onWifi) {
                items[index].lastError = "Waiting for wifi (large files)."
                continue
            }
            do {
                try await send(index)
                finished += 1
            } catch let error as TripsError {
                switch error {
                case .invalidFile(let message):
                    items[index].state = .failed(message)  // retrying won't help
                case .offline, .notLoggedIn:
                    items[index].lastError = PositionUploader.describe(error)
                    try? save()
                    return finished  // the next items would fail the same way
                default:
                    items[index].lastError = PositionUploader.describe(error)
                }
            } catch {
                items[index].lastError = "Couldn't reach the server; will retry."
            }
            try? save()
        }
        return finished
    }

    private func send(_ index: Int) async throws {
        var item = items[index]
        let uploader = ChunkedUploader(api: uploads)
        switch item.kind {
        case .post(var draft):
            if let title = draft.newChapterTitle, draft.createdChapterID == nil {
                draft.createdChapterID = try await api.createChapter(tripID: item.tripID, title: title)
                item.kind = .post(draft)
                items[index] = item
                try save()
            }
            try await uploadFiles(&item, index: index, target: .trip(item.tripID), uploader: uploader)
            let entryID = try await api.createEntry(tripID: item.tripID, draft: draft,
                                                    uploadIDs: item.files.compactMap(\.uploadID),
                                                    clientID: item.id.uuidString.lowercased())
            item.state = .done(resultID: String(entryID))

        case .photoImport(let existing, let makePublic):
            var batchID = existing
            if batchID == nil {
                batchID = try await api.startImport(tripID: item.tripID, clientID: item.id.uuidString.lowercased())
                item.kind = .photoImport(batchID: batchID, makePublic: makePublic)
                items[index] = item
                try save()
            }
            try await uploadFiles(&item, index: index, target: .batch(batchID!), uploader: uploader)
            item.state = .done(resultID: batchID!)
        }
        item.lastError = nil
        deleteFiles(of: item)
        items[index] = item
        try save()
    }

    private func uploadFiles(_ item: inout OutboxItem, index: Int, target: UploadTarget,
                             uploader: ChunkedUploader) async throws {
        for f in item.files.indices where !item.files[f].done {
            let url = fileURL(for: item.files[f].relativePath)
            guard FileManager.default.fileExists(atPath: url.path) else {
                throw TripsError.invalidFile("\(item.files[f].filename) is missing from the phone.")
            }
            if item.files[f].sha256 == nil {
                item.files[f].sha256 = try FileHash.sha256(of: url)
            }
            let fileID = item.files[f].id
            let outcome = try await uploader.upload(
                file: url, filename: item.files[f].filename, sha256: item.files[f].sha256!, target: target,
                clientID: fileID.uuidString.lowercased(),
                progress: { [weak self] value in Task { await self?.setProgress(fileID, value) } })
            if case .uploaded(let uploadID) = outcome {
                item.files[f].uploadID = uploadID
            }
            item.files[f].done = true
            items[index] = item
            try save()
        }
    }

    private func setProgress(_ id: UUID, _ value: Double) { progress[id] = value }

    private func deleteFiles(of item: OutboxItem) {
        for f in item.files { try? FileManager.default.removeItem(at: fileURL(for: f.relativePath)) }
    }

    private func save() throws { try file.write(items) }
}

/// OutboxAPI over the generated client.
public struct APIOutbox: OutboxAPI {
    let client: Client

    public init(client: Client) { self.client = client }

    public func createChapter(tripID: Int, title: String) async throws -> Int {
        switch try await client.createChapter(path: .init(tripId: tripID),
                                              body: .json(.init(makeCurrent: true, title: title))) {
        case .created(let created): return try created.body.json.id
        case .undocumented(let status, _): throw APIUploads.fail(status, "Creating the chapter")
        }
    }

    public func createEntry(tripID: Int, draft: PostDraft, uploadIDs: [String], clientID: String) async throws -> Int {
        let body = Components.Schemas.EntryIn(
            body: draft.body, chapterId: draft.createdChapterID, clientId: clientID, isPublic: draft.isPublic,
            latitude: draft.latitude, longitude: draft.longitude, occurredAt: draft.occurredAt,
            placeName: draft.placeName, uploadIds: uploadIDs)
        switch try await client.createEntry(path: .init(tripId: tripID), body: .json(body)) {
        case .ok(let ok): return try ok.body.json.id
        case .created(let created): return try created.body.json.id
        case .undocumented(let status, _): throw APIUploads.fail(status, "Posting")
        }
    }

    public func startImport(tripID: Int, clientID: String) async throws -> String {
        switch try await client.startImport(path: .init(tripId: tripID), body: .json(.init(clientId: clientID))) {
        case .created(let created): return try created.body.json.id
        case .undocumented(let status, _): throw APIUploads.fail(status, "Starting the import")
        }
    }
}
