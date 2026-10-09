import XCTest
import FirebaseCore
@testable import Smallnext

@MainActor
final class CrashReportingTests: XCTestCase {
    func testAutomaticCollectionIsDisabledInAppBundle() {
        XCTAssertEqual(Bundle.main.object(forInfoDictionaryKey: "FirebaseCrashlyticsCollectionEnabled") as? Bool, false)
        XCTAssertEqual(Bundle.main.object(forInfoDictionaryKey: "FirebaseDataCollectionDefaultEnabled") as? Bool, false)
    }

    private var validInfo: [String: Any] {
        ["CFBundleIdentifier": "dev.smallnext.app",
         "SmallnextFirebaseAppID": "1:123456789:ios:abc123",
         "SmallnextFirebaseSenderID": "123456789",
         "SmallnextFirebaseProjectID": "smallnext-test",
         "SmallnextFirebaseAPIKey": "AIza" + String(repeating: "A", count: 35)]
    }

    func testValidClientOptionsPreserveProjectAndAppIdentity() throws {
        let options = try XCTUnwrap(FirebaseClientConfiguration.options(info: validInfo))
        XCTAssertEqual(options.googleAppID, "1:123456789:ios:abc123")
        XCTAssertEqual(options.gcmSenderID, "123456789")
        XCTAssertEqual(options.projectID, "smallnext-test")
        XCTAssertEqual(options.bundleID, "dev.smallnext.app")
    }

    func testOffAndInvalidSettingsNeverInitializeFirebase() {
        XCTAssertNil(FirebaseApp.app())
        XCTAssertFalse(CrashReporting.start(enabled: false, info: validInfo))
        for key in validInfo.keys {
            for invalid: Any in ["", "$(UNSET)", "invalid value", 123] {
                var info = validInfo
                info[key] = invalid
                XCTAssertFalse(CrashReporting.start(enabled: true, info: info), key)
            }
            var missing = validInfo
            missing.removeValue(forKey: key)
            XCTAssertFalse(CrashReporting.start(enabled: true, info: missing), key)
        }
        for (key, value) in [("SmallnextFirebaseAppID", "1:123456789:android:abc123"),
                             ("SmallnextFirebaseSenderID", "987654321"),
                             ("SmallnextFirebaseAPIKey", "AIza-short"),
                             ("SmallnextFirebaseProjectID", "UPPER-case")] {
            var info = validInfo
            info[key] = value
            XCTAssertFalse(CrashReporting.start(enabled: true, info: info), key)
        }
        XCTAssertNil(FirebaseApp.app())
    }

    func testBundledCrashReportingFlagIsOff() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "feature-flags", withExtension: "json"))
        XCTAssertFalse(FeatureFlags.isEnabled("ios_crash_reporting", registry: try Data(contentsOf: url)))
    }
}
