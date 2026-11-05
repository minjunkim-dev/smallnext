<!--
PR 본문 양식. 헤더 이름(## Summary, ## Evidence, ## Merge Danger)과 Door, Author는 그대로 둔다.
작성 기록은 아래 Author 줄이거나, 같은 내용의 두 줄이다.
  작성 도구: Claude Code | Cursor | Cursor 클라우드 에이전트 | 사람
  작성 모델: 도구가 보여주는 모델 이름. 사람은 `없음`.
tool과 모델이 둘 다 있어야 한다. 이전 도구가 있으면 이전 작성 모델: 에 이름을 쉼표로 적는다.
축 이름은 Standards, Spec, 버그 찾기, Security다. 버그 찾기와 Security를 돌리지 않으면 모델은 `해당 없음: <이유>`이고 P0·P1·P2는 0이다.
리뷰를 시작하지 못한 축은 모델·effort·P0·P1·P2에 미실행이라고 적는다. 미실행은 0이 아니다.
head SHA는 이 표를 쓸 때의 PR head 전체 40자다. 리뷰 모델의 패밀리가 최종 작성 모델 또는 이전 작성 모델의 패밀리와 같으면 안 된다. 패밀리는 `docs/development-workflow.md` 역할 분담이다. CI 별칭은 Claude(Opus, Sonnet), Grok, Composer, Gemini, GPT다.
-->

Author: <tool> / <model>

## Summary

왜 바꾸는지, 바꾸기 전과 후.

## Evidence

실행한 명령, 결과, head SHA, 확인하지 않은 범위.

## Merge Danger

<!-- 되돌리기 어려움(one-way door: 되돌리기 어려운 결정), 되돌리기 쉬움(two-way door: 되돌리기 쉬운 결정). Door 값은 그 둘만. 필드 이름은 Door:다. POLICY.md §10으로 판정한다. 옛 `양쪽 문`·`한쪽 문`은 deprecated이고 검사기가 아직 받는다. -->

Door: <되돌리기 쉬움 또는 되돌리기 어려움>

영향 범위:

복구:

신뢰 경계 기준: <없음, 또는 걸린 POLICY.md §5 기준>

## Review evidence

| axis | model | effort | head SHA | P0 | P1 | P2 | result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Standards |  |  |  |  |  |  |  |
| Spec |  |  |  |  |  |  |  |
| 버그 찾기 |  |  |  |  |  |  |  |
| Security |  |  |  |  |  |  |  |
