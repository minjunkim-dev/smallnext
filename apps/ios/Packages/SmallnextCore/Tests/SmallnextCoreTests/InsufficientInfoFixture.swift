import Foundation
@testable import SmallnextCore

enum InsufficientInfoFixture {
    static func json() throws -> [String: Any] {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<7 { root.deleteLastPathComponent() }
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/fixtures/insufficient-info.json"))
        return try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }

    static func response() throws -> Data {
        try JSONSerialization.data(withJSONObject: json()["response"]!)
    }

    static func reason() throws -> String {
        let response = try json()["response"] as! [String: Any]
        return (response["proposal"] as! [String: Any])["reason"] as! String
    }
}
