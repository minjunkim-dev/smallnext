import Foundation

public struct HealthResponse: Decodable, Sendable {
    public let status: String
}

public struct APIClient: Sendable {
    public let baseURL: URL

    public func health() async throws -> HealthResponse {
        let (data, response) = try await URLSession.shared.data(
            from: baseURL.appendingPathComponent("health")
        )
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(HealthResponse.self, from: data)
    }
}
