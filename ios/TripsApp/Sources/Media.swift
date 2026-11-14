import AVFoundation
import CoreTransferable
import Foundation
import Observation
import Photos
import SwiftUI
import TripsKit
import UniformTypeIdentifiers

/// A photo or video chosen with PhotosPicker, received as the original file (HEIC/HEVC as is).
struct PickedFile: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .item) { received in
            // The received file is deleted when this returns: copy it somewhere we own.
            let target = FileManager.default.temporaryDirectory
                .appending(path: "\(UUID().uuidString)-\(received.file.lastPathComponent)")
            try FileManager.default.copyItem(at: received.file, to: target)
            return PickedFile(url: target)
        }
    }
}

enum OutboxFiles {
    /// Move a file into the outbox directory and describe it for an OutboxItem.
    static func adopt(_ url: URL, filename: String? = nil, into outbox: Outbox) async throws -> OutboxFile {
        let name = filename ?? url.lastPathComponent
        let relative = "files/\(UUID().uuidString)-\(name)"
        let target = await outbox.fileURL(for: relative)
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.moveItem(at: url, to: target)
        let size = (try FileManager.default.attributesOfItem(atPath: target.path)[.size] as? Int) ?? 0
        return OutboxFile(relativePath: relative, filename: name, size: size)
    }
}

/// Voice notes (ios #6): AAC in .m4a, at most 10 minutes.
@MainActor @Observable
final class VoiceRecorder {
    private(set) var isRecording = false
    private(set) var duration: TimeInterval = 0
    private(set) var recordedURL: URL?
    private var recorder: AVAudioRecorder?
    private var player: AVAudioPlayer?
    private var timer: Timer?
    static let maxDuration: TimeInterval = 600

    func start() async -> Bool {
        guard await AVAudioApplication.requestRecordPermission() else { return false }
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try session.setActive(true)
            let url = FileManager.default.temporaryDirectory.appending(path: "voice-\(UUID().uuidString).m4a")
            let recorder = try AVAudioRecorder(url: url, settings: [
                AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 44_100, AVNumberOfChannelsKey: 1,
                AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
            ])
            recorder.record(forDuration: Self.maxDuration)
            self.recorder = recorder
            recordedURL = url
            isRecording = true
            duration = 0
            timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    guard let self, let recorder = self.recorder else { return }
                    self.duration = recorder.currentTime
                    if !recorder.isRecording { self.stop() }
                }
            }
            return true
        } catch {
            return false
        }
    }

    func stop() {
        recorder?.stop()
        timer?.invalidate()
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    func play() {
        guard let url = recordedURL else { return }
        player = try? AVAudioPlayer(contentsOf: url)
        player?.play()
    }

    func discard() {
        stop()
        if let url = recordedURL { try? FileManager.default.removeItem(at: url) }
        recordedURL = nil
        duration = 0
    }

    /// Hand the recording over (e.g. to the outbox); the recorder forgets it.
    func take() -> URL? {
        defer { recordedURL = nil; duration = 0 }
        return recordedURL
    }
}

/// The photo library for the picker (ios #7): find assets in a trip, thumbnails, originals.
@MainActor
final class PhotoLibrary {
    let images = PHCachingImageManager()

    static var status: PHAuthorizationStatus { PHPhotoLibrary.authorizationStatus(for: .readWrite) }

    static func requestAccess() async -> PHAuthorizationStatus {
        await PHPhotoLibrary.requestAuthorization(for: .readWrite)
    }

    /// Photos and videos taken between `from` and `to`, newest last.
    func assets(from: Date, to: Date) -> [PHAsset] {
        let options = PHFetchOptions()
        options.predicate = NSPredicate(format: "creationDate >= %@ AND creationDate < %@ AND (mediaType == %d OR mediaType == %d)",
                                        from as NSDate, to as NSDate,
                                        PHAssetMediaType.image.rawValue, PHAssetMediaType.video.rawValue)
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: true)]
        var result: [PHAsset] = []
        PHAsset.fetchAssets(with: options).enumerateObjects { asset, _, _ in result.append(asset) }
        return result
    }

    static func candidate(_ asset: PHAsset) -> PhotoCandidate {
        PhotoCandidate(id: asset.localIdentifier, takenAt: asset.creationDate,
                       latitude: asset.location?.coordinate.latitude, longitude: asset.location?.coordinate.longitude)
    }

    func thumbnail(for asset: PHAsset, side: CGFloat) async -> UIImage? {
        await withCheckedContinuation { continuation in
            let options = PHImageRequestOptions()
            options.deliveryMode = .highQualityFormat
            options.isNetworkAccessAllowed = true
            options.resizeMode = .fast
            images.requestImage(for: asset, targetSize: CGSize(width: side, height: side), contentMode: .aspectFill,
                                options: options) { image, _ in continuation.resume(returning: image) }
        }
    }

    /// The original file (downloaded from iCloud if needed) written to a temporary file.
    static func exportOriginal(_ asset: PHAsset, allowNetwork: Bool) async throws -> (url: URL, filename: String) {
        let resources = PHAssetResource.assetResources(for: asset)
        let preferred: [PHAssetResourceType] = asset.mediaType == .video
            ? [.fullSizeVideo, .video] : [.fullSizePhoto, .photo]
        guard let resource = preferred.lazy.compactMap({ type in resources.first { $0.type == type } }).first
                ?? resources.first else {
            throw TripsError.invalidFile("This item has no file.")
        }
        let target = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString)-\(resource.originalFilename)")
        let options = PHAssetResourceRequestOptions()
        options.isNetworkAccessAllowed = allowNetwork
        try await PHAssetResourceManager.default().writeData(for: resource, toFile: target, options: options)
        return (target, resource.originalFilename)
    }
}
