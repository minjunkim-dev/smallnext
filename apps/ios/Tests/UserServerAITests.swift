import Foundation
import XCTest
@testable import SmallnextCore
import FirebaseCore
@testable import Smallnext

// App bundle and Info.plist checks; the server-path contract lives in SmallnextCore tests.
@MainActor
final class UserServerAITests: XCTestCase {
    func testAppBundleIncludesServerConfigurationKeys() {
        for key in ["SmallnextAPIBaseURL", "SmallnextFirebaseAppID", "SmallnextFirebaseSenderID",
                    "SmallnextFirebaseProjectID", "SmallnextFirebaseAPIKey"] {
            XCTAssertNotNil(Bundle.main.object(forInfoDictionaryKey: key) as? String, key)
        }
    }

    #if DEBUG
    func testMissingOrPlainHTTPSettingsStayUnavailableWithoutFirebaseIdentity() async throws {
        let flag = UserDefaults.standard.object(forKey: "user_server_ai")
        UserDefaults.standard.set(true, forKey: "user_server_ai")
        defer {
            if let flag { UserDefaults.standard.set(flag, forKey: "user_server_ai") }
            else { UserDefaults.standard.removeObject(forKey: "user_server_ai") }
        }
        let defaults = try XCTUnwrap(UserDefaults(suiteName: UUID().uuidString))
        for address in [nil, "", "$(SMALLNEXT_API_BASE_URL)", "http://api.example.invalid"] as [String?] {
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".bundle")
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: directory) }
            var info: [String: Any] = [
                "CFBundleIdentifier": "dev.smallnext.app.settings-test",
                "SmallnextFirebaseAppID": "1:123456789:ios:abc123",
                "SmallnextFirebaseSenderID": "123456789",
                "SmallnextFirebaseProjectID": "smallnext-test",
                "SmallnextFirebaseAPIKey": "AIza" + String(repeating: "A", count: 35)
            ]
            info["SmallnextAPIBaseURL"] = address
            try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
                .write(to: directory.appendingPathComponent("Info.plist"))
            let bundle = try XCTUnwrap(Bundle(url: directory))
            let provider = try XCTUnwrap(UserServerAI.configured(bundle: bundle, defaults: defaults))
            do {
                _ = try await provider.suggest(SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: []))
                XCTFail("invalid settings must stay unavailable")
            } catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
            XCTAssertNil(FirebaseApp.app(name: "SmallnextUserAI"))
        }
    }

    func testBundledUserServerFlagIsOff() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource:"feature-flags",withExtension:"json"))
        XCTAssertFalse(FeatureFlags.isEnabled("user_server_ai",registry:try Data(contentsOf:url)))
    }
    #endif
}
