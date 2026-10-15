import Foundation
import SmallnextCore
import Auth

/// 사용자 서버의 주소와 Supabase 익명 신원을 연결한다.
enum UserServerAI {
    @MainActor
    static func configured(
        bundle: Bundle = .main, defaults: UserDefaults = .standard,
        identityFactory: (URL, String, TurnstileConfiguration?) -> SupabaseAnonymousIdentity = { url, key, captcha in
            SupabaseAnonymousIdentity(projectURL: url, publishableKey: key, captcha: captcha)
        }
    ) -> (any ActionSuggestionProvider)? {
        guard FeatureFlags.userServerAI else { return nil }
        func value(_ key: String) -> String? {
            guard let value = bundle.object(forInfoDictionaryKey: key) as? String,
                  !value.isEmpty, !value.contains("$("),
                  !value.contains(where: { $0.isWhitespace }) else { return nil }
            return value
        }
        var address = value("SmallnextAPIBaseURL")
        #if DEBUG
        address = defaults.string(forKey: "server_ai_url") ?? address
        #endif
        guard let address, let url = URL(string: address),
              let project = value("SmallnextSupabaseURL"), let projectURL = URL(string: project),
              let key = value("SmallnextSupabasePublishableKey"),
              key.range(of: #"^sb_publishable_[A-Za-z0-9_-]+$"#, options: .regularExpression) != nil,
              HTTPActionSuggestionProvider.endpoint(url, schemes: ["https"]),
              HTTPActionSuggestionProvider.endpoint(projectURL, schemes: ["https"])
        else { return UnavailableSuggestionProvider() }
        // Validate both endpoints before initializing an Auth client or reading its Keychain.
        let captcha: TurnstileConfiguration?
        do { captcha = try TurnstileConfiguration.load(info: bundle.infoDictionary ?? [:]) }
        catch { return UnavailableSuggestionProvider() }
        let identity = identityFactory(projectURL, key, captcha)
        return HTTPActionSuggestionProvider.server(baseURL: url, token: { try await identity.idToken() })
    }
}

/// The SDK refreshes sessions and persists them in Keychain. Progress stays in GRDB.
@MainActor
final class SupabaseAnonymousIdentity {
    private let auth: AuthClient
    private let storage: any AuthLocalStorage
    private let storageKey: String
    private var signingIn: Task<Session, Error>?
    private let captchaToken: (@MainActor @Sendable () async throws -> String)?
    private var signInWaiters: Set<UUID> = []
    private var awaitingCaptcha = false

    convenience init(projectURL: URL, publishableKey: String, captcha: TurnstileConfiguration? = nil) {
        let storage = KeychainLocalStorage(service: "dev.smallnext.app.supabase")
        let key = "session.\(projectURL.host ?? "")"
        let auth = AuthClient(
            url: projectURL.appendingPathComponent("auth/v1"),
            headers: ["apikey": publishableKey], storageKey: key, localStorage: storage,
            autoRefreshToken: false, emitLocalSessionAsInitialSession: true
        )
        let token: (@MainActor @Sendable () async throws -> String)?
        if let captcha { token = { try await TurnstileChallenge.shared.token(configuration: captcha) } }
        else { token = nil }
        self.init(auth: auth, storage: storage, storageKey: key, captchaToken: token)
    }

    init(auth: AuthClient, storage: any AuthLocalStorage, storageKey: String,
         captchaToken: (@MainActor @Sendable () async throws -> String)? = nil) {
        self.auth = auth
        self.storage = storage
        self.storageKey = storageKey
        self.captchaToken = captchaToken
    }

    func idToken() async throws -> String {
        try Task.checkCancellation()
        do {
            // The SDK treats a storage read error as no session. Never create a user while Keychain is locked.
            _ = try storage.retrieve(key: storageKey)
            if let current = auth.currentSession {
                guard current.user.isAnonymous else { throw SuggestionFailure.rejected }
            } else {
                let waiter = UUID()
                signInWaiters.insert(waiter)
                defer { signInWaiters.remove(waiter) }
                let task: Task<Session, Error>
                if let existing = signingIn { task = existing }
                else {
                    task = Task { [self] in
                        defer { signingIn = nil; awaitingCaptcha = false }
                        guard !signInWaiters.isEmpty else { throw CancellationError() }
                        awaitingCaptcha = captchaToken != nil
                        let token = try await captchaToken?()
                        awaitingCaptcha = false
                        try Task.checkCancellation()
                        if captchaToken != nil {
                            guard let token, !token.isEmpty, token.utf8.count <= 4096,
                                  !token.contains(where: { $0.isWhitespace }) else { throw SuggestionFailure.unavailable }
                        }
                        return try await auth.signInAnonymously(captchaToken: token)
                    }
                    signingIn = task
                }
                _ = try await withTaskCancellationHandler {
                    try await task.value
                } onCancel: {
                    Task { @MainActor in
                        self.signInWaiters.remove(waiter)
                        if self.signInWaiters.isEmpty && self.awaitingCaptcha { self.signingIn?.cancel() }
                    }
                }
            }
            try Task.checkCancellation()
            let session = try await auth.session
            try Task.checkCancellation()
            guard session.user.isAnonymous else { throw SuggestionFailure.rejected }
            // Refuse a token whose persistence write failed or whose session was replaced.
            guard auth.currentSession?.accessToken == session.accessToken else { throw SuggestionFailure.unavailable }
            return session.accessToken
        } catch {
            if Task.isCancelled || error is CancellationError { throw CancellationError() }
            if let failure = error as? SuggestionFailure { throw failure }
            throw SuggestionFailure.unavailable
        }
    }
}
