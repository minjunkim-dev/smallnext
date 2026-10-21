# 후속 축소의 필수 작업 비교

2026-10-21, [Issue #205](https://github.com/minjunkim-dev/smallnext/issues/205).
기준 소스는 `72991cca49975879171380f07e0477f7d5559aa0`이다.
이 노트는 #204의 동결 근거를 비교한다. 원문과 판정을 바꾸지 않는다.

## 결론

생성 지침에 두 문장을 보완하는 안을 권장한다.
직전 제안이 입력에 제시한 막힘을 이미 다뤘어도 비교 기준은 그 제안에 남은 필수 작업이다.
응답 형식의 차이만으로 추가 감소를 가정하지 않도록 명시한다.
이는 기존 계약의 적용을 돕는 보완이다. 017의 위반이나 검사 오판을 확정하는 수정이 아니다.
기존 계약은 이미 직전 제안과의 필수 작업 비교를 요구한다. 지침 누락을 원인으로 확정하지 않는다. [공유 계약](../../services/api/src/suggestion/contract.md#L18), [기준 4](../../services/api/src/suggestion/contract.md#L26), [생성 지침](../../services/api/src/suggestion/generate.md#L3).

## 확인한 근거와 한계

[#47의 확정 답](https://github.com/minjunkim-dev/smallnext/issues/47#issuecomment-6189694213)은 예상 밖 결과와 완료 사양의 첫 반복을 사람 판정 대상으로 정한다.
#204의 직접 승인 대상은 `000·001·002·009·010·011·017`이다.
앞의 여섯 건은 기준 충족이다. 수행 시간은 추정이다.
017은 기준 4 불확실을 유지한다. 다른 기준의 미확인을 통과로 채우지 않는다.
이 기록은 33흐름 완주나 실제 수행 성공을 증명하지 않는다. [#204](https://github.com/minjunkim-dev/smallnext/issues/204).

017은 `fixed-quantity-3`의 두 번째 축소이다.
비교 대상은 `previous_proposals`의 마지막 항목이다.
직전 제안과 새 후보의 시간 추정은 모두 2분이다.
직전 제안은 입력에 제시한 작성 막힘을 이미 다루는 내용이다. 실제 수행은 미확인이다.
새 후보는 같은 작성 위치에서 요구 응답 형식을 바꾼다.
이 비교에서 추가 필수 작업 감소나 다른 실제 막힘의 해소를 입증하지 못했다.
형식 차이와 같은 시간 추정만으로 감소 또는 비감소를 확정할 수 없다.
실제 선택 부담이나 수행 시간의 차이도 관측하지 않았다.
따라서 `uncertain`을 위반 또는 오거부로 바꾸지 않는다. [#154의 미확인 분기](https://github.com/minjunkim-dev/smallnext/issues/154), [검사 지침](../../services/api/src/suggestion/check.md#L5).

막힘과 형식 차이의 의미 요약에는 담당 에이전트의 오프라인 분석을 함께 사용했다.
이 연구를 별도 독립 자연어 품질 판정으로 집계하지 않는다.

성공 여섯 건도 함께 비교했다.
`000·009`는 첫 행동이다. 축소 기준을 첫 행동에 추가하지 않는다.
`001·002·010·011`은 후속 축소이다. 같은 위치나 같은 조작이라는 사실만으로 배제하지 않는다.
유용한 필수 글자·항목 감소와 미선택 출력을 준비된 한 단위로 좁히는 선택 부담 감소는 계속 허용한다.
반대로 제안 설명문의 길이와 예상 시간만으로 그 감소를 증명하지 않는다.
고유 항목과 평가 표시의 연결도 유지한다. [공유 계약](../../services/api/src/suggestion/contract.md#L18), [생성 지침](../../services/api/src/suggestion/generate.md#L5), [검사 지침](../../services/api/src/suggestion/check.md#L3).

동결 근거의 식별자는 다음과 같다. hash는 읽은 바이트를 식별한다. 과거 진위나 의미의 정답을 증명하지 않는다.

| 근거 | SHA-256 |
| --- | --- |
| manifest | `1952cb40d61b55df6190eda3a16c2bfaef7ae4e415abc58edf7842be96731e8f` |
| `human-review-evidence.json` | `75bc2460e4a11b860f3e1a00401a6fa66753bec8d796e4e6a98258785480f7aa` |
| `human-review-links.json` | `ad64aeabb1928e7b53cc9b863862c965feac0d2a9cdcb1a5f0d1beaccf9c01b6` |
| `human-review-approved.md` | `ec0266cd66cc1aaf86188e490c1dc09dd92f36cd2eda916d2551b969216841a0` |
| 017 결과 | `870125f1a3ac448ef866070272070107d3def1030de5afcf66ec73df3bdf9ca4` |

원문과 파생 검토 자료는 기존 private 묶음에만 남긴다.
삭제 상한은 `2026-11-20 00:44:50 KST`이다. 이 노트로 기한을 연장하지 않는다. [보관 경계](../WORKFLOW.md#검증과-문서-관리), [#205의 유지와 제외](https://github.com/minjunkim-dev/smallnext/issues/205).

## 가설과 선택

1. **우선 검토:** 생성기가 직전 제안에 남은 작업보다 원래 막힘과 형식 차이에 기대어 후속 행동을 만들었을 수 있다. 원인으로 확정하지 않는다. 기존 비교 규칙을 생성 지침에 가깝게 명시하는 작은 보완은 이 위험을 다룬다.
2. **대안:** 실제 유용한 수량·선택 부담 감소가 있으나 근거가 부족할 수 있다. 이 가능성 때문에 형식 변경을 일괄 금지하지 않는다. 현재 판정은 불확실로 남긴다.
3. **근거 부족:** 검사기가 유효한 감소를 놓쳤을 수 있다. 현재 근거로 오거부를 확정할 수 없다. 검사 지침을 완화하거나 017을 수용으로 바꾸지 않는다.

권장 추가 문구는 다음과 같다.

> If the latest proposal already addresses the supplied blocker, compare the work it still requires. A different response format alone does not establish another reduction; useful reductions in required words/items or selection work still count under the shared contract.

공유 계약·검사 지침·schema·기존 사례는 유지한다.
기존 `minimum`·`need_info` 중단 규칙과 행동의 적격성도 유지한다.
이 문구는 새 응답 필드나 추가 추론 출력의 요구가 아니다. [상태와 적격성](../../services/api/src/suggestion/contract.md#L7), [중단 규칙](../../services/api/src/suggestion/contract.md#L12).

## 검증 경계와 다음 단계

생성 지침만 보완하고 공식 compact fixture를 갱신한다.
fixture 검사는 변경한 지침이 실제 요청에 전달됨을 확인한다. AI 품질 개선을 증명하지 않는다.
고정 base/head 독립 리뷰는 수량·선택 부담 감소 허용과 중단 규칙의 보존을 확인한다.
필수 CI와 실제 Trusted `accepted`를 확인한 뒤 병합한다. [병합 조건](../WORKFLOW.md#병합-조건), [Trusted CI ADR](../adr/0001-trusted-ci-aggregation.md).

새 실제 평가는 별도 실행 범위·변경·상한·보관·소유권 기록 뒤에 판단한다.
이 연구에서는 모델·OAuth·유료 API를 호출하지 않았다. 검사를 실행하지 않았다.
실제 수행·화면 응답 시간·서버·실기기·출시 품질은 검증하지 않았다.
진행 상태와 행동 결과는 제품 용어집의 의미를 유지한다. [CONTEXT](../../CONTEXT.md).
