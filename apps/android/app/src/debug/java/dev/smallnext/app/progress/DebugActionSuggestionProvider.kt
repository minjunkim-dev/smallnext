package dev.smallnext.app.progress

import kotlinx.coroutines.delay

/** iOS `DebugActionSuggestionProvider`와 같은 규칙과 예시 목표를 쓴다. Debug 빌드에만 있다. */
class DebugActionSuggestionProvider(private val delayMillis: Long = 400) : ActionSuggestionProvider {
    override suspend fun suggest(request: SuggestionRequest): SuggestionCandidate {
        delay(delayMillis)
        if (request.kind == SuggestionKind.GOAL_PREPARATION) {
            if (request.goal in listOf("정리하기", "준비하기", "공부하기") && request.context.currentState == null &&
                request.blocker == null && request.context.materialExcerpt == null && request.context.answers.isEmpty()
            ) {
                return SuggestionCandidate.Question("무엇을 하려는지 한 가지 알려 주세요.")
            }
            return SuggestionCandidate.GoalSummary("‘${request.goal}’을 마쳤다고 확인한다.")
        }
        // 대체: 대체 행동 하나를 돌려준다. 그 행동도 보류했으면 후보가 없다.
        if (request.kind == SuggestionKind.REPLACEMENT) {
            val replacement = step("목표에 대해 떠오르는 생각 한 줄 적기", "생각 한 줄이 남는다", 3).copy(
                targetName = "떠오른 생각",
                targetDescription = "지금 목표에 대해 떠오르는 생각을 적는 메모예요.",
            )
            val used = replacement.task in request.deferredTasks || replacement.task in request.completedTasks
            return if (used) SuggestionCandidate.NoAction else SuggestionCandidate.Action(replacement)
        }
        // 더 작게: 이미 나눈 행동을 막힘 원인 없이 다시 나누면 확인 질문을 돌려준다.
        val current = request.currentAction
        if (request.kind == SuggestionKind.SMALLER && current != null) {
            if (request.blocker == null && request.splitSources.isNotEmpty()) {
                return SuggestionCandidate.Question("가장 먼저 막히는 지점은 무엇인가요?")
            }
            return SuggestionCandidate.Action(
                step(SMALLER_PREFIX + current.task, "첫 부분 하나를 끝낸다", maxOf(1, current.estimatedMinutes / 2)),
            )
        }
        val count = request.completedTasks.size
        val example = examples.firstOrNull { it.goal == request.goal }
        val steps = example?.steps ?: general
        val action = if (count < steps.size) steps[count] else continued(count)
        return SuggestionCandidate.Action(
            action.copy(
                targetName = example?.target ?: "선택한 자료",
                targetDescription = example?.description ?: "앞에서 고른 한 자료로 이어서 진행해요.",
            ),
        )
    }

    private class Example(val goal: String, val target: String, val description: String, val steps: List<ProposedAction>)

    companion object {
        private const val SMALLER_PREFIX = "첫 부분만: "

        private fun step(task: String, doneWhen: String, minutes: Int) = ProposedAction(task, doneWhen, minutes)

        private fun continued(count: Int) = step("다음 한 가지 고르기 ($count)", "다음 한 가지가 한 줄로 남는다", 5)

        private val general = listOf(
            step("목표와 관련된 첫 자료 하나 열기", "자료가 화면에 열린다", 3),
            step("연 자료에서 지금 할 한 가지를 고르기", "고른 한 가지가 한 줄로 남는다", 5),
            step("고른 한 가지를 짧게 실행하기", "실행을 마친다", 10),
            step("실행한 결과를 한 줄로 남기기", "결과 한 줄이 남는다", 5),
        )

        private val examples = listOf(
            Example(
                "이력서 정리하기", "이력서", "지금 고른 이력서 파일 하나를 정리해요.",
                listOf(
                    step("이력서 파일 하나 열기", "파일이 화면에 보인다", 3),
                    step("최근 경력 한 항목의 기간 확인하기", "기간을 확인했다", 5),
                    step("그 경력 설명에서 한 문장 고치기", "고친 문장이 남는다", 12),
                    step("고친 이력서 저장하기", "저장이 끝난다", 2),
                ),
            ),
            Example(
                "분기 업무 보고서 초안 쓰기", "업무 보고서", "지금 고른 업무 보고서 문서에 초안을 남겨요.",
                listOf(
                    step("업무 보고서 문서 하나 열기", "문서가 화면에 보인다", 3),
                    step("이번 분기에 끝낸 업무 하나 적기", "업무 이름이 한 줄 남는다", 8),
                    step("그 업무의 결과를 한 문장으로 적기", "결과 문장이 한 줄 남는다", 10),
                    step("적은 문장을 문서에 저장하기", "저장이 끝난다", 2),
                ),
            ),
            Example(
                "통계 기초 단원 하나 학습하기", "학습 단원", "지금 연 학습 자료의 한 단원으로 이어서 진행해요.",
                listOf(
                    step("학습 자료에서 다음 단원 열기", "단원이 화면에 보인다", 3),
                    step("그 단원의 첫 소제목 읽기", "소제목을 읽었다", 8),
                    step("기억할 한 문장 적기", "문장 한 줄이 남는다", 10),
                    step("그 문장을 다시 볼 곳에 두기", "문장이 그 위치에 있다", 4),
                ),
            ),
            Example(
                "개인 프로젝트로 베란다 화분 옮겨 심기", "화분", "앞에서 정한 화분 하나를 새 자리로 옮겨요.",
                listOf(
                    step("옮길 화분 하나 정하기", "화분 하나가 정해진다", 3),
                    step("새 자리와 흙이 있는지 확인하기", "자리와 흙의 유무를 확인했다", 5),
                    step("화분을 새 자리로 옮기기", "화분이 새 자리에 있다", 12),
                    step("옮긴 뒤 상태를 한 줄로 남기기", "상태 한 줄이 남는다", 4),
                ),
            ),
        )

        val exampleGoals: List<String> = examples.map { it.goal }
    }
}

/** `android_server_ai`가 꺼진 Debug 빌드의 공급자다. 서버 공급자 연결은 #358에서 한다. */
fun defaultSuggestionProvider(): ActionSuggestionProvider = DebugActionSuggestionProvider()
