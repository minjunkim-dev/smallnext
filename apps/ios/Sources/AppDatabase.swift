import Foundation
import GRDB

struct AppDatabase {
    let writer: DatabasePool

    init(path: String) throws {
        writer = try DatabasePool(path: path)
        var migrator = DatabaseMigrator()
        migrator.registerMigration("bootstrap") { db in
            try db.create(table: "app_metadata") { table in
                table.column("key", .text).primaryKey()
                table.column("value", .text).notNull()
            }
            try db.execute(
                sql: "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                arguments: ["schema_version", "1"]
            )
        }
        try migrator.migrate(writer)
    }

    static func openDefault() throws -> AppDatabase {
        let directory = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ).appendingPathComponent("Smallnext", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return try AppDatabase(path: directory.appendingPathComponent("smallnext.sqlite").path)
    }
}
