import CoreLocation
import Foundation
import Observation
import TripsAPI
import TripsKit
import UserNotifications

/// Everything the screens need, in one place (ios #2–#8).
@MainActor @Observable
final class AppModel {
    // Configuration
    let server: URL
    let userAgent: String
    private let tokens = KeychainTokenStore()
    private(set) var client: Client
    private let auth: AuthService

    // State shown on screen
    enum Phase: Equatable { case loggedOut, loading, ready }
    private(set) var phase: Phase = .loggedOut
    private(set) var me: Components.Schemas.MeOut?
    private(set) var trips: [Components.Schemas.TripOut] = []
    private(set) var trip: Components.Schemas.TripDetailOut?
    var errorMessage: String?
    private(set) var clockSkew: TimeInterval = 0

    var settings: AppSettings { didSet { saveSettings(); applySettings() } }

    // Per-trip machinery
    let recorder = LocationRecorder()
    let network = NetworkMonitor()
    private(set) var positions: PositionStore?
    private(set) var uploader: PositionUploader?
    private(set) var outbox: Outbox
    private(set) var todayPath: [LocationFix] = []
    private(set) var unsentPositions = 0
    private(set) var lastShared: Date?
    private(set) var shareError: String?
    private(set) var outboxItems: [OutboxItem] = []

    private let defaults = UserDefaults.standard
    private let dataDir: URL

    init() {
        let configured = Bundle.main.object(forInfoDictionaryKey: "TripsServerURL") as? String
        let override = UserDefaults.standard.string(forKey: "serverURL")  // Debug builds: Settings
        server = URL(string: override ?? configured ?? "https://trips.aquiles.me")!
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
        userAgent = "Trips/\(version) (iPhone; iOS \(ProcessInfo.processInfo.operatingSystemVersionString))"
        dataDir = URL.applicationSupportDirectory.appending(path: "Trips")
        settings = (defaults.data(forKey: "settings")).flatMap { try? JSONDecoder().decode(AppSettings.self, from: $0) }
            ?? AppSettings()
        auth = AuthService(server: server, tokens: tokens, userAgent: userAgent)
        client = APIFactory.client(server: server, tokens: tokens, userAgent: userAgent)
        outbox = Outbox(directory: dataDir.appending(path: "outbox"), uploads: APIUploads(client: client),
                        api: APIOutbox(client: client), settings: AppSettings())
        // Every stored property is set; now build the client again with the 401 hook, which needs self.
        client = APIFactory.client(server: server, tokens: tokens, userAgent: userAgent,
                                   onUnauthorized: { [weak self] in Task { @MainActor in self?.sessionEnded() } })
        outbox = Outbox(directory: dataDir.appending(path: "outbox"), uploads: APIUploads(client: client),
                        api: APIOutbox(client: client), settings: settings)

        recorder.onPoints = { [weak self] points in self?.record(points) }
        network.onChange = { [weak self] in self?.kick() }
        if auth.isLoggedIn { Task { await loadAfterLogin() } }
    }

    // MARK: Login (ios #2)

    func login(email: String, password: String) async {
        errorMessage = nil
        do {
            try await auth.login(email: email, password: password)
            await loadAfterLogin()
        } catch TripsError.wrongCredentials(let message) {
            errorMessage = message
        } catch TripsError.offline {
            errorMessage = "No internet connection."
        } catch {
            errorMessage = "Couldn't log in. Try again in a moment."
        }
    }

    var hasUnsentWork: Bool { unsentPositions > 0 || outboxItems.contains(where: \.isPending) }

    func logout() async {
        recorder.stop()
        await auth.logout()
        phase = .loggedOut
        me = nil
        trips = []
        trip = nil
    }

    private func sessionEnded() {
        guard phase != .loggedOut else { return }
        recorder.stop()
        tokens.save(nil)
        phase = .loggedOut
        errorMessage = "You were signed out. Log in again; nothing waiting to be sent was lost."
    }

    private func loadAfterLogin() async {
        phase = .loading
        do {
            me = try await client.me().ok.body.json
            if let health = try? await client.health().ok.body.json,
               let serverTime = try? FlexibleISO8601().decode(health.serverTime) {
                clockSkew = Date().timeIntervalSince(serverTime)
            }
            try await refreshTrips()
            phase = .ready
        } catch {
            phase = auth.isLoggedIn ? .ready : .loggedOut
            errorMessage = "Couldn't load your trips. Pull to refresh."
        }
    }

    func refreshTrips() async throws {
        trips = try await client.listTrips().ok.body.json.items
        let remembered = defaults.integer(forKey: "tripID")
        let pick = trips.first { $0.id == remembered } ?? trips.first(where: \.current) ?? trips.first
        if let pick { await select(tripID: pick.id) }
    }

    // MARK: Trip (ios #2, #8)

