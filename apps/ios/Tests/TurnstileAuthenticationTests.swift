import Foundation
import XCTest
@testable import Smallnext
import SmallnextCore

@MainActor
final class TurnstileAuthenticationTests: XCTestCase {
    private let nonce = UUID(uuidString: "00000000-0000-4000-8000-000000000001")!
    private func configuration() throws -> TurnstileConfiguration {
        try TurnstileConfiguration(origin: URL(string: "https://captcha.example.invalid")!, siteKey: "synthetic-site")
    }

    func testNavigationPolicyIsRegisteredAsAnObjectiveCDelegate() throws {
        let request = TurnstileChallenge.Request(id: nonce, configuration: try configuration())
        let coordinator = TurnstileWebView.Coordinator(request: request) { _ in }
        XCTAssertTrue(coordinator.responds(to: NSSelectorFromString("webView:decidePolicyForNavigationAction:decisionHandler:")),
                      "WebKit must invoke the existing navigation allowlist.")
    }

    func testConfigurationPairIsOptionalButPartialOrUnsafeSettingsFailClosed() throws {
        XCTAssertNil(try TurnstileConfiguration.load(info: [:]))
        XCTAssertNil(try TurnstileConfiguration.load(info: ["SmallnextAuthCaptchaURL": "$(EMPTY)", "SmallnextTurnstileSiteKey": ""]))
        for origin in ["http://captcha.example.invalid", "https://user:pass@captcha.example.invalid",
                       "https://captcha.example.invalid/path", "https://captcha.example.invalid?query=1"] {
            XCTAssertThrowsError(try TurnstileConfiguration(origin: URL(string: origin)!, siteKey: "synthetic"))
        }
        for info in [["SmallnextAuthCaptchaURL": "https://captcha.example.invalid"],
                     ["SmallnextTurnstileSiteKey": "synthetic"],
                     ["SmallnextAuthCaptchaURL": "https://captcha.example.invalid", "SmallnextTurnstileSiteKey": "invalid key"]] {
            XCTAssertThrowsError(try TurnstileConfiguration.load(info: info))
        }
    }

    func testBridgeAcceptsOnlyExactHTTPSOriginMainFramePageAndNonce() throws {
        let config = try configuration()
        let page = config.pageURL(nonce: nonce)
        let body = ["type": "success", "token": "synthetic-captcha", "nonce": nonce.uuidString.lowercased(), "origin": config.origin.absoluteString]
        XCTAssertEqual(try config.messageToken(body: body, frameURL: page, securityOrigin: config.origin, mainFrame: true, nonce: nonce), "synthetic-captcha")
        XCTAssertThrowsError(try config.messageToken(body: body, frameURL: page, securityOrigin: config.origin, mainFrame: false, nonce: nonce))
        for address in ["https://other.example.invalid", "https://sub.captcha.example.invalid",
                        "http://captcha.example.invalid", "https://captcha.example.invalid:444"] {
            XCTAssertThrowsError(try config.messageToken(body: body, frameURL: page, securityOrigin: URL(string: address), mainFrame: true, nonce: nonce))
            XCTAssertThrowsError(try config.messageToken(body: body, frameURL: URL(string: address), securityOrigin: config.origin, mainFrame: true, nonce: nonce))
        }
        for (key, value) in [("nonce", UUID().uuidString), ("origin", "https://other.example.invalid"),
                             ("type", "error"), ("token", ""), ("token", "invalid token"), ("token", String(repeating: "x", count: 4097))] {
            var changed = body
            changed[key] = value
            XCTAssertThrowsError(try config.messageToken(body: changed, frameURL: page, securityOrigin: config.origin, mainFrame: true, nonce: nonce))
        }
    }

    func testChallengeCompletesOnceAndIgnoresStalePage() async throws {
        let challenge = TurnstileChallenge()
        let config = try configuration()
        let task = Task { try await challenge.token(configuration: config) }
        for _ in 0..<100 where challenge.request == nil { await Task.yield() }
        let first = try XCTUnwrap(challenge.request)
        challenge.finish(id: first.id, result: .success("synthetic-captcha"))
        challenge.finish(id: first.id, result: .failure(SuggestionFailure.unavailable))
        let result = try await task.value
        XCTAssertEqual(result, "synthetic-captcha")
        let next = Task { try await challenge.token(configuration: config) }
        for _ in 0..<100 where challenge.request == nil { await Task.yield() }
        let second = try XCTUnwrap(challenge.request)
        challenge.finish(id: first.id, result: .failure(CancellationError()))
        XCTAssertEqual(challenge.request?.id, second.id)
        next.cancel()
        do { _ = try await next.value; XCTFail("must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertNil(challenge.request)
    }

    func testChallengeTimeoutFailsClosed() async throws {
        let challenge = TurnstileChallenge()
        do {
            _ = try await challenge.token(configuration: configuration(), timeout: .milliseconds(1))
            XCTFail("must time out")
        } catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
        XCTAssertNil(challenge.request)
    }
}
