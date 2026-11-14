import Foundation

/// Where the app keeps its login token. The app uses the Keychain; tests use memory.
public protocol TokenStore: Sendable {
    func load() -> String?
    func save(_ token: String?)
}

public final class InMemoryTokenStore: TokenStore, @unchecked Sendable {
    private let lock = NSLock()
    private var token: String?

    public init(_ token: String? = nil) { self.token = token }

    public func load() -> String? { lock.withLock { token } }
    public func save(_ token: String?) { lock.withLock { self.token = token } }
}
