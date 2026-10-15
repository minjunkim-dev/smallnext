import Foundation
import XCTest
import SmallnextCore

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
    func testBundledUserServerFlagIsOff() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource:"feature-flags",withExtension:"json"))
        XCTAssertFalse(FeatureFlags.isEnabled("user_server_ai",registry:try Data(contentsOf:url)))
    }
    #endif
}
