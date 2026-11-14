import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession
import TripsAPI
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Adds the login token and the app's User-Agent to every API request, and tells the app
/// when the server no longer accepts the token (signed out on the website, ios #2).
public struct AuthMiddleware: ClientMiddleware {
    let tokens: TokenStore
    let userAgent: String
    let onUnauthorized: @Sendable () -> Void

    public init(tokens: TokenStore, userAgent: String, onUnauthorized: @escaping @Sendable () -> Void = {}) {
        self.tokens = tokens
        self.userAgent = userAgent
        self.onUnauthorized = onUnauthorized
    }

    public func intercept(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String,
                          next: (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?))
        async throws -> (HTTPResponse, HTTPBody?) {
        var request = request
        if let token = tokens.load() {
            request.headerFields[HTTPField.Name("X-Session-Token")!] = token
        }
        request.headerFields[.userAgent] = userAgent
        let (response, responseBody) = try await next(request, body, baseURL)
        if response.status.code == 401, operationID != "health" {
            onUnauthorized()
        }
        return (response, responseBody)
    }
}

/// Django writes fractional seconds only when they aren't zero ("…:05Z" vs "…:05.123456Z"),
/// so decoding accepts both. Encoding always sends fractions.
public struct FlexibleISO8601: DateTranscoder {
    public init() {}

    public func encode(_ date: Date) throws -> String {
        date.formatted(.iso8601.year().month().day().time(includingFractionalSeconds: true).timeZone(separator: .omitted))
    }

    public func decode(_ text: String) throws -> Date {
        if let date = try? Date(text, strategy: .iso8601.year().month().day().time(includingFractionalSeconds: true)
                                    .timeZone(separator: .colon)) { return date }
        if let date = try? Date(text, strategy: .iso8601) { return date }
        if let date = try? Date(text, strategy: .iso8601.year().month().day().time(includingFractionalSeconds: true)) {
            return date
        }
        throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "Not an ISO 8601 date: \(text)"))
    }
}

public enum APIFactory {
    /// The generated client. `server` is the site root (e.g. https://trips.aquiles.me): the
    /// contract's paths already start with /api/v1.
    public static func client(server: URL, tokens: TokenStore, userAgent: String,
                              onUnauthorized: @escaping @Sendable () -> Void = {},
                              session: URLSession = .shared) -> Client {
        Client(
            serverURL: server,
            configuration: .init(dateTranscoder: FlexibleISO8601()),
            transport: URLSessionTransport(configuration: .init(session: session)),
            middlewares: [AuthMiddleware(tokens: tokens, userAgent: userAgent, onUnauthorized: onUnauthorized)]
        )
    }
}
