import Foundation
import GRDB
import XCTest
@testable import Smallnext

final class AppDatabaseTests: XCTestCase {
    func testBootstrapSurvivesReopeningTheDatabase() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let path = directory.appendingPathComponent("test.sqlite").path

        do {
            let database = try AppDatabase(path: path)
            try database.writer.write { db in
                try db.execute(sql: "INSERT INTO app_metadata VALUES (?, ?)", arguments: ["test", "persistent"])
            }
        }

        let reopened = try AppDatabase(path: path)
        let values = try reopened.writer.read { db in
            (
                try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = 'schema_version'"),
                try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = 'test'")
            )
        }
        XCTAssertEqual(values.0, "1")
        XCTAssertEqual(values.1, "persistent")
    }
}
