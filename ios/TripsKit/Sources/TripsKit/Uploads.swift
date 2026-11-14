import Crypto
import Foundation
import OpenAPIRuntime
import TripsAPI

/// Where a finished upload goes (v4 #25).
public enum UploadTarget: Codable, Sendable, Hashable {
    case trip(Int)          // detached: an entry claims it later (posts)
    case batch(String)      // an import batch (photo picker)
}

public enum UploadOutcome: Sendable, Equatable {
    case uploaded(uploadID: String)    // detached, ready to attach
    case staged(itemID: Int)           // added to an import
    case skipped(String)               // the import already had it
}

/// The upload endpoints, so the chunk logic can be tested without a server.
public protocol UploadAPI: Sendable {
    func start(filename: String, size: Int, sha256: String, target: UploadTarget, clientID: String)
        async throws -> (id: String, received: Int, chunkSize: Int)
    func status(id: String) async throws -> Int
    /// Returns the new received size. A conflict (stale offset) also returns where to resume.
    func chunk(id: String, offset: Int, data: Data) async throws -> Int
    func complete(id: String) async throws -> UploadOutcome
    func existing(hashes: [String], tripID: Int?) async throws -> Set<String>
}

public enum FileHash {
    /// SHA-256 of a file, read in 1 MB blocks (videos can be large).
    public static func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let block = try handle.read(upToCount: 1 << 20), !block.isEmpty {
            hasher.update(data: block)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

/// Sends one file in chunks, resuming from what the server already has (ios #5).
public struct ChunkedUploader: Sendable {
    let api: UploadAPI

    public init(api: UploadAPI) { self.api = api }

    public func upload(file: URL, filename: String, sha256: String, target: UploadTarget, clientID: String,
                       progress: @Sendable (Double) -> Void = { _ in }) async throws -> UploadOutcome {
        let size = try FileManager.default.attributesOfItem(atPath: file.path)[.size] as? Int ?? 0
        guard size > 0 else { throw TripsError.invalidFile("\(filename) is empty.") }
        let started = try await api.start(filename: filename, size: size, sha256: sha256, target: target,
                                          clientID: clientID)
        var offset = started.received
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var stalls = 0
        while offset < size {
            try handle.seek(toOffset: UInt64(offset))
            let data = try handle.read(upToCount: min(started.chunkSize, size - offset)) ?? Data()
            let received = try await api.chunk(id: started.id, offset: offset, data: data)
            stalls = received > offset ? 0 : stalls + 1
            if stalls > 3 { throw TripsError.server(status: 409, message: "The upload of \(filename) is stuck.") }
            offset = received
            progress(Double(offset) / Double(size))
        }
        return try await api.complete(id: started.id)
    }
}

/// UploadAPI over the generated client.
public struct APIUploads: UploadAPI {
    let client: Client

    public init(client: Client) { self.client = client }

    static func fail(_ status: Int, _ what: String) -> TripsError {
        status == 401 ? .notLoggedIn : .server(status: status, message: "\(what) failed (\(status)).")
    }

    public func start(filename: String, size: Int, sha256: String, target: UploadTarget, clientID: String)
        async throws -> (id: String, received: Int, chunkSize: Int) {
        var body = Components.Schemas.UploadIn(clientId: clientID, filename: filename, sha256: sha256, size: size)
        switch target {
        case .trip(let id): body.tripId = id
        case .batch(let id): body.batchId = id
        }
        let response = try await client.startUpload(body: .json(body))
        let out: Components.Schemas.UploadOut
        switch response {
        case .ok(let ok): out = try ok.body.json
        case .created(let created): out = try created.body.json
        case .undocumented(let status, _): throw Self.fail(status, "Starting the upload")
        }
        return (out.id, out.received, out.chunkSize)
    }

    public func status(id: String) async throws -> Int {
        switch try await client.uploadStatus(path: .init(uploadId: id)) {
        case .ok(let ok): return try ok.body.json.received
        case .undocumented(let status, _): throw Self.fail(status, "Checking the upload")
        }
    }

    public func chunk(id: String, offset: Int, data: Data) async throws -> Int {
        let response = try await client.uploadChunk(path: .init(uploadId: id), query: .init(offset: offset),
                                                    body: .binary(HTTPBody(data)))
        switch response {
        case .ok(let ok): return try ok.body.json.received
        case .conflict(let conflict):
            if let received = try conflict.body.json.error.received { return received }
            throw TripsError.server(status: 409, message: try conflict.body.json.error.message)
        case .undocumented(let status, _): throw Self.fail(status, "Sending a chunk")
        }
    }

    public func complete(id: String) async throws -> UploadOutcome {
        switch try await client.uploadComplete(path: .init(uploadId: id)) {
        case .ok(let ok):
            let out = try ok.body.json
            if let skipped = out.skipped { return .skipped(skipped) }
            if let item = out.itemId { return .staged(itemID: item) }
            if let upload = out.uploadId { return .uploaded(uploadID: upload) }
            throw TripsError.server(status: 200, message: "Unexpected answer finishing the upload.")
        case .conflict(let conflict):
            throw TripsError.server(status: 409, message: try conflict.body.json.error.message)
        case .unprocessableContent(let invalid):
            throw TripsError.invalidFile(try invalid.body.json.error.message)
        case .undocumented(let status, _): throw Self.fail(status, "Finishing the upload")
        }
    }

    public func existing(hashes: [String], tripID: Int?) async throws -> Set<String> {
        switch try await client.mediaExists(body: .json(.init(sha256: hashes, tripId: tripID))) {
        case .ok(let ok): return Set(try ok.body.json.existing)
        case .undocumented(let status, _): throw Self.fail(status, "Checking for duplicates")
        }
    }
}
