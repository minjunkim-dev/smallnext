import Foundation
import SmallnextCore
import SwiftUI

/// 서버 AI로 목표·자료를 보내기 전의 명시 동의다(App Review 5.1.2(i)).
enum AIConsent {
    static let key = "ai_transfer_consent"

    static func privacyPolicyURL(info: [String: Any] = Bundle.main.infoDictionary ?? [:]) -> URL? {
        guard let value = info["SmallnextPrivacyPolicyURL"] as? String, !value.contains("$("),
              let url = URL(string: value), url.scheme?.lowercased() == "https",
              !(url.host ?? "").isEmpty, url.user == nil, url.password == nil else { return nil }
        return url
    }
}

/// 동의가 없으면 서버로 보내지 않는다. 화면 게이트와 별개로 요청마다 다시 확인한다.
struct ConsentGatedProvider: ActionSuggestionProvider {
    let base: any ActionSuggestionProvider

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        guard UserDefaults.standard.bool(forKey: AIConsent.key) else { throw SuggestionFailure.unavailable }
        return try await base.suggest(request)
    }
}

struct AIConsentView: View {
    let agree: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("AI 제안 전송 동의").font(.title2.bold()).accessibilityAddTraits(.isHeader)
                Text("작은 행동을 제안하려면 입력한 목표, 완료 조건, 자료 링크·발췌, 행동 기록과 답을 Smallnext 서버를 거쳐 Anthropic(Claude)으로 보냅니다.")
                Text("요청에는 익명 계정이 함께 쓰입니다. 이름이나 연락처는 묻지 않습니다.")
                Text("동의하지 않으면 AI 요청을 보내지 않습니다. 목표 목록에서 언제든 동의를 철회할 수 있습니다.")
                if let url = AIConsent.privacyPolicyURL() {
                    Link("개인정보 처리방침", destination: url)
                        .frame(minHeight: 44)
                }
                Button("동의하고 계속", action: agree)
                    .buttonStyle(.borderedProminent)
                    .frame(minHeight: 44)
                    .accessibilityHint("목표와 자료를 Anthropic으로 보내는 데 동의합니다.")
            }
            .padding(24)
            .frame(maxWidth: 560, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemGroupedBackground))
    }
}
