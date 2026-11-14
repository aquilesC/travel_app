import BackgroundTasks
import SwiftUI
import UIKit
import UserNotifications

@main
struct TripsApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .onAppear { AppDelegate.model = model }
        }
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active: model.kick()
            case .background: AppDelegate.scheduleSend()
            default: break
            }
        }
    }
}

/// Background work: iOS wakes the app now and then to send what's waiting (ios #4, #5), and
/// tapping a "Photos ready to review" notification opens the review page.
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    nonisolated static let sendTask = "me.aquiles.trips.send"
    @MainActor static weak var model: AppModel?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.sendTask, using: nil) { task in
            Self.scheduleSend()
            nonisolated(unsafe) let task = task  // BGTask isn't Sendable; only completed once, below
            let work = Task { @MainActor in
                Self.model?.kick()
                try? await Task.sleep(for: .seconds(25))  // kick() runs async; give it time
                task.setTaskCompleted(success: !Task.isCancelled)
            }
            task.expirationHandler = { work.cancel() }
        }
        return true
    }

    nonisolated static func scheduleSend() {
        let request = BGProcessingTaskRequest(identifier: sendTask)
        request.requiresNetworkConnectivity = true
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        if let text = response.notification.request.content.userInfo["url"] as? String, let url = URL(string: text) {
            await MainActor.run { UIApplication.shared.open(url) }
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification)
        async -> UNNotificationPresentationOptions { [.banner, .sound] }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        switch model.phase {
        case .loggedOut: LoginView()
        case .loading: ProgressView("Loading your trips…")
        case .ready: NavigationStack { TripView() }
        }
    }
}
