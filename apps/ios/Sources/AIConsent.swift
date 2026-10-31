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
    /// 동의 없이도 기기의 목표와 기록을 지울 수 있게 한다.
    let deleteLocalData: () throws -> Void
    let hasLocalData: Bool
    @State private var confirmingDeletion = false
    @State private var deletionMessage: String?
    @AccessibilityFocusState private var deletionMessageFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("AI 제안 전송 동의").font(.title2.bold()).accessibilityAddTraits(.isHeader)
                Text("작은 행동을 제안하려면 입력한 목표, 완료 조건, 자료 링크·발췌, 행동 기록과 답을 Smallnext 서버를 거쳐 Anthropic(Claude)으로 보냅니다.")
                Text("요청에는 익명 계정이 함께 쓰입니다. 이름이나 연락처는 묻지 않습니다.")
                Text("모든 행동 제안에 AI를 쓰므로 동의해야 시작할 수 있습니다. 동의 전에는 AI로 아무것도 보내지 않습니다. 목표 목록에서 언제든 동의를 철회할 수 있습니다.")
                if let url = AIConsent.privacyPolicyURL() {
                    Link(destination: url) {
                        Text("개인정보 처리방침").frame(minHeight: 44).contentShape(Rectangle())
                    }
                }
                Button("동의하고 계속", action: agree)
                    .buttonStyle(.borderedProminent)
                    .modifier(OnAccentLabel())
                    .controlSize(.large)
                    .accessibilityHint("목표와 자료를 Anthropic으로 보내는 데 동의합니다.")
                if hasLocalData {
                    Button("이 기기의 목표와 기록 삭제", role: .destructive) { confirmingDeletion = true }
                        .frame(minHeight: 44)
                }
                if let deletionMessage {
                    Text(deletionMessage)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityFocused($deletionMessageFocused)
                }
            }
            .padding(24)
            .frame(maxWidth: 560, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemGroupedBackground))
        .safeAreaInset(edge: .top, spacing: 0) {
            Color.clear.frame(height: 0).background(Color(.systemGroupedBackground))
        }
        .tint(.smallnextAccent)
        .alert("이 기기의 목표와 기록을 삭제할까요?", isPresented: $confirmingDeletion) {
            Button("삭제", role: .destructive) {
                deletionMessageFocused = false
                do {
                    try deleteLocalData()
                    deletionMessage = "이 기기의 목표와 기록을 삭제했어요."
                } catch {
                    deletionMessage = "삭제하지 못했어요. 다시 시도해 주세요."
                }
                // 알림이 닫히는 동안의 안내는 VoiceOver가 놓칠 수 있어 결과 문구로 초점을 옮긴다.
                DispatchQueue.main.async { deletionMessageFocused = true }
            }
            Button("취소", role: .cancel) { }
        } message: {
            Text("모든 목표의 행동·결과·입력·완료 기록과 작성 중인 목표를 지워요. 삭제 후에는 복구할 수 없어요. 서버의 익명 계정은 지워지지 않아요.")
        }
    }
}
