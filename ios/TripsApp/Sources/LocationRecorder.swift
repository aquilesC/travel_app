import CoreLocation
import Foundation
import Observation
import TripsKit

/// Records position while a trip is on (ios #3). CoreLocation runs continuously at an accuracy
/// that fits the chosen interval; PositionSampler keeps at most one point per interval; every
/// kept point is saved to disk at once and the uploader gets a chance to send (ios #4).
///
/// iOS doesn't run apps on a timer in the background: points arrive when location updates do.
/// The background activity session keeps updates coming with "When In Use" permission and shows
/// the blue location pill while recording.
@MainActor @Observable
final class LocationRecorder: NSObject {
    private(set) var isRecording = false
    private(set) var authorization: CLAuthorizationStatus = .notDetermined
    private(set) var lastFix: LocationFix?

    /// Called with the points to keep (already sampled).
    var onPoints: (@MainActor ([LocationFix]) -> Void)?

    private let manager = CLLocationManager()
    private var sampler = PositionSampler(interval: 60)
    private var backgroundSession: CLBackgroundActivitySession?

    override init() {
        super.init()
        manager.delegate = self
        manager.activityType = .otherNavigation
        manager.pausesLocationUpdatesAutomatically = false
        authorization = manager.authorizationStatus
    }

    var permissionDenied: Bool { authorization == .denied || authorization == .restricted }

    func requestPermission() { manager.requestWhenInUseAuthorization() }
    func requestAlways() { manager.requestAlwaysAuthorization() }

    func start(interval: TimeInterval, lastKept: LocationFix?) {
        sampler = PositionSampler(interval: interval, lastKept: lastKept)
        configure(interval: interval)
        if authorization == .notDetermined { requestPermission() }
        backgroundSession = CLBackgroundActivitySession()
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        manager.startUpdatingLocation()
        isRecording = true
    }

    /// Change the interval without stopping (ios #8 AC2).
    func update(interval: TimeInterval) {
        let points = sampler.flush()
        if !points.isEmpty { onPoints?(points) }
        sampler.interval = interval
        configure(interval: interval)
    }

    func stop() {
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
        backgroundSession?.invalidate()
        backgroundSession = nil
        let points = sampler.flush()
        if !points.isEmpty { onPoints?(points) }
        isRecording = false
    }

    /// Coarser accuracy and fewer updates for longer intervals: the main battery lever.
    private func configure(interval: TimeInterval) {
        switch interval {
        case ..<60:
            manager.desiredAccuracy = kCLLocationAccuracyBest
            manager.distanceFilter = 10
        case ..<300:
            manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
            manager.distanceFilter = 25
        case ..<900:
            manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
            manager.distanceFilter = 100
        default:
            manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
            manager.distanceFilter = 250
        }
    }

    fileprivate func handle(_ locations: [CLLocation]) {
        var kept: [LocationFix] = []
        for location in locations where location.horizontalAccuracy >= 0 {
            let fix = LocationFix(
                recordedAt: location.timestamp, latitude: location.coordinate.latitude,
                longitude: location.coordinate.longitude, accuracy: location.horizontalAccuracy,
                altitude: location.verticalAccuracy >= 0 ? location.altitude : nil,
                speed: location.speed >= 0 ? location.speed : nil)
            lastFix = fix
            kept += sampler.add(fix)
        }
        if !kept.isEmpty { onPoints?(kept) }
    }
}

extension LocationRecorder: CLLocationManagerDelegate {
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        Task { @MainActor in self.handle(locations) }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in self.authorization = status }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // Temporary failures (no signal in a tunnel) are normal; updates resume by themselves.
    }
}
