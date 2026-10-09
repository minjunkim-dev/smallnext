import Foundation
import FirebaseCore
import FirebaseCrashlytics

enum CrashReporting {
    @MainActor
    @discardableResult
    static func start(enabled: Bool = FeatureFlags.iosCrashReporting,
                      info: [String: Any] = Bundle.main.infoDictionary ?? [:]) -> Bool {
        guard enabled, let options = FirebaseClientConfiguration.options(info: info) else { return false }
        if FirebaseApp.app() == nil { FirebaseApp.configure(options: options) }
        guard let app = FirebaseApp.app(), app.options.googleAppID == options.googleAppID,
              app.options.projectID == options.projectID, app.options.bundleID == options.bundleID,
              app.options.apiKey == options.apiKey else { return false }
        app.isDataCollectionDefaultEnabled = false
        let reporter = Crashlytics.crashlytics()
        // A true override survives later OFF launches. Send only for this ON launch.
        reporter.setCrashlyticsCollectionEnabled(false)
        reporter.sendUnsentReports()
        #if DEBUG
        if UserDefaults.standard.bool(forKey: "crashlytics_test_crash") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                fatalError("Smallnext Crashlytics synthetic validation")
            }
        }
        #endif
        return true
    }
}
