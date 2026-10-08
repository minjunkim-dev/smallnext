import Foundation

enum FeatureFlags {
    static func isEnabled(_ key: String, registry: Data?) -> Bool {
        guard let registry,
              let decoded = try? JSONDecoder().decode(Registry.self, from: registry),
              decoded.version == 1
        else { return false }
        let matches = decoded.flags.filter { $0.key == key }
        return matches.count == 1 ? matches[0].default : false
    }

    static var iosCoreFlow: Bool {
        configured("ios_core_flow")
    }

    static var userServerAI: Bool {
        configured("user_server_ai")
    }

    private static func configured(_ key: String) -> Bool {
        #if DEBUG
        // 실행 인자 `-ios_core_flow YES`는 문자열로 들어온다. bool(forKey:)가 YES/NO/1/0을 해석한다.
        if UserDefaults.standard.object(forKey: key) != nil {
            return UserDefaults.standard.bool(forKey: key)
        }
        #endif
        let registry = Bundle.main
            .url(forResource: "feature-flags", withExtension: "json")
            .flatMap { try? Data(contentsOf: $0) }
        return isEnabled(key, registry: registry)
    }

    private struct Registry: Decodable {
        var version: Int
        var flags: [Flag]
    }

    private struct Flag: Decodable {
        var key: String
        var `default`: Bool
    }
}
