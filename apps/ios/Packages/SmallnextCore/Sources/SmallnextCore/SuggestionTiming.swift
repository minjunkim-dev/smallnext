import Foundation

/// Debug에서만 명시적으로 켠다. 시각은 프로세스 밖으로 내보내지 않는다.
public final class SuggestionTiming: @unchecked Sendable {
    @TaskLocal public static var current: SuggestionTiming?
    public let id = UUID().uuidString
    public let kind: SuggestionKind
    private let start: TimeInterval
    private let lock = NSLock()
    private var record: Record
    public var outcome: String { lock.withLock { record.outcome } }

    struct Server: Codable {
        public let run_id: String
        let generate_ms: Double?
        let check_ms: Double?
        let total_ms: Double
    }
    struct Record: Codable {
        let runID: String
        let requestKind: String
        public var outcome = "pending"
        public var authMS: Double?
        public var authApplicable: Bool?
        public var httpMS: Double?
        var applyMS: Double?
        var buttonToApplyMS: Double?
        // 실제 화면 관측은 외부 관측자가 별도 자료로 연결한다.
        var screenUpperBoundMS: Double?
        public var server: Server?
        var transportQueueResidualMS: Double?
    }

    public init(kind: SuggestionKind, start: TimeInterval) {
        self.kind = kind
        self.start = start
        record = Record(runID: id, requestKind: kind.rawValue)
    }
    public static var enabled: Bool {
        #if DEBUG
        UserDefaults.standard.bool(forKey: "suggestion_timing")
        #else
        false
        #endif
    }
    public static var now: TimeInterval { ProcessInfo.processInfo.systemUptime }
    func authentication(ms: Double?, applicable: Bool) {
        lock.withLock { record.authMS = ms; record.authApplicable = applicable }
    }
    public func http(ms: Double) { lock.withLock { record.httpMS = ms } }
    public func server(data: Data) {
        guard data.count <= 128 * 1024 else { return }
        lock.withLock {
            struct Envelope: Decodable { let _timing: Server? }
            if let server = try? JSONDecoder().decode(Envelope.self, from: data)._timing,
               server.run_id == id, server.total_ms.isFinite, server.total_ms >= 0,
               [server.generate_ms, server.check_ms].allSatisfy({ $0 == nil || ($0!.isFinite && $0! >= 0) }),
               (server.generate_ms ?? 0) + (server.check_ms ?? 0) <= server.total_ms {
                record.server = server
                if let httpMS = record.httpMS, httpMS >= server.total_ms { record.transportQueueResidualMS = httpMS - server.total_ms }
            }
        }
    }
    func finish(_ outcome: String, applyStart: TimeInterval) {
        lock.withLock {
            record.outcome = outcome
            record.applyMS = (Self.now - applyStart) * 1000
            record.buttonToApplyMS = (Self.now - start) * 1000
        }
    }
    func snapshot() -> Record { lock.withLock { record } }
    func save() {
        #if DEBUG
        guard Self.enabled, let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else { return }
        let file = directory.appendingPathComponent("suggestion-timing.json")
        let data = try? Data(contentsOf: file)
        var records = data.flatMap { $0.count <= 64 * 1024 ? try? JSONDecoder().decode([Record].self, from: $0) : nil } ?? []
        records.removeAll { $0.runID == id }
        records.append(snapshot())
        if let bytes = try? JSONEncoder().encode(Array(records.suffix(16))) { try? bytes.write(to: file, options: .atomic) }
        #endif
    }
}
