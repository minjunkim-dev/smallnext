import XCTest
import SmallnextCore

// The registry ships in the app bundle, so this check stays in the app-hosted tests.
final class FeatureFlagsBundleTests: XCTestCase {
    func testBundledCoreFlowIsOff() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "feature-flags", withExtension: "json"))
        let data = try Data(contentsOf: url)
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: data))
    }
}
