import Foundation
import XCTest
@testable import SmallnextCore
import Auth
import Security
@testable import Smallnext

@MainActor
final class UserServerAITests: XCTestCase {
    func testAppBundleIncludesServerConfigurationKeys() {
        for key in ["SmallnextAPIBaseURL", "SmallnextSupabaseURL", "SmallnextSupabasePublishableKey",
                    "SmallnextAuthCaptchaURL", "SmallnextTurnstileSiteKey"] {
            XCTAssertNotNil(Bundle.main.object(forInfoDictionaryKey: key) as? String, key)
        }
    }

    #if DEBUG
    func testInvalidSettingsAndOffFlagNeverCreateIdentity() async throws {
        let previous = UserDefaults.standard.object(forKey: "user_server_ai")
        defer {
            if let previous { UserDefaults.standard.set(previous, forKey: "user_server_ai") }
            else { UserDefaults.standard.removeObject(forKey: "user_server_ai") }
        }
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        let valid = ["SmallnextAPIBaseURL": "https://api.example.invalid",
                     "SmallnextSupabaseURL": "https://project.example.invalid",
                     "SmallnextSupabasePublishableKey": "sb_publishable_synthetic"]
        var cases = [[String: String]]()
        for key in valid.keys {
            for value in [nil, "", "$(UNRESOLVED)", " "] as [String?] {
                var info = valid
                info[key] = value
                cases.append(info)
            }
        }
        for key in ["SmallnextAPIBaseURL", "SmallnextSupabaseURL"] {
            for value in ["http://example.invalid", "https://user:password@example.invalid", "https://example.invalid/path"] {
                var info = valid
                info[key] = value
                cases.append(info)
            }
        }
        var secret = valid
        secret["SmallnextSupabasePublishableKey"] = "sb_secret_invalid"
        cases.append(secret)
        var partialCaptcha = valid
        partialCaptcha["SmallnextAuthCaptchaURL"] = "https://captcha.example.invalid"
        cases.append(partialCaptcha)
        partialCaptcha["SmallnextTurnstileSiteKey"] = "invalid key"
        cases.append(partialCaptcha)
        UserDefaults.standard.set(true, forKey: "user_server_ai")
        var creations = 0
        for info in cases {
            let bundle = try settingsBundle(info)
            let provider = try XCTUnwrap(UserServerAI.configured(bundle: bundle, defaults: defaults) { _, _, _ in
                creations += 1
                return self.fixture().identity
            })
            do {
                _ = try await provider.suggest(SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: []))
                XCTFail("invalid settings must stay unavailable")
            } catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
        }
        XCTAssertEqual(creations, 0)
        UserDefaults.standard.set(false, forKey: "user_server_ai")
        XCTAssertNil(UserServerAI.configured(bundle: try settingsBundle(valid), defaults: defaults) { _, _, _ in
            creations += 1
            return self.fixture().identity
        })
        XCTAssertEqual(creations, 0)
        UserDefaults.standard.set(true, forKey: "user_server_ai")
        XCTAssertTrue(UserServerAI.configured(bundle: try settingsBundle(valid), defaults: defaults) { _, _, _ in
            creations += 1
            return self.fixture().identity
        } is ConsentGatedProvider)
        XCTAssertEqual(creations, 1)
        var captchaSettings = valid
        captchaSettings["SmallnextAuthCaptchaURL"] = "https://captcha.example.invalid"
        captchaSettings["SmallnextTurnstileSiteKey"] = "synthetic-site"
        XCTAssertNotNil(UserServerAI.configured(bundle: try settingsBundle(captchaSettings), defaults: defaults) { _, _, captcha in
            XCTAssertEqual(captcha?.siteKey, "synthetic-site")
            return self.fixture().identity
        })
    }

    func testBundledUserServerFlagIsOff() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "feature-flags", withExtension: "json"))
        XCTAssertFalse(FeatureFlags.isEnabled("user_server_ai", registry: try Data(contentsOf: url)))
    }
    #endif

    func testConcurrentAnonymousSignInIsSharedAndSessionIsReused() async throws {
        let f = fixture(delay: true)
        async let first = f.identity.idToken()
        async let second = f.identity.idToken()
        let tokens = try await [first, second]
        XCTAssertEqual(tokens, ["synthetic-access", "synthetic-access"])
        let again = try await f.identity.idToken()
        XCTAssertEqual(again, "synthetic-access")
        let requests = await f.transport.paths
        XCTAssertEqual(requests, ["/auth/v1/signup"])
        XCTAssertNotNil(try f.storage.retrieve(key: "test-session"))
    }

    func testRestoredSessionRefreshesWithoutAnotherAnonymousSignUp() async throws {
        let f = fixture()
        try f.storage.store(key: "test-session", value: JSONEncoder().encode(session(expired: true)))
        async let first = f.identity.idToken()
        async let second = f.identity.idToken()
        let tokens = try await [first, second]
        XCTAssertEqual(tokens, ["synthetic-access", "synthetic-access"])
        let requests = await f.transport.paths
        XCTAssertEqual(requests, ["/auth/v1/token"])
    }

    func testRefreshFailureDoesNotCreateAnotherAnonymousAccount() async throws {
        let f = fixture(status: 401)
        try f.storage.store(key: "test-session", value: JSONEncoder().encode(session(expired: true)))
        do { _ = try await f.identity.idToken(); XCTFail("must reject expired session") }
        catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
        let requests = await f.transport.paths
        XCTAssertEqual(requests, ["/auth/v1/token"])
    }

    func testAuthenticationFailureDoesNotRetry() async throws {
        let f = fixture(status: 403, delay: true)
        let first = Task { try await f.identity.idToken() }
        let second = Task { try await f.identity.idToken() }
        for task in [first, second] {
            do { _ = try await task.value; XCTFail("must fail") }
            catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
        }
        let requests = await f.transport.paths
        XCTAssertEqual(requests, ["/auth/v1/signup"])
        do { _ = try await f.identity.idToken(); XCTFail("must fail") }
        catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
        let afterExplicitRetry = await f.transport.paths
        XCTAssertEqual(afterExplicitRetry.count, 2)
    }

    func testCancellationDoesNotReturnTokenOrCancelAnotherWaiter() async throws {
        let f = fixture(delay: true)
        let cancelled = Task { try await f.identity.idToken() }
        for _ in 0..<100 {
            if await !f.transport.paths.isEmpty { break }
            try await Task.sleep(for: .milliseconds(5))
        }
        cancelled.cancel()
        let other = Task { try await f.identity.idToken() }
        do { _ = try await cancelled.value; XCTFail("must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }
        let value = try await other.value
        XCTAssertEqual(value, "synthetic-access")
        let requests = await f.transport.paths
        XCTAssertEqual(requests, ["/auth/v1/signup"])
    }

    func testStorageFailureNeverCreatesAccountOrReturnsUnpersistedToken() async throws {
        for readFailure in [true, false] {
            let f = fixture()
            f.storage.failReads = readFailure
            f.storage.failWrites = !readFailure
            do { _ = try await f.identity.idToken(); XCTFail("must fail closed") }
            catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
            let requests = await f.transport.paths
            XCTAssertEqual(requests.count, readFailure ? 0 : 1)
        }
    }

    func testNonAnonymousSessionIsRejectedWithoutNetwork() async throws {
        let f = fixture()
        try f.storage.store(key: "test-session", value: JSONEncoder().encode(session(anonymous: false)))
        do { _ = try await f.identity.idToken(); XCTFail("must reject") }
        catch { XCTAssertEqual(error as? SuggestionFailure, .rejected) }
        let requests = await f.transport.paths
        XCTAssertTrue(requests.isEmpty)
    }

    func testSDKSessionStorageUsesProtectedNonSynchronizingKeychain() throws {
        let service = "dev.smallnext.app.auth-test.\(UUID().uuidString)"
        let storage = KeychainLocalStorage(service: service)
        defer { try? storage.remove(key: "session") }
        let bytes = Data("synthetic-session".utf8)
        try storage.store(key: "session", value: bytes)
        XCTAssertEqual(try storage.retrieve(key: "session"), bytes)
        var result: CFTypeRef?
        let status = SecItemCopyMatching([
            kSecClass: kSecClassGenericPassword, kSecAttrService: service,
            kSecAttrAccount: "session", kSecReturnAttributes: true
        ] as CFDictionary, &result)
        XCTAssertEqual(status, errSecSuccess)
        let attributes = try XCTUnwrap(result as? [String: Any])
        XCTAssertEqual(attributes[kSecAttrAccessible as String] as? String, kSecAttrAccessibleAfterFirstUnlock as String)
        XCTAssertNotEqual(attributes[kSecAttrSynchronizable as String] as? Bool, true)
    }

    func testNewAnonymousSignInSharesCaptchaAndSendsItsTokenOnce() async throws {
        var challenges = 0
        let f = fixture(delay: true, captchaToken: { challenges += 1; return "synthetic-captcha" })
        async let first = f.identity.idToken()
        async let second = f.identity.idToken()
        _ = try await [first, second]
        XCTAssertEqual(challenges, 1)
        let tokens = await f.transport.captchaTokens
        XCTAssertEqual(tokens, ["synthetic-captcha"])
    }

    func testExistingSessionRefreshDoesNotAskForCaptcha() async throws {
        var challenges = 0
        let f = fixture(captchaToken: { challenges += 1; throw SuggestionFailure.unavailable })
        try f.storage.store(key: "test-session", value: JSONEncoder().encode(session(expired: true)))
        _ = try await f.identity.idToken()
        XCTAssertEqual(challenges, 0)
        let paths = await f.transport.paths
        XCTAssertEqual(paths, ["/auth/v1/token"])
    }

    func testCaptchaFailureAndEmptyTokenNeverCreateAccount() async throws {
        for token in [nil, "", "invalid token"] as [String?] {
            let f = fixture(captchaToken: {
                guard let token else { throw SuggestionFailure.unavailable }
                return token
            })
            do { _ = try await f.identity.idToken(); XCTFail("must fail closed") }
            catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
            let paths = await f.transport.paths
            XCTAssertTrue(paths.isEmpty)
        }
    }

    func testCancellingOnlyCaptchaWaiterDismissesChallengeWithoutSignUp() async throws {
        let challenge = TurnstileChallenge()
        let configuration = try TurnstileConfiguration(origin: URL(string: "https://captcha.example.invalid")!, siteKey: "synthetic-site")
        let f = fixture(captchaToken: { try await challenge.token(configuration: configuration) })
        let task = Task { try await f.identity.idToken() }
        for _ in 0..<100 where challenge.request == nil { await Task.yield() }
        XCTAssertNotNil(challenge.request)
        task.cancel()
        do { _ = try await task.value; XCTFail("must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertNil(challenge.request)
        let paths = await f.transport.paths
        XCTAssertTrue(paths.isEmpty)
    }

    func testCaptchaUserCancellationNeverCreatesAccount() async throws {
        let f = fixture(captchaToken: { throw CancellationError() })
        do { _ = try await f.identity.idToken(); XCTFail("must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }
        let paths = await f.transport.paths
        XCTAssertTrue(paths.isEmpty)
    }

    func testCancellingOneWaiterDoesNotCancelSharedChallenge() async throws {
        let challenge = TurnstileChallenge()
        let configuration = try TurnstileConfiguration(origin: URL(string: "https://captcha.example.invalid")!, siteKey: "synthetic-site")
        let f = fixture(captchaToken: { try await challenge.token(configuration: configuration) })
        let first = Task { try await f.identity.idToken() }
        let second = Task { try await f.identity.idToken() }
        for _ in 0..<100 where challenge.request == nil { await Task.yield() }
        let request = try XCTUnwrap(challenge.request)
        first.cancel()
        for _ in 0..<10 { await Task.yield() }
        XCTAssertEqual(challenge.request?.id, request.id)
        challenge.finish(id: request.id, result: .success("synthetic-captcha"))
        do { _ = try await first.value; XCTFail("must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }
        _ = try await second.value
        let paths = await f.transport.paths
        XCTAssertEqual(paths, ["/auth/v1/signup"])
    }

    private func settingsBundle(_ settings: [String: String]) throws -> Bundle {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".bundle")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try FileManager.default.removeItem(at: directory) }
        var info = settings
        info["CFBundleIdentifier"] = "dev.smallnext.app.settings-test"
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
            .write(to: directory.appendingPathComponent("Info.plist"))
        return try XCTUnwrap(Bundle(url: directory))
    }

    private func session(expired: Bool = false, anonymous: Bool = true) -> Session {
        Session(accessToken: "synthetic-old", tokenType: "bearer", expiresIn: 3600,
                expiresAt: Date().timeIntervalSince1970 + (expired ? -60 : 3600), refreshToken: "synthetic-refresh",
                user: User(id: UUID(), appMetadata: [:], userMetadata: [:], aud: "authenticated",
                           createdAt: Date(), updatedAt: Date(), isAnonymous: anonymous))
    }

    private func fixture(status: Int = 200, delay: Bool = false,
                         captchaToken: (@MainActor @Sendable () async throws -> String)? = nil) -> (identity: SupabaseAnonymousIdentity, transport: AuthTransport, storage: MemoryAuthStorage) {
        let storage = MemoryAuthStorage()
        let transport = AuthTransport(status: status, delay: delay)
        let client = AuthClient(url: URL(string: "https://auth.example.invalid/auth/v1")!,
                                headers: ["apikey": "sb_publishable_synthetic"], storageKey: "test-session", localStorage: storage,
                                fetch: { try await transport.fetch($0) }, autoRefreshToken: false,
                                emitLocalSessionAsInitialSession: true)
        return (SupabaseAnonymousIdentity(auth: client, storage: storage, storageKey: "test-session", captchaToken: captchaToken), transport, storage)
    }
}

private actor AuthTransport {
    let status: Int
    let delay: Bool
    var paths: [String] = []
    var captchaTokens: [String?] = []
    init(status: Int, delay: Bool) { self.status = status; self.delay = delay }
    func fetch(_ request: URLRequest) async throws -> (Data, URLResponse) {
        paths.append(request.url!.path)
        if let body = request.httpBody,
           let value = try JSONSerialization.jsonObject(with: body) as? [String: Any] {
            captchaTokens.append((value["gotrue_meta_security"] as? [String: Any])?["captcha_token"] as? String)
        }
        if delay { try await Task.sleep(for: .milliseconds(100)) }
        let body: [String: Any] = status == 200 ? [
            "access_token": "synthetic-access", "token_type": "bearer", "expires_in": 3600,
            "expires_at": Date().timeIntervalSince1970 + 3600, "refresh_token": "synthetic-refresh-new",
            "user": ["id": "00000000-0000-0000-0000-000000000001", "aud": "authenticated",
                     "app_metadata": [:], "user_metadata": [:], "is_anonymous": true,
                     "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"]
        ] : ["msg": "synthetic rejection", "error_code": "invalid_credentials"]
        return (try JSONSerialization.data(withJSONObject: body),
                HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: [:])!)
    }
}

private final class MemoryAuthStorage: AuthLocalStorage, @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String: Data] = [:]
    var failReads = false
    var failWrites = false
    func store(key: String, value: Data) throws {
        lock.lock(); defer { lock.unlock() }
        if failWrites { throw SuggestionFailure.unavailable }
        values[key] = value
    }
    func retrieve(key: String) throws -> Data? {
        lock.lock(); defer { lock.unlock() }
        if failReads { throw SuggestionFailure.unavailable }
        return values[key]
    }
    func remove(key: String) throws {
        lock.lock(); defer { lock.unlock() }
        values.removeValue(forKey: key)
    }
}
