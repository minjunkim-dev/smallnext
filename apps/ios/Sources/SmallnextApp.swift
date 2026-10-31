import SwiftUI
import OSLog
import SmallnextCore

@main
struct SmallnextApp: App {
    init() { CrashReporting.start() }

    @State private var database: AppDatabase?
    @State private var flow: ProgressFlow?
    @State private var storageFailed = false
    @State private var captcha = TurnstileChallenge.shared
    @AppStorage(AIConsent.key) private var aiConsent = false
    private let logger = Logger(subsystem: "dev.smallnext.app", category: "storage")

    var body: some Scene {
        WindowGroup {
            Group {
                if let flow {
                    if FeatureFlags.userServerAI && !aiConsent {
                        AIConsentView(agree: { aiConsent = true },
                                      deleteLocalData: { try flow.deleteAllGoals(confirmed: true) },
                                      hasLocalData: !flow.goals.isEmpty || flow.goalInput != GoalInput())
                    } else {
                        CoreFlowView(flow: flow)
                    }
                } else {
                    ContentView(storageFailed: storageFailed)
                }
            }
            .sheet(item: Binding(get: { captcha.request }, set: { value in
                if value == nil, let request = captcha.request {
                    captcha.finish(id: request.id, result: .failure(CancellationError()))
                }
            })) { request in
                TurnstileSheet(request: request, challenge: captcha)
            }
            .task {
                guard database == nil, !storageFailed else { return }
                do {
                    let opened = try AppDatabase.openDefault()
                    database = opened
                    if FeatureFlags.iosCoreFlow {
                        flow = try ProgressFlow(database: opened, provider: Self.suggestionProvider)
                    }
                } catch {
                    logger.error("Storage initialization failed: \(String(describing: type(of: error)), privacy: .public)")
                    storageFailed = true
                }
            }
        }
    }

    private static var suggestionProvider: any ActionSuggestionProvider {
        if FeatureFlags.userServerAI {
            return UserServerAI.configured() ?? UnavailableSuggestionProvider()
        }
        #if DEBUG
        return DevelopmentAI.configured() ?? DebugActionSuggestionProvider()
        #else
        return UnavailableSuggestionProvider()
        #endif
    }
}
