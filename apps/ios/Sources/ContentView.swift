import SwiftUI

struct ContentView: View {
    var storageFailed = false

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "arrow.right.circle")
                .font(.system(size: 48))
                .foregroundStyle(.tint)
                .accessibilityHidden(true)
            Text("Smallnext")
                .font(.largeTitle.bold())
            Text(storageFailed
                 ? "저장 공간을 열 수 없습니다. 앱을 다시 실행해 주세요."
                 : "작은 다음 행동을 준비하고 있어요.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
    }
}

#Preview {
    ContentView()
}
