import MapKit
import Photos
import PhotosUI
import SwiftUI
import TripsKit

/// Find the right photos quickly and upload only those (ios #7): pick a trip day, narrow the
/// time window, pan the map to an area. Originals go into an import; the website groups them
/// into draft entries for review.
struct PhotoPickerView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var access = PhotoLibrary.status
    @State private var library = PhotoLibrary()
    @State private var assets: [String: PHAsset] = [:]
    @State private var candidates: [PhotoCandidate] = []
    @State private var filter = PhotoFilter()
    @State private var useMapArea = false
    @State private var visibleRegion: MapRegion?
    @State private var selected: Set<String> = []
    @State private var uploading = false
    @State private var progressText = ""
    @State private var fallbackItems: [PhotosPickerItem] = []
    @State private var path: [LocationFix] = []

    private var uploadedKey: String { "uploaded-\(model.trip?.id ?? 0)" }
    private var uploaded: Set<String> { Set(UserDefaults.standard.stringArray(forKey: uploadedKey) ?? []) }

    private var shown: [PhotoCandidate] {
        var f = filter
        f.region = useMapArea ? visibleRegion : nil
        return f.apply(candidates)
    }

    var body: some View {
        NavigationStack {
            Group {
                switch access {
                case .authorized: picker
                case .notDetermined: ProgressView().task { access = await PhotoLibrary.requestAccess(); await load() }
                default: limitedAccess
                }
            }
            .navigationTitle("Pick photos")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
            }
        }
        .task { if access == .authorized { await load() } }
    }

    // MARK: Full access

    private var picker: some View {
        VStack(spacing: 0) {
            dayChips
            timeWindow
            mapArea
            grid
            uploadBar
        }
    }

    private var dayChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack {
                ForEach(Array((model.calendar?.days ?? []).enumerated()), id: \.offset) { index, day in
                    let isOn = filter.day == day
                    Button("Day \(index + 1)") { filter.day = isOn ? nil : day }
                        .buttonStyle(.bordered)
                        .tint(isOn ? .teal : .secondary)
                }
            }.padding(.horizontal)
        }.padding(.vertical, 6)
    }

    private var timeWindow: some View {
        HStack {
            Picker("From", selection: $filter.fromMinute) {
                ForEach(0..<24, id: \.self) { Text(String(format: "%02d:00", $0)).tag($0 * 60) }
            }
            Text("–")
            Picker("To", selection: $filter.toMinute) {
                ForEach(1...24, id: \.self) { Text(String(format: "%02d:00", $0 % 24 == 0 ? 24 : $0)).tag($0 * 60) }
            }
            Spacer()
            Toggle("Map area", isOn: $useMapArea).fixedSize()
        }
        .font(.subheadline)
        .padding(.horizontal)
        .disabled(filter.day == nil)
        .opacity(filter.day == nil ? 0.5 : 1)
    }

    private var mapArea: some View {
        Map(initialPosition: .automatic) {
            MapPolyline(coordinates: path.map { CLLocationCoordinate2D(latitude: $0.latitude, longitude: $0.longitude) })
                .stroke(.teal.opacity(0.7), lineWidth: 3)
            ForEach(filter.apply(candidates).filter(\.hasLocation)) { photo in
                Annotation("", coordinate: CLLocationCoordinate2D(latitude: photo.latitude!, longitude: photo.longitude!)) {
                    Circle().fill(photo.placedFromPath ? .orange : .teal).frame(width: 8, height: 8)
                }
            }
        }
        .frame(height: 200)
        .onMapCameraChange(frequency: .onEnd) { context in
            let r = context.region
            visibleRegion = MapRegion(minLatitude: r.center.latitude - r.span.latitudeDelta / 2,
                                      maxLatitude: r.center.latitude + r.span.latitudeDelta / 2,
                                      minLongitude: r.center.longitude - r.span.longitudeDelta / 2,
                                      maxLongitude: r.center.longitude + r.span.longitudeDelta / 2)
        }
    }

    private var grid: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: 2)], spacing: 2) {
                ForEach(shown) { photo in
                    if let asset = assets[photo.id] {
                        Thumbnail(asset: asset, library: library, selected: selected.contains(photo.id),
                                  uploaded: uploaded.contains(photo.id), placed: photo.placedFromPath)
                            .onTapGesture { toggle(photo.id) }
                    }
                }
            }
        }
        .overlay {
            if shown.isEmpty { ContentUnavailableView("No photos here", systemImage: "photo",
                                                      description: Text("Try another day, time or area.")) }
        }
    }

    private var uploadBar: some View {
        let bytes = selected.compactMap { assets[$0] }.count
        return VStack(spacing: 6) {
            if uploading { Text(progressText).font(.caption) }
            HStack {
                Button("Select all shown") { selected.formUnion(shown.map(\.id).filter { !uploaded.contains($0) }) }
                    .disabled(shown.isEmpty)
                Spacer()
                Button { Task { await upload() } } label: {
                    Text(uploading ? "Preparing…" : "Upload \(bytes)")
                }
                .buttonStyle(.borderedProminent)
                .disabled(selected.isEmpty || uploading)
            }
        }
        .padding()
        .background(.bar)
    }

    private func toggle(_ id: String) {
        if selected.contains(id) { selected.remove(id) } else { selected.insert(id) }
    }

    private func load() async {
        guard let calendar = model.calendar else { return }
        let found = library.assets(from: calendar.start, to: calendar.end)
        assets = Dictionary(uniqueKeysWithValues: found.map { ($0.localIdentifier, $0) })
        path = await model.positions?.points(since: calendar.start) ?? []
        candidates = PathPlacement.place(found.map(PhotoLibrary.candidate), on: path)
        let today = calendar.startOfDay(Date())
        if calendar.days.contains(today) { filter.day = today }
    }

    private func upload() async {
        guard let trip = model.trip else { return }
        uploading = true
        defer { uploading = false }
        var files: [OutboxFile] = []
        let picked = selected.compactMap { assets[$0] }
        for (index, asset) in picked.enumerated() {
            progressText = "Preparing \(index + 1) of \(picked.count)…"
            do {
                // iCloud-only originals download here (on cellular only if large files may use it).
                let allowNetwork = model.network.isOnWifi || !model.settings.largeFilesOnWifiOnly
                let (url, name) = try await PhotoLibrary.exportOriginal(asset, allowNetwork: allowNetwork)
                files.append(try await OutboxFiles.adopt(url, filename: name, into: model.outbox))
            } catch {
                model.errorMessage = "Skipped a photo that's only in iCloud; try again on wifi."
            }
        }
        guard !files.isEmpty else { return }
        await model.enqueue(OutboxItem(tripID: trip.id, kind: .photoImport(batchID: nil, makePublic: true), files: files))
        UserDefaults.standard.set(Array(uploaded.union(selected)), forKey: uploadedKey)
        selected = []
        dismiss()
    }

    // MARK: Limited or no access

    private var limitedAccess: some View {
        VStack(spacing: 16) {
            ContentUnavailableView("Full photo access needed for filters", systemImage: "photo.on.rectangle.angled",
                                   description: Text("To show photos by day, time and place, Trips needs to read your library. "
                                                     + "Only the photos you pick are uploaded. You can still pick photos one by one."))
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
            }
            PhotosPicker(selection: $fallbackItems, maxSelectionCount: 50, matching: .any(of: [.images, .videos]),
                         preferredItemEncoding: .current) {
                Label("Pick photos one by one", systemImage: "photo.badge.plus")
            }
            .buttonStyle(.borderedProminent)
            .onChange(of: fallbackItems) { _, items in Task { await uploadFallback(items) } }
            if uploading { ProgressView(progressText) }
        }
        .padding()
    }

    private func uploadFallback(_ items: [PhotosPickerItem]) async {
        guard let trip = model.trip, !items.isEmpty else { return }
        uploading = true
        defer { uploading = false }
        var files: [OutboxFile] = []
        for (index, item) in items.enumerated() {
            progressText = "Preparing \(index + 1) of \(items.count)…"
            if let picked = try? await item.loadTransferable(type: PickedFile.self),
               let file = try? await OutboxFiles.adopt(picked.url, into: model.outbox) {
                files.append(file)
            }
        }
        await model.enqueue(OutboxItem(tripID: trip.id, kind: .photoImport(batchID: nil, makePublic: true), files: files))
        dismiss()
    }
}

struct Thumbnail: View {
    let asset: PHAsset
    let library: PhotoLibrary
    let selected: Bool
    let uploaded: Bool
    let placed: Bool
    @State private var image: UIImage?

    var body: some View {
        Color.secondary.opacity(0.15)
            .aspectRatio(1, contentMode: .fit)
            .overlay {
                if let image { Image(uiImage: image).resizable().scaledToFill() }
            }
            .clipped()
            .overlay(alignment: .topTrailing) {
                if selected {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.white, .teal).padding(4)
                } else if uploaded {
                    Image(systemName: "icloud.and.arrow.up").foregroundStyle(.white).shadow(radius: 2).padding(4)
                }
            }
            .overlay(alignment: .bottomLeading) {
                HStack(spacing: 2) {
                    if asset.mediaType == .video { Image(systemName: "video.fill") }
                    if placed { Image(systemName: "location.fill.viewfinder") }
                }
                .font(.caption2).foregroundStyle(.white).shadow(radius: 2).padding(4)
            }
            .opacity(uploaded && !selected ? 0.6 : 1)
            .task(id: asset.localIdentifier) { image = await library.thumbnail(for: asset, side: 220) }
    }
}
