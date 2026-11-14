import CoreLocation
import PhotosUI
import SwiftUI
import TripsKit

/// Posting from the phone (ios #6): text, photos and videos, a voice note. It goes into the
/// outbox at once and is sent when there's signal.
struct ComposeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var placeName = ""
    @State private var isPublic = true
    @State private var newChapter = ""
    @State private var startChapter = false
    @State private var pickerItems: [PhotosPickerItem] = []
    @State private var attachments: [PickedFile] = []
    @State private var loadingMedia = false
    @State private var voice = VoiceRecorder()
    @State private var voiceURL: URL?
    @State private var saving = false
    @State private var micDenied = false
    private let geocoder = CLGeocoder()

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("What happened?", text: $text, axis: .vertical).lineLimit(4...12)
                    TextField("Place", text: $placeName)
                } footer: { Text("Markdown works: **bold**, *italic*, lists.") }

                Section("Photos and videos") {
                    PhotosPicker(selection: $pickerItems, maxSelectionCount: 20, matching: .any(of: [.images, .videos]),
                                 preferredItemEncoding: .current, photoLibrary: .shared()) {
                        Label(attachments.isEmpty ? "Add from library" : "\(attachments.count) selected",
                              systemImage: "photo.badge.plus")
                    }
                    if loadingMedia { ProgressView("Preparing…") }
                }
                .onChange(of: pickerItems) { _, items in Task { await load(items) } }

                Section("Voice note") {
                    if voice.isRecording {
                        HStack {
                            Label(Duration.seconds(voice.duration).formatted(.time(pattern: .minuteSecond)),
                                  systemImage: "record.circle").foregroundStyle(.red)
                            Spacer()
                            Button("Stop") { voice.stop(); voiceURL = voice.recordedURL }
                        }
                    } else if voiceURL != nil {
                        HStack {
                            Button { voice.play() } label: { Label("Play", systemImage: "play.fill") }
                            Spacer()
                            Button("Delete", role: .destructive) { voice.discard(); voiceURL = nil }
                        }.buttonStyle(.borderless)
                    } else {
                        Button { Task { micDenied = !(await voice.start()) } } label: {
                            Label("Record (up to 10 min)", systemImage: "mic")
                        }
                        if micDenied { Text("Allow the microphone for Trips in Settings.").font(.caption) }
                    }
                }

                Section {
                    Toggle("Show on the share link", isOn: $isPublic)
                    Toggle("Start a new chapter", isOn: $startChapter)
                    if startChapter { TextField("Chapter title", text: $newChapter) }
                } footer: {
                    if let current = model.trip?.chapters.first(where: { $0.id == model.trip?.currentChapterId }) {
                        Text("Goes into “\(current.title)” unless you start a new chapter.")
                    }
                }
            }
            .navigationTitle("Post")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { cleanUp(); dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") { Task { await send() } }
                        .disabled(saving || loadingMedia || voice.isRecording || isEmpty)
                }
            }
            .task { await fillPlace() }
        }
    }

    private var isEmpty: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && attachments.isEmpty && voiceURL == nil
    }

    private func load(_ items: [PhotosPickerItem]) async {
        loadingMedia = true
        defer { loadingMedia = false }
        attachments.forEach { try? FileManager.default.removeItem(at: $0.url) }
        attachments = []
        for item in items {
            if let file = try? await item.loadTransferable(type: PickedFile.self) { attachments.append(file) }
        }
    }

    /// Prefill the place from where the phone is now (editable).
    private func fillPlace() async {
        guard placeName.isEmpty, let fix = model.recorder.lastFix ?? model.todayPath.last else { return }
        let location = CLLocation(latitude: fix.latitude, longitude: fix.longitude)
        if let mark = try? await geocoder.reverseGeocodeLocation(location).first {
            placeName = [mark.name, mark.locality].compactMap { $0 }.uniqued().joined(separator: ", ")
        }
    }

    private func send() async {
        guard let trip = model.trip else { return }
        saving = true
        defer { saving = false }
        let fix = model.recorder.lastFix ?? model.todayPath.last
        let fresh = fix.map { Date().timeIntervalSince($0.recordedAt) < 30 * 60 } ?? false
        let draft = PostDraft(occurredAt: Date(), body: text, placeName: placeName,
                              latitude: fresh ? fix?.latitude : nil, longitude: fresh ? fix?.longitude : nil,
                              isPublic: isPublic,
                              newChapterTitle: startChapter && !newChapter.isEmpty ? newChapter : nil)
        do {
            var files: [OutboxFile] = []
            if let url = voice.take() ?? voiceURL { files.append(try await OutboxFiles.adopt(url, into: model.outbox)) }
            for file in attachments { files.append(try await OutboxFiles.adopt(file.url, into: model.outbox)) }
            await model.enqueue(OutboxItem(tripID: trip.id, kind: .post(draft), files: files))
            dismiss()
        } catch {
            model.errorMessage = "Couldn't save the post on the phone: \(error.localizedDescription)"
        }
    }

    private func cleanUp() {
        voice.discard()
        attachments.forEach { try? FileManager.default.removeItem(at: $0.url) }
    }
}

extension Array where Element: Hashable {
    func uniqued() -> [Element] {
        var seen = Set<Element>()
        return filter { seen.insert($0).inserted }
    }
}
