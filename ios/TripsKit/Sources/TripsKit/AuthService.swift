import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Raw HTTP for the few calls outside the generated API (allauth's login/logout).
public protocol HTTPSending: Sendable {
    func send(_ request: URLRequest) async throws -> (Data, Int)
}

public struct URLSessionSender: HTTPSending {
    let session: URLSession
    public init(session: URLSession = .shared) { self.session = session }

    public func send(_ request: URLRequest) async throws -> (Data, Int) {
        do {
            let (data, response) = try await session.data(for: request)
            return (data, (response as? HTTPURLResponse)?.statusCode ?? 0)
        } catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost,
                                             .timedOut, .cannotFindHost, .cannotConnectToHost].contains(error.code) {
            throw TripsError.offline
        }
    }
}

/// Logs in through allauth's headless "app" client (v4 #22). The token goes into the TokenStore.
public struct AuthService: Sendable {
    let server: URL
    let http: HTTPSending
    let tokens: TokenStore
    let userAgent: String

    public init(server: URL, http: HTTPSending = URLSessionSender(), tokens: TokenStore, userAgent: String) {
        self.server = server
        self.http = http
        self.tokens = tokens
        self.userAgent = userAgent
    }

    public var isLoggedIn: Bool { tokens.load() != nil }

    public func login(email: String, password: String) async throws {
        var request = URLRequest(url: server.appending(path: "_allauth/app/v1/auth/login"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["email": email, "password": password])
        let (data, status) = try await http.send(request)
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if status == 200, let meta = json["meta"] as? [String: Any], let token = meta["session_token"] as? String {
            tokens.save(token)
            return
        }
        if status == 429 {
            throw TripsError.wrongCredentials("Too many attempts. Try again in a few minutes.")
        }
        let messages = (json["errors"] as? [[String: Any]])?.compactMap { $0["message"] as? String } ?? []
        if status == 400 || status == 401 {
            throw TripsError.wrongCredentials(messages.first ?? "Email or password is not right.")
        }
        throw TripsError.server(status: status, message: messages.first ?? "Login failed.")
    }

    /// Signs out on the server too; the token is forgotten even when offline.
    public func logout() async {
        defer { tokens.save(nil) }
        guard let token = tokens.load() else { return }
        var request = URLRequest(url: server.appending(path: "_allauth/app/v1/auth/session"))
        request.httpMethod = "DELETE"
        request.setValue(token, forHTTPHeaderField: "X-Session-Token")
        _ = try? await http.send(request)
    }
}
