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

## #215 후속: 축소 후에도 남는 확인 결과

2026-10-21, [#215](https://github.com/minjunkim-dev/smallnext/issues/215). 비교 기준 소스는 `8a4af7693937ce5ecf204a9835f0bf6eaccf9db8`이다. 앞의 #212 연구와 #211 판정은 보존한다.
[#214의 직접 승인](https://github.com/minjunkim-dev/smallnext/issues/214#issuecomment-6308047209)은 000·001·002 충족과 010의 기준 2·4 거부이다. 010의 기준 1은 미확인이다. 자동 거부의 기준 1·2·4와 사람 판정을 구분한다.
000·001은 제공된 원고에서 역할 문장의 존재 또는 근거 부족을 확인하고 결과 대상을 남기는 정상 경로이다. 002는 유용한 최소 이후의 첫 막힘 질문이다. 009는 직전 비교 자료이며 별도 사람 통과로 세지 않는다.
010은 직전 제안의 사실 확인 작업을 제거하고 경험 참조 문구만 남겼다. 이 사실은 승인된 실패의 요약이다. 원문을 새로 읽거나 별도 사람 판정을 수행한 결과가 아니다. 실제 수행 시간도 추정이다.

기준 소스의 [생성 지침 3행](https://github.com/minjunkim-dev/smallnext/blob/8a4af7693937ce5ecf204a9835f0bf6eaccf9db8/services/api/src/suggestion/generate.md#L3)은 직전 필수 작업과 필요한 확인 작업을 이미 비교하게 한다. [5행](https://github.com/minjunkim-dev/smallnext/blob/8a4af7693937ce5ecf204a9835f0bf6eaccf9db8/services/api/src/suggestion/generate.md#L5)은 미확인 과거 사실의 출처를 요구한다. [7행](https://github.com/minjunkim-dev/smallnext/blob/8a4af7693937ce5ecf204a9835f0bf6eaccf9db8/services/api/src/suggestion/generate.md#L7)은 결과의 대상·의미와 유용함을 요구한다.
그런데 알아볼 수 있는 참조가 남았다는 사실만으로 직전 확인 작업의 유용한 결과까지 남는 것은 아니다. 비교할 대상은 수행할 경우 얻게 될 정보·확인 결과이다. 직전 제안을 이미 수행했다고 가정하지 않는다. [공유 계약 3행](../../services/api/src/suggestion/contract.md#L3), [18행](../../services/api/src/suggestion/contract.md#L18), [20행](../../services/api/src/suggestion/contract.md#L20), [기준 2·4](../../services/api/src/suggestion/contract.md#L24)가 이 구분의 기준이다.
**가설:** 대상 식별을 보존하는 축소에서 정보 진전까지 보존되는지를 더 직접 비교하면 이번 위험을 다룰 수 있다. 기존 규칙이 없었다거나 모델이 이를 특정 방식으로 해석했다고 확정하지 않는다. 모델 내부 원인은 미확인이다.

생성 지침 7행의 첫 문장 뒤에 다음 두 문장을 보완하도록 권장한다. 나머지 예외와 문맥 규칙은 유지한다.

> For smaller, compare the useful information, verification result or other goal result the latest proposal and the reduced action would each leave. Removing required finding, reading or checking and leaving only its subject does not preserve that work's useful result.

`finding, reading or checking`을 선택한 이유는 원고 내용을 찾아 읽고 얻는 진전도 비교에 포함하기 위해서다. 별도 검증 절차가 있었는지만으로 유용함을 판정하지 않는다. 알려진 참조만 남기는 것과 원고에서 새로운 정보를 얻는 작업을 구분한다.

이 후보는 확인 작업 전체나 확인 결과 원문의 복사를 요구하지 않는다. 제공된 자료에서 한 부분만 확인하거나 근거 부족을 확인하는 유용한 결과도 허용한다. 식별 가능한 기록 위치의 문맥을 다시 쓰게 하지 않는다.
제목·표시 자체가 필요한 목표 결과인 기존 예외를 유지한다. 유용한 글자·항목·선택 부담 감소와 정상 `minimum`·`need_info`도 유지한다. 000·001·002 및 #211의 정상 정보 질문은 이 경계를 확인할 반례이다.
검사기는 이번 후보를 이미 거부했다. [기준 소스의 일반 검사 지침](https://github.com/minjunkim-dev/smallnext/blob/8a4af7693937ce5ecf204a9835f0bf6eaccf9db8/services/api/src/suggestion/check.md#L5)을 변경하지 않는다. 공유 계약·schema·기존 사례·하네스·모델도 유지한다.
생성 역할 전달은 [Rust](../../services/api/src/suggestion/compact.rs#L291)와 [Python](../../scripts/oauth_quality.py#L354)의 기존 경계를 쓴다. 공식 compact fixture에서는 generate만 갱신한다. 전달 검증과 실제 의미 품질 개선을 구분한다. check·check-unpreserved·check-question 보존도 확인한다.

보관 식별자는 승인 MD SHA `2458e5962513a6d700c081c869adad19169bcb2002f29d526e5d4e7fd7d82dda`, 판정 JSON SHA `a2123e4d325a2b70662708df5f0984900ea2fe200f6987ae94816440a59282c7`이다. 담당자는 minjunkim-dev이다. #214 삭제 상한 `2026-11-20 13:03:00.271319 KST`를 연장하지 않는다.
이 후속 연구는 검사·모델·OAuth·유료 API를 실행하지 않았다. 추가 사례·문자열 기반 의미 검사·반복 재시도·구조 변경은 제안하지 않는다. 후속 실제 평가는 별도 범위 기록 뒤에 판단한다. 실제 수행·품질 개선·화면·서버·실기기·출시는 검증하지 않았다.

## #218 후속: 자료 작업의 범위와 질문 판정 근거

2026-10-21, [#218](https://github.com/minjunkim-dev/smallnext/issues/218). 비교 기준 소스는 `8430a00aa6245d03877e378a93aa9986dce84670`이다. 앞의 #212·#215 연구와 판정을 보존한다.
[#217의 직접 승인](https://github.com/minjunkim-dev/smallnext/issues/217#issuecomment-6308711977)은 001 충족·000 기준 3 불확실·002/011 기준 4 불확실이다. 다른 미확인 칸을 통과로 채우지 않는다. 자동 `accept` 11건과 `reject` 1건 및 011의 자동 기준 4 거부도 보존한다.
000은 전체 복사량을 알 수 없어 시간 적합성을 입증하지 못했다. 실제 분량 초과를 확인한 것은 아니다. 002·011은 유용한 추가 축소와 유용한 최소 도달을 모두 입증하지 못했다. 두 기록 항목이나 반복 실패 부재만으로 어느 결론도 확정하지 않는다.
직접 승인은 기존 초안의 승인이다. 수행 시간은 추정이다. 이 조사는 공개 승인 요약과 소스를 대조한 연구이다. private 원문을 읽거나 새로운 사람 판정·실제 품질 관측을 수행하지 않았다.

### 기존 기준과 도달 범위

[공유 계약 3행](../../services/api/src/suggestion/contract.md#L3)은 제공한 사실의 범위를 정한다. [20행](../../services/api/src/suggestion/contract.md#L20)과 [기준 3](../../services/api/src/suggestion/contract.md#L25)은 필수 준비·복사·작성 등을 모두 제약에 포함한다. 알 수 없는 자료 분량이 짧은 추정 시간에 맞는다고 가정하지 않는 보완은 기존 기준의 강조이다.
[계약 12~15행](../../services/api/src/suggestion/contract.md#L12)은 정보 질문과 유용한 최소의 경계를 정한다. 최소 이후 첫 막힘 질문에는 반복 실패 보고가 필수가 아니다. [18행](../../services/api/src/suggestion/contract.md#L18)은 유용함을 보존한 글자·항목·선택 부담 감소를 허용한다. 항목 수는 이 유용함을 대신 증명하지 않는다.
기준 소스의 [generate 3행](https://github.com/minjunkim-dev/smallnext/blob/8430a00aa6245d03877e378a93aa9986dce84670/services/api/src/suggestion/generate.md#L3)과 [7행](https://github.com/minjunkim-dev/smallnext/blob/8430a00aa6245d03877e378a93aa9986dce84670/services/api/src/suggestion/generate.md#L7)은 필요한 자료 확인과 축소 후 결과를 이미 다룬다. 전체 작업량의 미확인과 유용한 일부 작업의 가능성을 더 직접 구분하는 것이 이번 후보이다. 지침 누락이나 모델 내부 원인으로 확정하지 않는다.
[Rust instructions](../../services/api/src/suggestion/compact.rs#L291)는 `smaller/need_info` 검사에서 [question_prompt](../../services/api/src/suggestion/compact.rs#L316)로 check prefix를 교체한다. [Python question_prompt](../../scripts/oauth_quality.py#L524)도 같은 투영을 한다. 따라서 일반 check.md 수정으로 이 경로의 강조를 전달할 수 없다. 기존 공유 계약 투영은 유지하고 양쪽 question prefix에 같은 문구를 넣는다.

### 선택한 문구와 반례

생성 지침 후보를 다음 세 문장으로 선택한다.

> For source work, bound the required finding, reading, copying and checking to the supplied constraints. Do not assume an unknown total amount fits a short estimate. A useful supported partial action may still be possible without asking about total length.

Rust/Python question_prompt의 후보를 다음 세 문장으로 선택한다.

> Item count alone establishes neither useful further reduction nor the useful minimum; compare required work, useful results and supplied recording context. Absence of repeated failure alone does not invalidate a first-impediment question. If decisive evidence for the stopping route is missing, return uncertain.

후보의 reason은 계속 독립 증거가 아니다. 근거가 없는 추가 축소를 만들어 질문을 거부하지 않는다. 반대로 항목이 하나라는 사실만으로 최소나 질문의 적합성을 수용하지 않는다. 다른 기준의 입증된 실패는 기존 거부 규칙을 따른다. 이번 보완은 근거가 부족한 질문 경로를 통과시키는 규칙이 아니다.
총분량을 몰라도 제약에 맞는 유용한 일부 확인이 뒷받침되면 행동을 허용한다. 분량 확인 질문을 일괄 강제하지 않는다. 제공된 기록 문맥·제목 자체가 필요한 목표 결과·유용한 글자/항목/선택 부담 감소·정상 `minimum/need_info`·적격성과 보류를 유지한다.
검증은 generate와 check-question의 전달 변경 및 Rust/Python 일치를 확인한다. 일반 check·check-unpreserved·공유 계약·schema·12사례·참조·상한은 유지한다. 전달 검증은 실제 의미 품질 개선의 증명이 아니다. 새로운 문자열 의미 검사·모의 통과 사례·반복 재시도를 추가하지 않는다.
최초 전체 검사와 PR #219의 Repository 검사에서 재판정 명령 회귀 4건이 실패했다. 질문 prefix가 바뀌어 동결 실행기 SHA가 새 값이 됐지만, [재판정 도구](../../scripts/rejudge_oauth_quality.py#L12)의 검토한 실행기 목록에는 이전 SHA만 있었다. 미확인 실행기를 `unknown`으로 남기는 보호는 정상 동작했다. 이 실패는 실제 과거 원문을 재판정한 결과가 아니다.
이전 실행기 SHA `1799cb2c4ef7c5cddd58f2a275cdad37750bae8b45d26286f21fcfd69d18afe2`와 새 SHA `1e2d25eb61b3c52ef34fe1f54f1e1ebc73c9e938108da58f8768bedaa5d6ddff`의 차이는 위 질문 지침 세 문장뿐이다. 취소 표식·종료 기록·회수·오류 판정 코드는 그대로다. 새 SHA를 같은 `cancellation-marker-v1`로 명시 등록하고 별도 Security 리뷰로 이 바이트 비교를 확인한다. 기존 두 SHA와 미등록 SHA의 불확실 처리는 유지한다. 현재 실행기를 자동 신뢰하는 규칙이나 해시 검사를 우회하는 규칙을 추가하지 않는다. 기존 명령 경계의 정상·미확인·취소·원본 보존 회귀를 그대로 재사용한다. 실행기 바이트 변경 시 이 목록의 검토 필요성도 함께 확인한다.
보관 식별자는 #217 승인 MD SHA `e042aa2b3fe188a3b36e990077f42b643a2010a49818e4d54d2289bb5eac70ff`, 판정 JSON SHA `30dac0248eca71fedc30d1ba6c83c8d67b04047857ccdad482d4ca8e8487e584`이다. 담당자 minjunkim-dev와 삭제 상한 `2026-11-20T14:01:44.609418+09:00`을 유지한다.
이 후속 연구에서는 검사·모델·OAuth·유료 API를 실행하지 않았다. 기존 불확실을 실제 분량 초과나 검사 오류로 바꾸지 않는다. 실제 수행·품질 개선·화면·서버·실기기·출시는 검증하지 않았다.

## #221 후속: 유용한 일부 단위와 선택 규칙의 결과

2026-10-21, [#221](https://github.com/minjunkim-dev/smallnext/issues/221). 비교 기준 소스는 `0e372bdee6c511a8852b87caf8e5f0800b8f017a`이다. 앞의 107행과 기존 판정은 보존한다.
[#220의 직접 승인](https://github.com/minjunkim-dev/smallnext/issues/220#issuecomment-6309806394)은 001·002 충족·000 기준 3 불확실·011 기준 2·4 불확실이다. 자동 `accept` 11건과 `reject` 1건 및 011의 자동 기준 4 거부는 보존한다. 다른 미확인 칸을 통과로 채우지 않는다.
000은 요구한 역할·기여 문장 전체의 분량을 알 수 없다. 011은 선택을 단순화했지만 실제 원고에서 고르는 단위의 역할 관련성과 유용한 결과 보존을 입증하지 못했다. 같은 위치·동작·개수·시간만으로 감소를 부정할 수도 없다. 후보 reason만으로 감소를 입증할 수도 없다.
실제 분량 초과·무관한 동사·감소 실패를 확인한 것은 아니다. 011의 영어 근거와 복사된 reason은 한국어 지침과 다른 출력의 관측이다. 이를 새 사람 품질 실패 기준으로 바꾸지 않는다. 직접 승인은 기존 초안의 승인이고 수행 시간은 추정이다. 이 연구는 추가 사람 판정이나 실제 품질 관측이 아니다.

### 기준과 도달 범위

[공유 계약 18행](../../services/api/src/suggestion/contract.md#L18)은 유용한 단위를 보존한 수량·선택 부담 감소를 허용한다. [20행](../../services/api/src/suggestion/contract.md#L20)과 [기준 3](../../services/api/src/suggestion/contract.md#L25)은 필수 작업 전체를 제약에 포함한다. 따라서 범위가 정해진 유용한 일부와 미확인 전체량의 구분은 기존 기준의 강조이다.
기준 소스의 [generate 5행](https://github.com/minjunkim-dev/smallnext/blob/0e372bdee6c511a8852b87caf8e5f0800b8f017a/services/api/src/suggestion/generate.md#L5)은 자료 작업의 범위를 이미 다룬다. [7행](https://github.com/minjunkim-dev/smallnext/blob/0e372bdee6c511a8852b87caf8e5f0800b8f017a/services/api/src/suggestion/generate.md#L7)은 축소 후 유용한 결과를 요구한다. 일부 단위의 명시와 선택 규칙의 목표 관련성을 더 직접 대조하는 후보를 선택한다. 지침 누락이나 모델 내부 원인으로 확정하지 않는다.
기준 소스의 [일반 check 3행](https://github.com/minjunkim-dev/smallnext/blob/0e372bdee6c511a8852b87caf8e5f0800b8f017a/services/api/src/suggestion/check.md#L3)은 같은 위치·조작의 선택 부담 감소를 허용한다. [7행](https://github.com/minjunkim-dev/smallnext/blob/0e372bdee6c511a8852b87caf8e5f0800b8f017a/services/api/src/suggestion/check.md#L7)은 reason의 독립 증거 사용을 금지하고 입증된 실패와 근거 부족을 구분한다. 두 방향의 근거 대조를 더 직접 강조하며 기준을 완화하지 않는다.
[Rust instructions](../../services/api/src/suggestion.rs#L189)는 역할 MD와 공유 계약을 합친다. [Python evaluate](../../scripts/oauth_quality.py#L623)는 동결 manifest의 생성 prompt를 사용한다. [request](../../scripts/oauth_quality.py#L354)는 전달받은 prompt를 compact 형태로 바꾼다. [기존 공식 fixture 대조](../../scripts/test_oauth_contract.py#L18)는 Python 전달값과 Rust fixture를 비교한다.
[Rust compact](../../services/api/src/suggestion/compact.rs#L293)와 Python request는 `smaller/need_info`에서 일반 check prefix를 교체한다. 이번 일반 check 보완은 그 경로에 전달되지 않는다. check-question·Rust/Python 실행기·등록한 `PROTOCOLS`를 변경하지 않는다.

### 선택한 최소 문구

생성 지침의 기존 source-work 세 문장을 다음으로 대체한다.

> For source work of unknown total amount, specify a bounded useful part to find, read, copy or check rather than all matching material. A short estimate alone does not bound that work. Unknown total length alone does not require a question when a useful supported partial action is possible.

생성 지침에 선택 규칙의 결과 보존을 다음과 같이 강조한다.

> When reducing selection work, keep a rule that yields a unit useful for the goal. Position or grammatical form alone does not establish the needed relevance unless that feature is itself the required goal result.

일반 검사 지침의 추가 후보는 다음 두 문장이다.

> Matching location, operation, item count or estimate alone proves neither reduction nor its absence. For a claimed reduction in selection work, verify both the selected unit's usefulness for the goal and the supported decrease in required selection work.

한국어 정당화와 원문 인용의 언어를 다음 문장으로 구분한다.

> Write the justification in Korean; exact input or candidate quotes may retain their original language.

### 반례와 검증 경계

목표 자체가 문법·위치 확인을 요구하면 그 특징은 유용한 결과일 수 있다. 제공된 자료의 일부 확인·이미 제공한 기록 문맥·제목/표시 자체가 필요한 목표 결과·글자/항목/선택 부담 감소를 유지한다. 총분량 질문을 일괄 강제하거나 임의 단어를 목표 결과로 간주하지 않는다.
reason의 주장은 계속 대조 대상이다. 다른 근거로 입증된 실패는 기존 `reject`를 따른다. 결정적 근거 부족은 `uncertain`을 유지한다. 정상 `minimum/need_info`·사실·남은 범위·보류를 유지한다.
검증은 공식 fixture의 generate·check·check-unpreserved 변경과 check-question·공유 계약·schema·12사례/status 보존을 구분한다. 새 인터페이스·문자열 의미 검사·자동 모델 재시도는 제안하지 않는다. 전달 검증은 실제 AI 품질 개선을 증명하지 않는다.
보관 식별자는 #220 승인판정표 SHA `b30cdf33edb4d3e90b5bdacfa2d700e10c8be8c50dbe5d189c5204fe1b5e7780`, 출처기록 SHA `b82d2a02ac89163cbbce5a918a97227069dfbdb83757a5b44067c47a14e1cd0b`이다. 담당자 minjunkim-dev와 삭제 상한 `2026-11-20T15:10:10.145476+09:00`을 유지한다.
이 연구는 공개 승인 요약과 공식 소스만 대조했다. private 원문을 읽지 않았다. 검사·모델·OAuth·유료 API를 실행하지 않았다. 실제 수행·품질 개선·화면·서버·실기기·출시는 검증하지 않았다.

## #224 후속: minimum의 동일 작업 재표시와 실제 도움

2026-10-21, [#224](https://github.com/minjunkim-dev/smallnext/issues/224). 비교 기준 소스는 `f19f95b70365ba37f1a2a8e120aed60a6e352fc1`이다. 앞의 148행과 기존 판정을 보존한다.
[#223의 직접 승인](https://github.com/minjunkim-dev/smallnext/issues/223#issuecomment-6310744883)은 000·001·002 충족과 011의 기준 4 거부 유지이다. 수행 시간은 추정이다. 자동 `accept` 11건·`reject` 1건과 011의 `minimum` 상태도 보존한다.
공개 승인 요약에서 011은 직전과 같은 필수 작업·고정 표시·단어 하나·3분을 유지했다. 이미 단어 하나인 작업에 문장을 쓰지 않는다는 제약을 더한 것을 새 도움으로 인정하지 못했다. 모든 minimum에 추가 축소를 강제한 판정은 아니다. 이전 #220의 action과 이번 minimum은 다른 결과이다. 같은 중단 위치를 같은 원인의 증거로 쓰지 않는다.
이 연구는 공개 승인 요약과 현재 공식 소스를 따로 확인했다. private 원문을 읽거나 복사하지 않았다. 기존 직접 승인·자동 판정·연구를 구분한다. 새 사람 판정이나 실제 수행 관측으로 세지 않는다.

### 사실과 가설

[공유 계약 15행](../../services/api/src/suggestion/contract.md#L15)은 minimum에도 유용한 결과와 공급한 막힘의 도움을 요구한다. 동일 작업·군더더기·다루지 않은 막힘을 라벨로 정당화할 수 없다. [18행](../../services/api/src/suggestion/contract.md#L18)은 직전 필수 작업과 실제 감소·도움을 비교한다. [기준 4](../../services/api/src/suggestion/contract.md#L26)는 action의 축소와 minimum의 중단·도움 규칙을 구분한다.
기준 소스의 [generate 3행](https://github.com/minjunkim-dev/smallnext/blob/f19f95b70365ba37f1a2a8e120aed60a6e352fc1/services/api/src/suggestion/generate.md#L3)은 유용한 추가 축소가 없으면 minimum 또는 need_info를 선택하도록 한다. 같은 문단은 직전 제안이 이미 처리한 막힘과 남은 필수 작업의 비교도 요구한다. [7행](https://github.com/minjunkim-dev/smallnext/blob/f19f95b70365ba37f1a2a8e120aed60a6e352fc1/services/api/src/suggestion/generate.md#L7)은 두 행동 상태 모두의 유용한 결과를 요구한다. 공유 계약이나 유용함 규칙이 없었던 것은 아니다.
**가설:** minimum 선택 안내 바로 뒤에 이미 제공한 도움과 새 도움의 차이를 명시하면 기계적인 상태 재표시 위험을 다룰 수 있다. 이것이 모델 내부의 실제 원인이었다고 확정하지 않는다. 이번 일반 검사는 거부를 포착했다. 검사 완화나 기준 변경의 근거는 없다.

### 권장 문구와 반례

생성 지침의 기존 `If no useful material reduction remains, choose minimum or need_info...` 문장 뒤에 다음 세 문장을 보완하도록 권장한다.

> Minimum need not reduce work further, but must leave a useful result and provide supported help for the current blocker. Help already provided by the latest proposal or a constraint its required work already satisfies is not new help. Relabeling the same required work as minimum does not supply that help.

minimum을 항상 더 작은 작업으로 바꾸지 않는다. 추가 축소 없이도 현재 막힘에 실제 도움을 주는 유용한 minimum은 허용한다. 과거 막힘을 이미 도왔다는 사실로 현재 작업의 미확인 막힘까지 해결했다고 가정하지 않는다.
유용한 글자·항목·선택 부담 감소와 같은 위치·조작의 유용한 결과는 유지한다. 제공한 자료의 일부 확인·필요한 찾기/읽기·이미 제공한 기록 문맥·제목/표시 자체가 필요한 목표 결과도 유지한다. 최신 작업의 첫 막힘이 미확인이면 [기존 need_info 중단 규칙](../../services/api/src/suggestion/contract.md#L12)을 적용한다. 완료·미완료·남은 범위·보류·사실 보존은 바꾸지 않는다.

### 도달 범위와 검증 한계

[Rust instructions](../../services/api/src/suggestion.rs#L189)는 생성 MD와 공유 계약을 합친다. [compact instructions](../../services/api/src/suggestion/compact.rs#L291)는 생성 역할에 기존 전달 규칙을 덧붙인다. 이번 구현 범위는 generate.md와 공식 fixture의 generate 전달값 및 이 노트이다. check·check-unpreserved·check-question·공유 계약·schema·12사례/status·참조·실행기·PROTOCOLS·상한은 유지한다.
공식 전달 경계의 red와 fixture 재생성을 재사용한다. 이 전달 검증은 실제 minimum의 품질 개선을 증명하지 않는다. 새 제품 규칙·문자열 의미 검사·모의 통과 사례·자동 재시도·추상화는 제안하지 않는다. 실제 모델 평가는 별도 실행 범위 기록 뒤에 판단한다.
보관 식별자는 #223 승인판정표 SHA `a4753f01e0a829349a1358780b4d40f55d1a18b69f1d5d981912510c02772697`, 출처기록 SHA `be2ea81acfa1ab8b08cd63fbd8673a7621a8e3aee7a1eec8f84ffe95b477130f`이다. 담당자 minjunkim-dev와 삭제 상한 `2026-11-20T16:29:53.192046+09:00`을 유지한다.
이 연구는 모델·CLI·테스트·원격 변경을 실행하지 않았다. 파일 변경은 기존 노트 뒤의 이 절뿐이다. 실제 수행·품질 개선·화면·서버·실기기·출시는 검증하지 않았다.
