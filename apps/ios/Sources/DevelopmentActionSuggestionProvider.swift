#if DEBUG
import Foundation

/// 개발자 Mac의 HTTP만 호출한다. Release에는 공급자와 설정 코드를 포함하지 않는다.
struct DevelopmentActionSuggestionProvider: ActionSuggestionProvider {
    let baseURL: URL
    let token: String?
    var session: URLSession = .shared

    static func configured(defaults: UserDefaults = .standard) -> (any ActionSuggestionProvider)? {
        guard let address = defaults.string(forKey: "development_ai_url") else { return nil }
        guard let url = URL(string: address), ["http", "https"].contains(url.scheme),
              url.host != nil, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil,
              url.path.isEmpty || url.path == "/" else { return UnavailableSuggestionProvider() }
        return Self(baseURL: url, token: defaults.string(forKey: "development_ai_token"))
    }

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        let value = token
        return try await HTTPActionSuggestionProvider(baseURL: baseURL, path: "development/suggestions",
            token: { value }, session: session).suggest(request)
    }
}
#endif
