import Foundation
import Network
import Observation

/// Online / wifi state, so the outbox knows when large files may go (ios #5).
@MainActor @Observable
final class NetworkMonitor {
    private(set) var isOnline = true
    /// Wifi or wired: not "expensive" (cellular or a personal hotspot).
    private(set) var isOnWifi = false
    var onChange: (@MainActor () -> Void)?

    private let monitor = NWPathMonitor()

    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                guard let self else { return }
                let wasOnline = self.isOnline, wasWifi = self.isOnWifi
                self.isOnline = path.status == .satisfied
                self.isOnWifi = path.status == .satisfied && !path.isExpensive
                if self.isOnline != wasOnline || self.isOnWifi != wasWifi { self.onChange?() }
            }
        }
        monitor.start(queue: DispatchQueue(label: "trips.network"))
    }
}
