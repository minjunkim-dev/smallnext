import Foundation
import XCTest
@testable import SmallnextCore
@testable import Smallnext

final class AIConsentTests: XCTestCase {
    func testBundleDeclaresBetaReleaseRequirements() throws {
        let info = try XCTUnwrap(Bundle.main.infoDictionary)
        XCTAssertEqual(info["ITSAppUsesNonExemptEncryption"] as? Bool, false)
        let icons = try XCTUnwrap(info["CFBundleIcons"] as? [String: Any])
        let primary = try XCTUnwrap(icons["CFBundlePrimaryIcon"] as? [String: Any])
        XCTAssertEqual(primary["CFBundleIconName"] as? String, "AppIcon")
        let manifestURL = try XCTUnwrap(Bundle.main.url(forResource: "PrivacyInfo", withExtension: "xcprivacy"))
        let manifest = try XCTUnwrap(PropertyListSerialization.propertyList(from: Data(contentsOf: manifestURL), format: nil) as? [String: Any])
        XCTAssertEqual(manifest["NSPrivacyTracking"] as? Bool, false)
        let collected = try XCTUnwrap(manifest["NSPrivacyCollectedDataTypes"] as? [[String: Any]])
        XCTAssertTrue(collected.contains { $0["NSPrivacyCollectedDataType"] as? String == "NSPrivacyCollectedDataTypeOtherUserContent" })
    }

    func testPrivacyPolicyURLAcceptsOnlyHTTPSPages() {
        XCTAssertEqual(AIConsent.privacyPolicyURL(info: ["SmallnextPrivacyPolicyURL": "https://example.invalid/privacy"]),
                       URL(string: "https://example.invalid/privacy"))
        for value in [nil, "", "$(SMALLNEXT_PRIVACY_POLICY_URL)", "http://example.invalid/privacy",
                      "https://user:password@example.invalid/privacy", "privacy", "https:///privacy"] as [String?] {
            XCTAssertNil(AIConsent.privacyPolicyURL(info: value.map { ["SmallnextPrivacyPolicyURL": $0] } ?? [:]), value ?? "nil")
        }
    }

    func testProviderSendsOnlyWhileConsentIsGranted() async throws {
        let previous = UserDefaults.standard.object(forKey: AIConsent.key)
        defer {
            if let previous { UserDefaults.standard.set(previous, forKey: AIConsent.key) }
            else { UserDefaults.standard.removeObject(forKey: AIConsent.key) }
        }
        let base = CountingProvider()
        let provider = ConsentGatedProvider(base: base)
        let request = SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: [])
        for consent in [nil, true, false] as [Bool?] {
            if let consent { UserDefaults.standard.set(consent, forKey: AIConsent.key) }
            else { UserDefaults.standard.removeObject(forKey: AIConsent.key) }
            do {
                let candidate = try await provider.suggest(request)
                XCTAssertEqual(consent, true)
                XCTAssertEqual(candidate, .noAction)
            } catch {
                XCTAssertNotEqual(consent, true)
                XCTAssertEqual(error as? SuggestionFailure, .unavailable)
            }
        }
        let calls = await base.calls
        XCTAssertEqual(calls, 1)
    }
}

private actor CountingProvider: ActionSuggestionProvider {
    var calls = 0
    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        calls += 1
        return .noAction
    }
}
