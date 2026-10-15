#if DEBUG
import Foundation

// Shared with the app-hosted tests through project.yml.
final class DevelopmentTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var request = request
        if request.httpBody == nil, let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }
                data.append(contentsOf: buffer.prefix(count))
            }
            request.httpBody = data
        }
        let handler = Self.store.record(request)
        guard let handler else { return }
        do {
            let (code, data) = try handler(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() { Self.store.stop() }

    final class Store: @unchecked Sendable {
        typealias Handler = (URLRequest) throws -> (Int, Data)
        private let lock = NSLock()
        private var handlerValue: Handler?
        private var requestValues: [URLRequest] = []
        private var stoppedValue = false
        var handler: Handler? {
            get { lock.withLock { handlerValue } }
            set { lock.withLock { handlerValue = newValue } }
        }
        var requests: [URLRequest] { lock.withLock { requestValues } }
        var stopped: Bool { lock.withLock { stoppedValue } }
        func reset() { lock.withLock { handlerValue = nil; requestValues = []; stoppedValue = false } }
        func record(_ request: URLRequest) -> Handler? { lock.withLock { requestValues.append(request); return handlerValue } }
        func stop() { lock.withLock { stoppedValue = true } }
    }
}
#endif
