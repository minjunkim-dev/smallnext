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
        // 제품 진행 상태. 플래그와 관계없이 적용한다. 선택한 목표는 app_metadata의 selected_goal_id다.
        migrator.registerMigration("progress_v1") { db in
            try db.create(table: "goal") { table in
                table.autoIncrementedPrimaryKey("id")
                table.column("statement", .text).notNull()
                table.column("deadline", .text)
                table.column("current_state", .text)
                table.column("blocker", .text)
                table.column("materials", .text)
                table.column("available_minutes", .integer)
                table.column("completion_criteria", .text)
                table.column("status", .text).notNull().defaults(to: "active")
                    .check { ["active", "stopped"].contains($0) }
                table.column("revision", .integer).notNull().defaults(to: 0)
                table.column("created_at", .datetime).notNull()
                table.column("updated_at", .datetime).notNull()
            }
            try db.create(table: "action") { table in
                table.autoIncrementedPrimaryKey("id")
                table.column("goal_id", .integer).notNull().indexed().references("goal", onDelete: .cascade)
                table.column("task", .text).notNull()
                table.column("done_when", .text).notNull()
                table.column("estimated_minutes", .integer).notNull()
                table.column("reason", .text)
                table.column("target_name", .text)
                table.column("target_description", .text)
                table.column("status", .text).notNull()
                    .check { ["current", "done", "deferred", "split"].contains($0) }
                table.column("split_from_id", .integer).references("action", onDelete: .setNull)
                table.column("remaining_summary", .text)
                table.column("sequence", .integer).notNull()
            }
            try db.execute(sql: "CREATE UNIQUE INDEX action_one_current ON action(goal_id) WHERE status = 'current'")
            try db.create(table: "action_note") { table in
                table.autoIncrementedPrimaryKey("id")
                table.column("action_id", .integer).notNull().indexed().references("action", onDelete: .cascade)
                table.column("body", .text).notNull()
                table.column("is_draft", .boolean).notNull()
                table.column("updated_at", .datetime).notNull()
            }
            try db.execute(sql: "CREATE UNIQUE INDEX action_note_one_draft ON action_note(action_id) WHERE is_draft")
            try db.create(table: "completion") { table in
                table.autoIncrementedPrimaryKey("id")
                table.column("action_id", .integer).notNull().indexed().references("action", onDelete: .cascade)
                table.column("completed_at", .datetime).notNull()
            }
            try db.execute(sql: "CREATE UNIQUE INDEX completion_one_per_action ON completion(action_id)")
            try db.create(table: "suggestion_request") { table in
                table.autoIncrementedPrimaryKey("id")
                table.column("goal_id", .integer).notNull().indexed().references("goal", onDelete: .cascade)
                table.column("kind", .text).notNull()
                table.column("goal_revision", .integer).notNull()
                table.column("status", .text).notNull()
                    .check { ["pending", "applied", "failed", "interrupted", "cancelled"].contains($0) }
                table.column("failure_reason", .text)
                table.column("created_at", .datetime).notNull()
            }
            try db.execute(sql: "CREATE UNIQUE INDEX suggestion_request_one_pending ON suggestion_request(goal_id) WHERE status = 'pending'")
        }
        // 더 작게 요청이 돌려준 확인 질문과 그 답. 답하기 전까지 질문을 화면에 복구한다.
        migrator.registerMigration("progress_v2_question") { db in
            try db.alter(table: "suggestion_request") { table in
                table.add(column: "question", .text)
                table.add(column: "answer", .text)
            }
        }
        migrator.registerMigration("progress_v3_material_links") { db in
            try db.alter(table: "action") { table in
                table.add(column: "material_links", .text).notNull().defaults(to: "[]")
            }
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
