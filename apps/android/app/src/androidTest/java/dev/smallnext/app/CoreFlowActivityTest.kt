package dev.smallnext.app

import android.content.Intent
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** 실제 MainActivity에서 플래그 OFF 기존 화면과 Debug 인텐트 extra로 켠 ON 핵심 경로를 확인한다. */
@RunWith(AndroidJUnit4::class)
class CoreFlowActivityTest {
    @get:Rule
    val compose = createEmptyComposeRule()

    private val app = ApplicationProvider.getApplicationContext<SmallnextApplication>()

    private fun launch(coreFlow: Boolean? = null) = ActivityScenario.launch<MainActivity>(
        Intent(app, MainActivity::class.java).apply { coreFlow?.let { putExtra(FeatureFlags.CORE_FLOW, it) } },
    )

    // CI 에뮬레이터(320x640dp)는 입력 뒤 소프트 키보드가 남아 본문 버튼을 가린다. 본문 버튼은 화면 안으로 스크롤한 뒤 누른다.
    private fun waitFor(text: String) = compose.waitUntil(10_000) { compose.onAllNodes(hasText(text)).fetchSemanticsNodes().size == 1 }

    @Test
    fun flagOffKeepsExistingStartScreen() {
        launch().use {
            compose.onNodeWithText("작은 다음 행동을 준비하고 있어요.").assertIsDisplayed()
            compose.onNodeWithText("목표를 한 문장으로 적어 주세요.").assertDoesNotExist()
        }
    }

    @Test
    fun debugLaunchExtraRunsCorePathWithDebugProviderAndSurvivesRecreation() {
        // 앞선 실행이 남긴 진행 기록을 비운다. 진행 흐름은 이 테스트에서 처음 연다.
        app.database.openHelper.writableDatabase.apply {
            execSQL("DELETE FROM goal")
            execSQL("DELETE FROM app_metadata WHERE `key` = 'selected_goal_id' OR `key` LIKE 'goal_input%'")
        }
        launch(coreFlow = true).use { scenario ->
            waitFor("목표를 한 문장으로 적어 주세요.")
            compose.onNode(hasSetTextAction()).performTextInput("이력서 정리하기")
            compose.onNodeWithText("목표 정리").performScrollTo().performClick()
            waitFor("확인하고 시작")
            compose.onNodeWithText("확인하고 시작").performScrollTo().performClick()
            waitFor("이력서 파일 하나 열기")
            compose.onNodeWithText("약 3분 · 예상").assertIsDisplayed()
            compose.onNodeWithText("완료").performClick()
            waitFor("최근 경력 한 항목의 기간 확인하기")

            scenario.recreate()
            waitFor("최근 경력 한 항목의 기간 확인하기")
        }
    }
}
