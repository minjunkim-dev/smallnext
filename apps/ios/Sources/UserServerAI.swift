import Foundation
import FirebaseCore
@preconcurrency import FirebaseAuth

/// 사용자 서버의 주소와 Firebase 익명 신원을 연결한다.
enum UserServerAI {
    @MainActor
    static func configured(bundle: Bundle = .main, defaults: UserDefaults = .standard) -> (any ActionSuggestionProvider)? {
        guard FeatureFlags.userServerAI else { return nil }
        func value(_ key: String) -> String? {
            guard let value = bundle.object(forInfoDictionaryKey: key) as? String,
                  !value.isEmpty, !value.contains("$(") else { return nil }
            return value
        }
        var address = value("SmallnextAPIBaseURL")
        #if DEBUG
        address = defaults.string(forKey: "server_ai_url") ?? address
        #endif
        guard let address, let url = URL(string: address),
              let options = FirebaseClientConfiguration.options(info: bundle.infoDictionary ?? [:])
        else { return UnavailableSuggestionProvider() }
        // Validate the endpoint before creating even an anonymous Firebase identity.
        guard HTTPActionSuggestionProvider.endpoint(url, schemes: ["https"]) else { return UnavailableSuggestionProvider() }
        let name = "SmallnextUserAI"
        if FirebaseApp.app(name: name) == nil {
            FirebaseApp.configure(name: name, options: options)
        }
        guard let app = FirebaseApp.app(name: name) else { return UnavailableSuggestionProvider() }
        app.isDataCollectionDefaultEnabled = false
        let identity = FirebaseAnonymousIdentity(auth: Auth.auth(app: app))
        return HTTPActionSuggestionProvider.server(baseURL: url, token: { try await identity.idToken() })
    }
}

/// Firebase owns token refresh and Keychain persistence. App progress stays in GRDB.
@MainActor
private final class FirebaseAnonymousIdentity {
    private let auth: Auth
    private var signingIn: Task<User, Error>?
    init(auth: Auth) { self.auth = auth }

    func idToken() async throws -> String {
        try Task.checkCancellation()
        do {
            let user: User
            if let current = auth.currentUser {
                user = current
            } else {
                let task: Task<User, Error>
                if let existing = signingIn { task = existing }
                else {
                    task = Task { @MainActor in try await auth.signInAnonymously().user }
                    signingIn = task
                }
                defer { signingIn = nil }
                user = try await task.value
            }
            try Task.checkCancellation()
            guard user.isAnonymous else { throw SuggestionFailure.rejected }
            return try await user.getIDToken()
        } catch {
            if Task.isCancelled { throw CancellationError() }
            if let failure = error as? SuggestionFailure { throw failure }
            throw SuggestionFailure.unavailable
        }
    }
}
