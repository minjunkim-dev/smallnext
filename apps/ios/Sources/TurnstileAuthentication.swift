import Foundation
import Observation
import SmallnextCore
import SwiftUI
import WebKit

struct TurnstileConfiguration: Sendable, Equatable {
    let origin: URL
    let siteKey: String

    init(origin: URL, siteKey: String) throws {
        guard HTTPActionSuggestionProvider.endpoint(origin, schemes: ["https"]),
              siteKey.range(of: #"^[A-Za-z0-9_-]{1,256}$"#, options: .regularExpression) != nil
        else { throw SuggestionFailure.unavailable }
        var canonical = URLComponents(url: origin, resolvingAgainstBaseURL: false)!
        canonical.scheme = "https"
        canonical.host = origin.host!.lowercased()
        canonical.path = ""
        if canonical.port == 443 { canonical.port = nil }
        self.origin = canonical.url!
        self.siteKey = siteKey
    }

    static func load(info: [String: Any]) throws -> Self? {
        func value(_ key: String) -> String? {
            guard let value = info[key] as? String, !value.isEmpty, !value.contains("$(") else { return nil }
            return value
        }
        let address = value("SmallnextAuthCaptchaURL")
        let key = value("SmallnextTurnstileSiteKey")
        guard address != nil || key != nil else { return nil }
        guard let address, let origin = URL(string: address), let key else { throw SuggestionFailure.unavailable }
        return try Self(origin: origin, siteKey: key)
    }

    func pageURL(nonce: UUID) -> URL {
        var url = URLComponents(url: origin.appendingPathComponent("auth/captcha/"), resolvingAgainstBaseURL: false)!
        url.queryItems = [URLQueryItem(name: "sitekey", value: siteKey), URLQueryItem(name: "nonce", value: nonce.uuidString.lowercased())]
        return url.url!
    }

    func sameOrigin(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.host?.lowercased() == origin.host
            && (url.port ?? 443) == (origin.port ?? 443) && url.user == nil && url.password == nil
    }

    func messageToken(body: Any, frameURL: URL?, securityOrigin: URL?, mainFrame: Bool, nonce: UUID) throws -> String {
        guard mainFrame, let frameURL, let securityOrigin,
              sameOrigin(frameURL), sameOrigin(securityOrigin),
              frameURL == pageURL(nonce: nonce),
              let message = body as? [String: String], message["origin"] == origin.absoluteString,
              message["nonce"] == nonce.uuidString.lowercased(),
              message["type"] == "success", let token = message["token"],
              !token.isEmpty, token.utf8.count <= 4096,
              !token.contains(where: { $0.isWhitespace }) else { throw SuggestionFailure.unavailable }
        return token
    }
}

@Observable @MainActor
final class TurnstileChallenge {
    static let shared = TurnstileChallenge()
    struct Request: Identifiable {
        let id: UUID
        let configuration: TurnstileConfiguration
    }
    private(set) var request: Request?
    @ObservationIgnored private var continuation: CheckedContinuation<String, any Error>?
    @ObservationIgnored private var timeoutTask: Task<Void, Never>?

    func token(configuration: TurnstileConfiguration, timeout: Duration = .seconds(120)) async throws -> String {
        try Task.checkCancellation()
        guard continuation == nil else { throw SuggestionFailure.unavailable }
        let id = UUID()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
                request = Request(id: id, configuration: configuration)
                timeoutTask = Task {
                    do { try await Task.sleep(for: timeout) }
                    catch { return }
                    self.finish(id: id, result: .failure(SuggestionFailure.unavailable))
                }
                if Task.isCancelled { finish(id: id, result: .failure(CancellationError())) }
            }
        } onCancel: {
            Task { @MainActor in self.finish(id: id, result: .failure(CancellationError())) }
        }
    }

    func finish(id: UUID, result: Result<String, any Error>) {
        guard request?.id == id, let continuation else { return }
        self.continuation = nil
        timeoutTask?.cancel()
        timeoutTask = nil
        request = nil
        continuation.resume(with: result)
    }
}

struct TurnstileSheet: View {
    let request: TurnstileChallenge.Request
    let challenge: TurnstileChallenge

    var body: some View {
        NavigationStack {
            TurnstileWebView(request: request) { challenge.finish(id: request.id, result: $0) }
                .navigationTitle("익명 로그인 확인")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("취소") { challenge.finish(id: request.id, result: .failure(CancellationError())) }
                            .accessibilityHint("로그인 확인을 중단합니다.")
                    }
                }
        }
        .interactiveDismissDisabled()
        .onDisappear { challenge.finish(id: request.id, result: .failure(CancellationError())) }
    }
}

private struct TurnstileWebView: UIViewRepresentable {
    let request: TurnstileChallenge.Request
    let completion: @MainActor (Result<String, any Error>) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(request: request, completion: completion) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(context.coordinator, name: "turnstile")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.accessibilityLabel = "익명 로그인 확인"
        view.load(URLRequest(url: request.configuration.pageURL(nonce: request.id)))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.stopLoading()
        view.configuration.userContentController.removeScriptMessageHandler(forName: "turnstile")
        view.navigationDelegate = nil
    }

    @MainActor final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        let request: TurnstileChallenge.Request
        let completion: @MainActor (Result<String, any Error>) -> Void
        init(request: TurnstileChallenge.Request, completion: @escaping @MainActor (Result<String, any Error>) -> Void) {
            self.request = request
            self.completion = completion
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "turnstile" else { return }
            let origin = message.frameInfo.securityOrigin
            var components = URLComponents()
            components.scheme = origin.protocol
            components.host = origin.host
            if origin.port != 0 { components.port = origin.port }
            do {
                let token = try request.configuration.messageToken(
                    body: message.body, frameURL: message.frameInfo.request.url,
                    securityOrigin: components.url, mainFrame: message.frameInfo.isMainFrame, nonce: request.id
                )
                completion(.success(token))
            } catch { completion(.failure(SuggestionFailure.unavailable)) }
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let frame = action.targetFrame, let url = action.request.url else { decisionHandler(.cancel); return }
            if frame.isMainFrame {
                let allowed = url == request.configuration.pageURL(nonce: request.id) && action.request.httpMethod == "GET"
                if !allowed { completion(.failure(SuggestionFailure.unavailable)) }
                decisionHandler(allowed ? .allow : .cancel)
            } else {
                let allowed = (url.scheme == "https" && url.host == "challenges.cloudflare.com") || url.absoluteString == "about:blank"
                decisionHandler(allowed ? .allow : .cancel)
            }
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error) {
            completion(.failure(SuggestionFailure.unavailable))
        }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: any Error) {
            completion(.failure(SuggestionFailure.unavailable))
        }
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            completion(.failure(SuggestionFailure.unavailable))
        }
    }
}
