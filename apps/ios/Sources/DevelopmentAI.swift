#if DEBUG
import Foundation

/// 개발자 Mac의 HTTP만 호출한다. Release에는 설정 코드를 포함하지 않는다.
enum DevelopmentAI {
    static func configured(defaults: UserDefaults = .standard) -> (any ActionSuggestionProvider)? {
        guard let address = defaults.string(forKey: "development_ai_url") else { return nil }
        guard let url = URL(string: address) else { return UnavailableSuggestionProvider() }
        return HTTPActionSuggestionProvider.development(baseURL: url, token: defaults.string(forKey: "development_ai_token"))
    }
}
#endif
