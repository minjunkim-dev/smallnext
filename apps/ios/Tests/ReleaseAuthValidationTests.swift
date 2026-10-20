import Auth
import Foundation
import SmallnextCore
import XCTest
@testable import Smallnext

@MainActor
final class ReleaseAuthValidationTests: XCTestCase {
    func testOptInReleaseAnonymousAuthentication() async throws {
        guard ProcessInfo.processInfo.environment["SMALLNEXT_LIVE_AUTH_CHECK"] == "1" else {
            throw XCTSkip("Live authentication requires explicit opt-in; no identity or network created.")
        }
        guard isReleaseBuild else {
            XCTFail("Live authentication validation requires a Release test build.")
            return
        }
        guard !FeatureFlags.userServerAI, !FeatureFlags.iosCoreFlow, UserServerAI.configured() == nil else {
            XCTFail("Both product flags and the product AI provider must remain OFF.")
            return
        }
        let settings: ReleaseAuthSettings
        do { settings = try ReleaseAuthSettings(info: Bundle.main.infoDictionary ?? [:]) }
        catch { XCTFail("Release authentication settings are missing or invalid."); return }

        let identifier = UUID().uuidString
        let storage = KeychainLocalStorage(service: "dev.smallnext.app.auth-validation.\(identifier)")
        let key = "session.\(identifier)"
        defer {
            do { try storage.remove(key: key) }
            catch { XCTFail("Isolated authentication session cleanup failed.") }
        }
        let transport = ReleaseAuthTransport(signupURL: settings.signupURL)
        let auth = AuthClient(
            url: settings.projectURL.appendingPathComponent("auth/v1"),
            headers: ["apikey": settings.publishableKey], storageKey: key, localStorage: storage,
            fetch: { try await transport.fetch($0) }, autoRefreshToken: false,
            emitLocalSessionAsInitialSession: true
        )
        let captchaToken: (@MainActor @Sendable () async throws -> String)?
        if let captcha = settings.captcha {
            captchaToken = { try await TurnstileChallenge.shared.token(configuration: captcha) }
        } else { captchaToken = nil }
        let identity = SupabaseAnonymousIdentity(auth: auth, storage: storage, storageKey: key, captchaToken: captchaToken)
        do {
            let token = try await identity.idToken()
            XCTAssertFalse(token.isEmpty, "Authentication must return a nonempty token.")
            let count = await transport.requestCount
            XCTAssertEqual(count, 1, "Only one anonymous signup request is permitted.")
        } catch { XCTFail("Release authentication validation failed; sensitive details omitted.") }
    }

    func testSettingsRejectInvalidEndpointsKeysAndPartialCaptcha() throws {
        let valid = ["SmallnextSupabaseURL": "https://project.example.invalid",
                     "SmallnextSupabasePublishableKey": "sb_publishable_synthetic"]
        XCTAssertNil(try ReleaseAuthSettings(info: valid).captcha)
        for key in valid.keys {
            for value in [nil, "", "$(UNRESOLVED)", " "] as [String?] {
                var info = valid
                info[key] = value
                XCTAssertThrowsError(try ReleaseAuthSettings(info: info))
            }
        }
        for address in ["http://project.example.invalid", "https://user:password@project.example.invalid",
                        "https://project.example.invalid/path", "https://project.example.invalid?query=value",
                        "https://$(UNRESOLVED)", "https://project.example.invalid "] {
            var info = valid
            info["SmallnextSupabaseURL"] = address
            XCTAssertThrowsError(try ReleaseAuthSettings(info: info))
        }
        var info = valid
        info["SmallnextSupabasePublishableKey"] = "sb_secret_synthetic"
        XCTAssertThrowsError(try ReleaseAuthSettings(info: info))
        for key in ["SmallnextAuthCaptchaURL", "SmallnextTurnstileSiteKey"] {
            info = valid
            info[key] = key == "SmallnextAuthCaptchaURL" ? "https://captcha.example.invalid" : "synthetic-site"
            XCTAssertThrowsError(try ReleaseAuthSettings(info: info))
        }
        info = valid
        info["SmallnextAuthCaptchaURL"] = "https://captcha.example.invalid"
        info["SmallnextTurnstileSiteKey"] = "synthetic-site"
        XCTAssertNotNil(try ReleaseAuthSettings(info: info).captcha)
    }

    func testTransportRejectsEveryNonSignupRequestBeforeNetwork() async throws {
        let signup = URL(string: "https://project.example.invalid/auth/v1/signup")!
        let transport = ReleaseAuthTransport(signupURL: signup)
        for address in ["https://other.example.invalid/auth/v1/signup", "http://project.example.invalid/auth/v1/signup",
                        "https://project.example.invalid/v1/suggestions", "https://project.example.invalid/auth/v1/token",
                        "https://project.example.invalid/auth/v1/signup?query=value", signup.absoluteString] {
            var request = URLRequest(url: URL(string: address)!)
            request.httpMethod = address == signup.absoluteString ? "GET" : "POST"
            do { _ = try await transport.fetch(request); XCTFail("Request must be rejected.") }
            catch { XCTAssertEqual(error as? SuggestionFailure, .rejected) }
        }
        let count = await transport.requestCount
        XCTAssertEqual(count, 0)
    }

    func testRedirectsAreRejected() async {
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        let url = URL(string: "https://other.example.invalid/v1/suggestions")!
        let request = URLRequest(url: url)
        let allowed = await withCheckedContinuation { continuation in
            RejectAuthRedirects().urlSession(
                session, task: session.dataTask(with: request),
                willPerformHTTPRedirection: HTTPURLResponse(url: url, statusCode: 307, httpVersion: nil, headerFields: nil)!,
                newRequest: request, completionHandler: { continuation.resume(returning: $0 != nil) }
            )
        }
        XCTAssertFalse(allowed)
    }

    private var isReleaseBuild: Bool {
        #if DEBUG
        false
        #else
        true
        #endif
    }
}

private struct ReleaseAuthSettings {
    let projectURL: URL
    let publishableKey: String
    let captcha: TurnstileConfiguration?
    var signupURL: URL { projectURL.appendingPathComponent("auth/v1/signup") }

    init(info: [String: Any]) throws {
        guard let address = info["SmallnextSupabaseURL"] as? String,
              !address.contains("$("), !address.contains(where: { $0.isWhitespace }),
              let url = URL(string: address), HTTPActionSuggestionProvider.endpoint(url, schemes: ["https"]),
              let key = info["SmallnextSupabasePublishableKey"] as? String,
              key.range(of: #"^sb_publishable_[A-Za-z0-9_-]+$"#, options: .regularExpression) != nil
        else { throw SuggestionFailure.unavailable }
        projectURL = url
        publishableKey = key
        captcha = try TurnstileConfiguration.load(info: info)
    }
}

private actor ReleaseAuthTransport {
    private let signupURL: URL
    private let session: URLSession
    private(set) var requestCount = 0

    init(signupURL: URL) {
        self.signupURL = signupURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 30
        session = URLSession(configuration: configuration)
    }

    deinit { session.invalidateAndCancel() }

    func fetch(_ request: URLRequest) async throws -> (Data, URLResponse) {
        guard request.url == signupURL, request.httpMethod == "POST", requestCount == 0 else {
            throw SuggestionFailure.rejected
        }
        requestCount += 1
        return try await session.data(for: request, delegate: RejectAuthRedirects())
    }
}

private final class RejectAuthRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
