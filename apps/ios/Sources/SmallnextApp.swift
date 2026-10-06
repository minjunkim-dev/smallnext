import SwiftUI
import OSLog

@main
struct SmallnextApp: App {
    @State private var database: AppDatabase?
    @State private var flow: ProgressFlow?
    @State private var storageFailed = false
    private let logger = Logger(subsystem: "dev.smallnext.app", category: "storage")

    var body: some Scene {
        WindowGroup {
            Group {
                if let flow {
                    CoreFlowView(flow: flow)
                } else {
                    ContentView(storageFailed: storageFailed)
                }
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
                    logger.error("Storage initialization failed: \(error.localizedDescription, privacy: .public)")
                    storageFailed = true
                }
            }
        }
    }

    private static var suggestionProvider: any ActionSuggestionProvider {
        #if DEBUG
        DebugActionSuggestionProvider()
        #else
        UnavailableSuggestionProvider()
        #endif
    }
}
