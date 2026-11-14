import OSLog
import SwiftUI
import TripsKit

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var confirmLogout = false
    @State private var diagnostics: URL?
    @AppStorage("serverURL") private var serverOverride = ""

    var body: some View {
        @Bindable var model = model
        Form {
            Section {
                Picker("Record a point every", selection: $model.settings.recordingInterval) {
                    ForEach(AppSettings.recordingChoices, id: \.self) { Text(RecordingSection.describe($0)).tag($0) }
                }
                Text(AppSettings.batteryHint(for: model.settings.recordingInterval)).font(.caption).foregroundStyle(.secondary)
                Picker("Share my position every", selection: $model.settings.uploadInterval) {
                    ForEach(AppSettings.uploadChoices, id: \.self) { Text(RecordingSection.describe($0)).tag($0) }
                }
                Toggle("Start recording when a trip begins", isOn: $model.settings.autoStartRecording)
                    .onChange(of: model.settings.autoStartRecording) { _, on in if on { model.recorder.requestAlways() } }
            } header: { Text("Location") } footer: {
                Text("Positions are tiny and go over mobile data. Your family sees them as set on the trip's page.")
            }

            Section("Photos and videos") {
                Toggle("Large files only on wifi", isOn: $model.settings.largeFilesOnWifiOnly)
                Text("Files over \(ByteCountFormatter.string(fromByteCount: Int64(model.settings.largeFileBytes), countStyle: .file)) wait for wifi; you can send one anyway from the Outbox.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section("Account") {
                if let me = model.me { LabeledContent("Logged in as", value: me.name) }
                Button("Log out", role: .destructive) { confirmLogout = true }
            }

            Section("About") {
                LabeledContent("App", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?")
                LabeledContent("Server", value: model.server.host() ?? "")
                if abs(model.clockSkew) > 120 {
                    Text("This phone's clock is \(Int(abs(model.clockSkew) / 60)) min off. Times on entries may be wrong.")
                        .foregroundStyle(.orange)
                }
                Button("Export diagnostics (last 24 h)") { diagnostics = Diagnostics.export() }
                if let diagnostics {
                    ShareLink(item: diagnostics) { Label("Share diagnostics", systemImage: "square.and.arrow.up") }
                }
            }

            #if DEBUG
            Section("Developer") {
                TextField("Server URL (restart the app)", text: $serverOverride)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
            }
            #endif
        }
        .navigationTitle("Settings")
        .confirmationDialog("Log out?", isPresented: $confirmLogout) {
            Button("Log out", role: .destructive) { Task { await model.logout() } }
        } message: {
            Text(model.hasUnsentWork
                 ? "Some posts or positions haven't been sent yet. They stay on the phone and go after you log in again."
                 : "You can log in again any time.")
        }
    }
}

enum Diagnostics {
    static let log = Logger(subsystem: "me.aquiles.trips", category: "app")

    /// The app's own log lines from the last 24 hours, as a text file to share.
    static func export() -> URL? {
        guard let store = try? OSLogStore(scope: .currentProcessIdentifier) else { return nil }
        let since = store.position(date: Date().addingTimeInterval(-86_400))
        let lines = (try? store.getEntries(at: since))?
            .compactMap { $0 as? OSLogEntryLog }
            .filter { $0.subsystem == "me.aquiles.trips" }
            .map { "\($0.date.formatted(.iso8601)) [\($0.category)] \($0.composedMessage)" } ?? []
        let url = FileManager.default.temporaryDirectory.appending(path: "trips-diagnostics.txt")
        try? lines.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
        return url
    }
}
