# 정보 근거와 유용한 결과의 역할 지침

2026-10-21, [#212](https://github.com/minjunkim-dev/smallnext/issues/212). 기준 소스는 `f6d3f8f7f928da1acb326489c8c4e0f8f024eca7`이다.
공유 계약을 유지하고 생성·일반 검사 역할 지침을 함께 보완하도록 권장한다.

## 확인한 사실

[#211의 직접 승인](https://github.com/minjunkim-dev/smallnext/issues/211#issuecomment-6306801058)은 24건 중 19건 충족·3건 불확실·2건 거부이다.
자동 검사 70건의 `accept`와 이 판정은 다르다. 원본의 자동 판정을 보존한다.
029는 기준 2·4 거부이다. 평가 표시가 대상·근거 종류와 연결된 유용한 결과를 남기지 못했다.
069는 기준 3·4 거부이다. 필요한 과거 역할이 미확인인데 제공되지 않은 기억에 의존하게 했다. 구체적인 역할을 모델이 지어냈다고 확정하지 않는다.
009·010·011은 기준 2·4 불확실이다. 이를 위반으로 승격하거나 다른 기준을 통과로 채우지 않는다.
직접 승인은 에이전트 초안의 승인이다. 실제 수행이나 별도의 독립 품질 관측은 아니다. 시간도 추정이다.
이 조사는 기존 판정과 소스를 대조한 연구이다. 추가 사람 판정으로 세지 않는다.

## 소스와 도달 범위

동결 manifest의 contract·generate·check·compact·oauth_quality 소스 SHA는 조사 시작 시 기준 소스와 같았다.
[공유 계약](../../services/api/src/suggestion/contract.md#L3)은 제공한 사실만 사용하도록 한다. [정보 질문](../../services/api/src/suggestion/contract.md#L12), [유용한 작업](../../services/api/src/suggestion/contract.md#L18), [증거·제한](../../services/api/src/suggestion/contract.md#L20)도 이미 정한다.
기준 소스의 [생성 지침](https://github.com/minjunkim-dev/smallnext/blob/f6d3f8f7f928da1acb326489c8c4e0f8f024eca7/services/api/src/suggestion/generate.md#L3)은 사실 범위를 `smaller`에 강조한다. 069는 첫 행동이다. 필요한 과거 사실의 근거를 다른 행동에서도 대조하도록 명시할 여지가 있다.
기준 소스의 [생성 지침](https://github.com/minjunkim-dev/smallnext/blob/f6d3f8f7f928da1acb326489c8c4e0f8f024eca7/services/api/src/suggestion/generate.md#L5)은 표시와 대상의 연결을 강조한다. 기준 소스의 [일반 검사 지침](https://github.com/minjunkim-dev/smallnext/blob/f6d3f8f7f928da1acb326489c8c4e0f8f024eca7/services/api/src/suggestion/check.md#L3)에는 같은 구체적 대조가 없다. 공유 계약 자체가 빠진 것은 아니다.
[Rust instructions](../../services/api/src/suggestion/compact.rs#L291)와 [Python request](../../scripts/oauth_quality.py#L354)는 일반 검사에 check 역할 지침을 전달한다.
반면 `smaller`의 `need_info`는 [Rust question_prompt](../../services/api/src/suggestion/compact.rs#L316)와 [Python question_prompt](../../scripts/oauth_quality.py#L524)를 쓴다.
두 함수는 check prefix를 교체한다. 공유 계약 8문단은 보존하고 상태 문단에서 정보 질문에 필요한 행만 남긴다. 따라서 check.md 보완이 이 분기에도 전달된다고 보고하면 안 된다.
host의 문자 그대로인 보존 검증은 의미의 유용성을 증명하지 않는다. [Rust의 명시적 경계](../../services/api/src/suggestion/compact.rs#L311)를 유지한다.

## 가설과 권장 문구

1. **우선 후보:** 필요한 과거 사실과 제공되지 않은 사용자 지식의 구분을 생성·일반 검사 양쪽에서 더 직접 대조하면 069 유형의 위험을 다룰 수 있다. 모델 내부의 실제 원인으로 확정하지 않는다.
2. **우선 후보:** 표시가 생성됐다는 사실과 목표에 쓸 수 있는 결과의 보존을 구분하면 029 유형의 위험을 다룰 수 있다. 제안에서 대상을 언급한 사실만으로 분리된 표시를 복구했다고 보지 않는다.
3. **미확인:** 009·010·011의 실제 유용성·감소와 모델의 일반화는 입증하지 못했다. 형식·조작·제목·표시를 일괄 금지하는 근거로 쓰지 않는다.

생성 지침의 필요한 과거 사실 후보:
> For an action requiring an unknown past fact, do not assume unsupplied user memory or knowledge. Use supplied source material to verify it when available; otherwise ask for the missing fact with need_info.

생성 지침의 기존 연결 문장 보완 후보:
> Keep the target and meaning of each assessment or mark identifiable in its result or recording context. Naming the target only in the proposal does not repair an otherwise detached mark.

일반 검사 지침 후보:
> Check required unknown past facts against supplied information and source-based verification work; unsupplied user memory or knowledge is not evidence. Verify that an assessment or mark retains its target and meaning in the result or recording context, rather than only in the proposal. A reminder of later checking does not replace a useful result unless producing that reminder is itself a required goal result.

## 유지할 반례와 검증 경계

unknown이 있어도 현재 행동에 그 사실이 필요하지 않으면 질문을 강제하지 않는다. 제공된 자료를 찾아·열어·확인하는 정상 행동을 유지한다.
원문이나 대상명을 매번 다시 쓰게 하지 않는다. 식별된 기록 위치의 연결은 허용한다. 필수 글자·항목·선택 부담의 유용한 감소와 제목·표시 자체가 필요한 목표 결과인 경우도 유지한다.
19건 충족을 반례로 보존한다. 그중 038·056·064는 정상 `need_info`이며 실제 행동 감소로 세지 않는다. [행동 결과의 뜻](../../CONTEXT.md#용어)을 바꾸지 않는다.
검증은 공식 compact fixture의 generate·일반 check 전달과 check-question 보존을 구분한다. 전달 검사는 실제 AI 품질 개선의 증명이 아니다. 계약·schema·사례·하네스·모델을 바꾸지 않는다.
manifest SHA는 `d4fb85332f811c49b51b53ccc6b639fafa16f9f63fc6e7fd5dc5e5a8dab09903`, 승인 MD SHA는 `55a584421a461982ab369d0a38ae4f971b4c0d9dd55cfd4aa1c8c8db9c46b271`이다.
원문은 기존 private 묶음에만 둔다. 담당자는 minjunkim-dev이다. 삭제 상한 `2026-11-20 11:36:56 KST`를 연장하지 않는다. [보관·검증 경계](../WORKFLOW.md#검증과-문서-관리)를 따른다.
이 연구는 검사·모델·OAuth·유료 API를 실행하지 않았다. 실제 수행·화면·서버·실기기·출시 품질은 검증하지 않았다.
