import SwiftUI
import OSLog

@main
struct SmallnextApp: App {
    @State private var database: AppDatabase?
    @State private var storageFailed = false
    private let logger = Logger(subsystem: "dev.smallnext.app", category: "storage")

    var body: some Scene {
        WindowGroup {
            ContentView(storageFailed: storageFailed)
                .task {
                    guard database == nil, !storageFailed else { return }
                    do {
                        database = try AppDatabase.openDefault()
                    } catch {
                        logger.error("Storage initialization failed: \(error.localizedDescription, privacy: .public)")
                        storageFailed = true
                    }
                }
        }
    }
}
