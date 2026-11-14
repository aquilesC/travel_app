import MapKit
import SwiftUI
import TripsKit

/// The home screen (ios #8): the current trip, recording, sharing, and what's waiting to be sent.
struct TripView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var composing = false
    @State private var pickingPhotos = false

    var body: some View {
        List {
            if let trip = model.trip {
                Section {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(trip.title).font(.title2.bold())
                        if let day = model.calendar?.dayNumber(of: Date()) {
                            Text("Day \(day.day) of \(day.of)").foregroundStyle(.secondary)
                        } else {
                            Text("\(trip.startDate) – \(trip.endDate)").foregroundStyle(.secondary)
                        }
                    }
                }
                RecordingSection()
                if !model.todayPath.isEmpty {
                    Section("Today") {
                        TodayMap(path: model.todayPath).frame(height: 220).listRowInsets(EdgeInsets())
                    }
                }
                Section {
                    Button { composing = true } label: { Label("Post", systemImage: "square.and.pencil") }
                    Button { pickingPhotos = true } label: { Label("Pick photos", systemImage: "photo.on.rectangle") }
                    if let url = model.tripWebURL {
                        Button { openURL(url) } label: { Label("Open the trip on the web", systemImage: "safari") }
                    }
                }
                OutboxSection()
            } else {
                ContentUnavailableView("No trips yet", systemImage: "map",
                                       description: Text("Create a trip on the website, then pull to refresh."))
            }
            if let error = model.errorMessage {
                Section { Text(error).foregroundStyle(.red) }
            }
        }
        .refreshable {
            try? await model.refreshTrips()
            model.kick()
        }
        .navigationTitle("Trips")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) { TripMenu() }
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink { SettingsView() } label: { Image(systemName: "gearshape") }
            }
        }
        .sheet(isPresented: $composing) { ComposeView() }
        .sheet(isPresented: $pickingPhotos) { PhotoPickerView() }
    }
}

struct TripMenu: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Menu {
            ForEach(model.trips, id: \.id) { trip in
                Button {
                    Task { await model.select(tripID: trip.id) }
                } label: {
                    if trip.id == model.trip?.id { Label(trip.title, systemImage: "checkmark") } else { Text(trip.title) }
                }
            }
        } label: { Image(systemName: "list.bullet") }
    }
}

struct RecordingSection: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Section {
            Toggle(isOn: Binding(get: { model.recorder.isRecording },
                                 set: { $0 ? model.startRecording() : model.stopRecording() })) {
                VStack(alignment: .leading) {
                    Text("Record my path")
                    Text("One point every \(Self.describe(model.settings.recordingInterval))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if model.recorder.permissionDenied {
                Label("Location is off for Trips. Turn it on in Settings › Trips › Location.",
                      systemImage: "location.slash").foregroundStyle(.orange)
                Button("Open Settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                }
            }
            LabeledContent("Today", value: String(format: "%.1f km · %d points", model.todayKilometres, model.todayPath.count))
            LabeledContent("Shared") {
                if let last = model.lastShared {
                    Text(last, format: .relative(presentation: .named))
                } else {
                    Text("not yet")
                }
            }
            if model.unsentPositions > 0 {
                LabeledContent("Waiting to send", value: "\(model.unsentPositions) points")
            }
            if let error = model.shareError { Text(error).font(.caption).foregroundStyle(.orange) }
            Button("Send now") { Task { await model.sendPositions(force: true) } }
                .disabled(model.unsentPositions == 0)
            if let trip = model.trip {
                Text(Self.audience(trip.liveShare, delay: trip.liveDelayMinutes))
                    .font(.caption).foregroundStyle(.secondary)
            }
        } header: {
            Text("Location")
        }
    }

    static func describe(_ seconds: TimeInterval) -> String {
        seconds < 60 ? "\(Int(seconds)) s" : "\(Int(seconds / 60)) min"
    }

    static func audience(_ share: String, delay: Int) -> String {
        switch share {
        case "off": return "Live location is off for this trip (change it on the website)."
        case "link": return "Members see where you are; the share link shows it \(delay) min later, rounded."
        default: return "Only trip members see where you are."
        }
    }
}

struct TodayMap: View {
    let path: [LocationFix]

    var body: some View {
        Map(initialPosition: .automatic, interactionModes: [.pan, .zoom]) {
            MapPolyline(coordinates: path.map { CLLocationCoordinate2D(latitude: $0.latitude, longitude: $0.longitude) })
                .stroke(.teal, lineWidth: 4)
            if let last = path.last {
                Marker("Now", coordinate: CLLocationCoordinate2D(latitude: last.latitude, longitude: last.longitude))
            }
        }
    }
}

struct OutboxSection: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let pending = model.outboxItems.filter(\.isPending).count
        let failed = model.outboxItems.filter { if case .failed = $0.state { return true }; return false }.count
        if !model.outboxItems.isEmpty {
            Section {
                NavigationLink { OutboxView() } label: {
                    LabeledContent("Outbox", value: pending + failed == 0 ? "All sent" : "\(pending) waiting"
                                   + (failed > 0 ? ", \(failed) need you" : ""))
                }
                if pending > 0 && !model.network.isOnline {
                    Text("Offline: everything is saved on the phone and goes when there's signal.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }
}
