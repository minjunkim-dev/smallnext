import SwiftUI
import SmallnextCore

/// 외부 시뮬레이터 관측용 표식이다. 상태 콜백을 화면 관측으로 기록하지 않는다.
struct SuggestionTimingMarker: ViewModifier {
    let sample: SuggestionTiming?
    @ViewBuilder func body(content: Content) -> some View {
        #if DEBUG
        if let sample {
            content.accessibilityElement(children: .contain)
                .accessibilityIdentifier("timing:\(sample.id):\(sample.kind.rawValue):\(sample.outcome)")
        } else { content }
        #else
        content
        #endif
    }
}