    func select(tripID: Int) async {
        guard trip?.id != tripID || positions == nil else { return }
        if recorder.isRecording { recorder.stop() }
        defaults.set(tripID, forKey: "tripID")
        do {
            trip = try await client.tripDetail(path: .init(tripId: tripID)).ok.body.json
        } catch {
            errorMessage = "Couldn't open that trip."
            return
        }
        let store = PositionStore(directory: dataDir.appending(path: "positions"), tripID: tripID)
        positions = store
        uploader = PositionUploader(store: store, sender: APIPositionSender(client: client), tripID: tripID,
                                    uploadInterval: settings.uploadInterval)
        await refreshStatus()
        if defaults.bool(forKey: "recording-\(tripID)"), calendar?.covers(Date()) == true {
            startRecording()  // it was on when the app was stopped (ios #3 AC3)
        } else if settings.autoStartRecording, calendar?.covers(Date()) == true, !defaults.bool(forKey: "stopped-\(tripID)") {
            startRecording()
        }
    }

    var calendar: TripCalendar? {
        guard let trip else { return nil }
        return TripCalendar(timeZoneID: trip.timezone, startDay: trip.startDate, endDay: trip.endDate)
    }

    // MARK: Recording (ios #3, #4)

    func startRecording() {
        guard let trip else { return }
        Diagnostics.log.info("recording on, every \(self.settings.recordingInterval) s")
        Task {
            let last = await positions?.lastPoint
            recorder.start(interval: settings.recordingInterval, lastKept: last)
        }
        defaults.set(true, forKey: "recording-\(trip.id)")
        defaults.set(false, forKey: "stopped-\(trip.id)")
    }

    func stopRecording() {
        recorder.stop()
        if let trip {
            defaults.set(false, forKey: "recording-\(trip.id)")
            defaults.set(true, forKey: "stopped-\(trip.id)")
        }
        Task { await sendPositions(force: true) }
    }

    private func record(_ points: [LocationFix]) {
        guard let positions else { return }
        Task {
            try? await positions.append(points)
            Diagnostics.log.debug("kept \(points.count) point(s), accuracy \(points.last?.accuracy ?? -1) m")
            // Stop by itself after the trip (end date + 1 day), ios #3.
            if let calendar, !calendar.covers(Date()) { stopRecording() }
            await sendPositions(force: false)
        }
    }

    func sendPositions(force: Bool) async {
        let sent = await uploader?.tick(force: force) ?? 0
        if sent > 0 { Diagnostics.log.info("sent \(sent) positions") }
        await refreshStatus()
        if let error = shareError { Diagnostics.log.notice("positions not sent: \(error, privacy: .public)") }
    }

    // MARK: Outbox (ios #5, #6, #7)

    func enqueue(_ item: OutboxItem) async {
        do { try await outbox.add(item) } catch { errorMessage = "Couldn't save on the phone: \(error.localizedDescription)" }
        await refreshStatus()
        kick()
    }

    /// Try to send everything that's waiting (network back, app opened, background task).
    func kick() {
        Task {
            await sendPositions(force: false)
            let before = Set(outboxItems.filter(\.isPending).map(\.id))
            let sent = await outbox.process(onWifi: network.isOnWifi)
            await refreshStatus()
            if sent > 0 { Diagnostics.log.info("outbox sent \(sent) item(s)") }
            for item in outboxItems where item.isPending {
                if let error = item.lastError { Diagnostics.log.notice("outbox waiting: \(error, privacy: .public)") }
            }
            notifyFinishedImports(previouslyPending: before)
        }
    }

    func sendAnyway(_ id: UUID) async {
        try? await outbox.sendAnyway(id)
        kick()
    }

    func retry(_ id: UUID) async {
        try? await outbox.retry(id)
        kick()
    }

    func discard(_ id: UUID) async {
        try? await outbox.remove(id)
        await refreshStatus()
    }

    func reviewURL(batchID: String) -> URL { server.appending(path: "imports/\(batchID)/review/") }
    var tripWebURL: URL? { trip.map { server.appending(path: "trips/\($0.id)/") } }

    private func notifyFinishedImports(previouslyPending: Set<UUID>) {
        for item in outboxItems where previouslyPending.contains(item.id) {
            guard case .photoImport = item.kind, case .done(let batch) = item.state else { continue }
            let content = UNMutableNotificationContent()
            content.title = "Photos ready to review"
            content.body = "\(item.files.count) photos are on the website, grouped into draft entries."
            content.userInfo = ["url": reviewURL(batchID: batch).absoluteString]
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: batch, content: content, trigger: nil))
        }
    }

    // MARK: Status (ios #8)

    func refreshStatus() async {
        outboxItems = await outbox.all
        guard let positions else { return }
        unsentPositions = await positions.unsentCount
        lastShared = await positions.lastUploadAt
        shareError = await positions.lastError
        if let calendar {
            todayPath = await positions.points(since: calendar.startOfDay(Date()))
        }
    }

    var todayKilometres: Double { PathPlacement.kilometres(todayPath) }

    // MARK: Settings

    private func saveSettings() {
        if let data = try? JSONEncoder().encode(settings) { defaults.set(data, forKey: "settings") }
    }

    private func applySettings() {
        if recorder.isRecording { recorder.update(interval: settings.recordingInterval) }
        let settings = settings
        Task {
            await uploader?.setUploadInterval(settings.uploadInterval)
            await outbox.update(settings: settings)
        }
    }
}
