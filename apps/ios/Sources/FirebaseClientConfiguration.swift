import Foundation
import FirebaseCore

enum FirebaseClientConfiguration {
    static func options(info: [String: Any]) -> FirebaseOptions? {
        func value(_ key: String) -> String? {
            guard let value = info[key] as? String,
                  !value.isEmpty, !value.contains("$("),
                  !value.contains(where: { $0.isWhitespace }) else { return nil }
            return value
        }
        guard let bundleID = value("CFBundleIdentifier"),
              let appID = value("SmallnextFirebaseAppID"),
              let sender = value("SmallnextFirebaseSenderID"),
              let project = value("SmallnextFirebaseProjectID"),
              let key = value("SmallnextFirebaseAPIKey"),
              appID.range(of: #"^1:[0-9]+:ios:[0-9a-f]+$"#, options: .regularExpression) != nil,
              appID.split(separator: ":")[1] == Substring(sender),
              project.range(of: #"^[a-z][a-z0-9-]{4,28}[a-z0-9]$"#, options: .regularExpression) != nil,
              key.range(of: #"^AIza[A-Za-z0-9_-]{35}$"#, options: .regularExpression) != nil
        else { return nil }
        let options = FirebaseOptions(googleAppID: appID, gcmSenderID: sender)
        options.projectID = project
        options.apiKey = key
        options.bundleID = bundleID
        return options
    }
}
