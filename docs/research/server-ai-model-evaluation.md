# Smallnext 서버 AI 모델 비교와 평가 검토안

확인일: 2026-10-04. 공식 문서만 확인했다. 유료 API를 호출하지 않았다.
범위: OpenAI·Anthropic·Google의 주요 텍스트 API 모델 카탈로그다. 전체 시장 조사라고 주장하지 않는다.
대상 결정: [첫 버전에 사용할 서버 AI 공급자와 모델은 무엇인가?](https://github.com/minjunkim-dev/smallnext/issues/17). 확정 답은 해당 Issue에서 관리한다.
아래 추천은 평가 후보 제안이다. 제품 기본 모델은 아직 확정하지 않는다.
`사실`은 문서 확인값이다. `추론`은 후보 선정 판단이다. `미측정`은 실제 요청으로 확인하지 않은 값이다.

## 최신 주요 목록과 정상 가격

단위는 USD/백만 토큰이다. 캐시·Batch·도구 비용은 제외했다. 추론 토큰은 출력 과금에 포함된다.

| 공급자 | 주요 텍스트 모델 | 입력 / 출력 | 문서 상태 |
|---|---|---:|---|
| OpenAI | GPT-6 Astra | 10 / 50 | 최신 상위급 |
| OpenAI | GPT-6.1 Sol | 2 / 10 | 최신 균형형 |
| OpenAI | GPT-6 Luna | 0.10 / 0.50 | 최신 저비용형 |
| OpenAI | GPT-6 Sol | 2 / 10 | 이전 세대, 제공 중 |
| Anthropic | Claude Fable 5.1 | 10 / 50 | Active, 최신 |
| Anthropic | Claude Opus 5.5 | 4 / 20 | Active, 최신 |
| Anthropic | Claude Sonnet 5.5 | 2 / 10 | Active, 최신 |
| Anthropic | Claude Haiku 4.5 | 1 / 5 | Active, 현행 Haiku |
| Google | Gemini 3.8 Flash | 0.75 / 3.75 | Stable |
| Google | Gemini 3.7 Flash | 0.75 / 3.75 | Stable |
| Google | Gemini 3.6 Flash | 0.75 / 3.75 | Stable |
| Google | Gemini 3.5 Flash | 1.50 / 9 | Stable |
| Google | Gemini 3.5 Flash-Lite | 0.30 / 2.50 | Stable |
| Google | Gemini 3.1 Flash-Lite | 0.25 / 1.50 | 이전 Stable |
| Google | Gemini 3.1 Pro | 2 / 12 | Preview, 입력 200k 이하 |

사실: Gemini 3.8·3.7·3.6 Flash의 위 가격은 2026-12-31까지다. 2027-01-01에는 1.50 / 7.50이 된다.
사실: Gemini 3.1 Pro Preview는 입력 200k 초과 시 4 / 18이다. GPT-6 계열은 입력 272k 초과 시 별도 장문 요율이 적용된다.
범위 밖: 전용 코딩·이미지·음성·실시간 모델과 오래된 모델은 전체 가격표로 펼치지 않았다. 카탈로그에는 구형 모델도 남아 있다.
출처: [OpenAI 카탈로그](https://developers.openai.com/api/docs/models), [Claude 카탈로그](https://platform.claude.com/docs/en/models/overview), [Gemini 카탈로그](https://ai.google.dev/gemini-api/docs/models), [Gemini 정상 가격](https://ai.google.dev/gemini-api/docs/pricing).
OpenAI 가격 출처: [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [Sol 6.1](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol 6](https://developers.openai.com/api/docs/models/gpt-6-sol).

## 상세 후보 6개

| 후보 | 정확한 API ID | 상태 | 입력 / 출력 | 구조화 출력 |
|---|---|---|---:|---|
| GPT-6 Luna | `gpt-6-luna` | 일반 모델, Preview 표기 없음 | 0.10 / 0.50 | 지원 |
| GPT-6.1 Sol | `gpt-6.1-sol` | 일반 모델, Preview 표기 없음 | 2 / 10 | 지원 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | Active, 최신 | 2 / 10 | GA 지원 |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | Active, 최신 | 1 / 5 | GA 지원 |
| Gemini 3.8 Flash | `gemini-3.8-flash` | Stable | 0.75 / 3.75 | 지원 |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | Stable | 0.30 / 2.50 | 지원 |

사실: OpenAI 두 모델의 snapshot 목록은 위의 날짜 없는 ID를 제시한다. 날짜형 ID를 만들면 안 된다. 가중치의 영구 불변 보장으로 확대하지 않는다.
사실: Claude 4.6 이후 날짜 없는 ID도 고정 버전이다. 문서는 해당 ID의 수명 동안 기반 모델을 바꾸지 않는다고 명시한다.
사실: Haiku의 날짜 없는 `claude-haiku-4-5`는 별칭이다. 재현 평가에는 날짜가 있는 ID를 사용한다.
사실: Gemini Stable은 특정 안정 버전이며 보통 변경하지 않는다고 설명한다. 불변 snapshot 보장은 아니다. `latest` 별칭은 자동 갱신되므로 평가에 쓰지 않는다.
출처: [OpenAI Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [OpenAI Sol 6.1](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Claude ID와 버전](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions), [Gemini 버전 이름](https://ai.google.dev/gemini-api/docs/models).

사실: OpenAI 두 후보와 Gemini 두 후보의 종료일은 발표되지 않았다. 정해진 최소 지원 기간이 있다고 추정하지 않는다.
사실: Sonnet 5.5의 최소 지원 기준일은 2027-09-28이다. Haiku 4.5는 2026-10-15다. 이 날짜는 확정 종료일이 아니다.
사실: Claude 문서는 폐기 전에 최소 60일을 통지한다고 설명한다. Haiku는 평가 직전 상태를 다시 확인한다.
출처: [OpenAI 폐기 공지](https://developers.openai.com/api/docs/deprecations), [Claude 수명 표](https://platform.claude.com/docs/en/about-claude/model-deprecations), [Gemini 폐기 공지](https://ai.google.dev/gemini-api/docs/deprecations).

사실: 세 공급자는 JSON Schema의 일부를 지원한다. 스키마 준수와 결과의 의미·사용 가능성은 다른 검사다. 앱 서버의 값 검증이 필요하다.
사실: 거절과 출력 한도 도달을 정상 JSON 결과로 가정하지 않는다. 모델별 스키마 제약을 어댑터에서 확인한다.
사실: Sonnet 5.5의 `thinking.type=disabled`는 지원하지 않는다. GPT-6.1 Sol의 `none`·`minimal`도 지원하지 않는다. Gemini 3.8 Flash의 `minimal`은 오류다.
출처: [OpenAI 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [Claude 구조화 출력](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [Gemini 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output), [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).

## 데이터 조건과 신규 모델 예외

사실: OpenAI API는 기본적으로 학습에 쓰지 않는다. 기본 abuse 로그는 최대 30일이다. 법적·안전상 예외가 있다.
사실: Responses의 기본 저장 상태는 최소 30일이다. `store=false`는 이 상태 저장을 줄이지만 abuse 로그까지 제거하지 않는다.
사실: ZDR·MAM은 사전 승인 조건이다. 신규 모델·일부 고객의 보관 예외도 문서에 있다. 현재 계정에 적용된다고 확인하지 않았다.
사실: GPT-6 캐시 쓰기는 일반 입력의 1.25배다. Luna는 0.125/M, Sol 6.1은 2.50/M이다. 캐시 보관과 ZDR 조건을 별도로 확인해야 한다.
추론: 평가 설정은 `prompt_cache_options.mode=explicit`과 breakpoint 없음으로 검토한다. 문서상 이 조합은 캐시 읽기·쓰기를 만들지 않는다. API로 실행하지 않았다.
출처: [OpenAI 데이터 제어](https://developers.openai.com/api/docs/guides/your-data), [GPT-6 캐시 설정과 가격](https://developers.openai.com/api/docs/guides/prompt-caching).

사실: Claude 상용 API는 기본적으로 학습에 쓰지 않는다. 일반 보관 조건은 30일이며 계정 계약·기능별 조건을 확인해야 한다.
사실: Fable 5.1·Mythos 5.1·Fable 5·Mythos 5에는 필수 30일 보관 예외가 있다. 명시적 허가 없이는 ZDR을 사용할 수 없다.
사실: Sonnet 5.5·Haiku 4.5는 이 Covered Models 목록에 없다. 이는 모든 계정의 ZDR이 승인됐다는 뜻이 아니다.
사실: 구조화 출력 스키마는 마지막 사용 후 최대 24시간 캐시한다. 스키마 이름·설명·enum에 개인 내용을 넣지 않는다. 정책 위반 자료에는 더 긴 보관 예외가 있다.
출처: [Claude API 보관](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention), [학습 조건](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training), [일반 보관 조건](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data), [스키마 보관](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

사실: Gemini 유료 API는 일반 제품 개선용 학습에 쓰지 않는다. 한국의 무료 API는 제품 개선·학습 및 사람의 검토에 쓰일 수 있다.
사실: 유료 API에도 abuse 감시용 입력·문맥·출력 55일 보관이 남는다. 정책 집행용 사용 예외가 있다. 새 후보에 별도의 완화 조건을 찾지 못했다.
사실: 선택적 개발자 로그·데이터 공유와 기본 abuse 보관은 다르다. 유료 선택만으로 무보관이 되지 않는다.
출처: [Gemini 약관](https://ai.google.dev/gemini-api/terms), [Gemini 사용 정책](https://ai.google.dev/gemini-api/docs/usage-policies).

## 평가 제안과 비용 가정

추론: 최신 저비용 후보 GPT-6 Luna와 현재 중간급 후보 Claude Sonnet 5.5를 1차 평가 쌍으로 제안한다. 두 후보의 구조화 출력·데이터 조건을 확인했다.
추론: GPT-6.1 Sol은 Luna의 품질이 부족할 때 비교할 상위 후보로 남긴다. Haiku 4.5는 가격이 낮지만 최소 지원 기준일이 가깝다.
추론: Gemini 3.8 Flash는 최신 대안이다. 3.5 Flash-Lite는 비용 대안이다. 두 후보는 55일 보관 조건의 수용 여부를 먼저 확인해야 한다.
추론: 최신이라는 이유나 가격만으로 최종 모델을 선택하지 않는다. 기존 5.4 mini 추천을 최신 모델 검토 결과로 정당화하지 않는다.

계산 가정: 요청마다 입력 8,000토큰·과금 출력 2,000토큰을 사용한다. 출력에는 숨은 추론을 포함한다. 캐시·도구·세금 비용은 제외한다.
계산 가정: 후보별 15흐름 × 최대 3요청 = 45건이다. 경계 3종 × 3회 = 9건을 더한다. 후보별 최대 54건이다.
계산값: Luna 0.0018USD/건, 54건 0.0972USD. Sonnet 5.5와 Sol 6.1은 0.036USD/건, 54건 1.944USD다.
계산값: Haiku는 54건 0.972USD다. Gemini 3.8은 현재 0.729USD, 2027년 요율은 1.458USD다. 3.5 Flash-Lite는 0.3996USD다.
계산값: Luna·Sonnet 평가 쌍의 최대 108건은 2.0412USD다. 1차 평가 API 한도 3USD는 검토안이다. 월 개인 API 예산 10USD는 유지한다.

미측정: 한국어 분할 품질, 첫 행동의 크기, 사용자 시작 성공, 지연, 실제 토큰, 실제 청구액, 오류율을 측정하지 않았다.
미확인: 계정별 모델 접근·결제 설정·보관 승인·요율 적용과 서버 설정 동작을 확인하지 않았다. 제품 출력 상한과 timeout은 아직 미확정이다.
후속: 고정 평가와 3상황 사용자 시작 평가를 통과한 뒤 제품 기본 모델을 고른다. 자동 재시도 0회와 모델 자동 전환 없음은 유지한다.
후속: 서버 키를 앱에 넣지 않는다. 자체 운영 메타데이터 7일·사용자 확인 익명 평가자료 30일과 공급자 보관을 구분한다.

## 합성 평가 입력 검토안

상태: 사용자 확인 전. 외부 API로 보내지 않았습니다.
이 문서는 평가 준비 자료입니다. 확정 답과 실제 평가 결과는 아닙니다.

기준은 [목표 분할 결과를 어떤 기준으로 통과시킬 것인가?](https://github.com/minjunkim-dev/smallnext/issues/6#issuecomment-5968651172)와 [첫 버전의 AI 연결 방식과 실패 시 동작은 무엇인가?](https://github.com/minjunkim-dev/smallnext/issues/10#issuecomment-5969227418)입니다.

### 공통 입력

아래 문장은 평가를 위한 합성 입력입니다. 실제 개인·회사 원문을 복사하지 않았습니다. 공개된 결정의 목표 구조와 경험 A의 종류만 사용합니다.

```text
목표: 준비 시작일부터 3주 안에 지원용 이력서 PDF 하나와 포트폴리오 PDF 하나,
대표 공개 저장소 1~2개와 기존 안내 페이지 하나를 정리한다.
완료 조건: 두 PDF의 경험·기간·역할이 서로 일치하고,
선택한 저장소의 설명 및 안내 페이지에서 자료를 확인할 수 있다.
이번 행동의 대상: 경험 A, iOS 빌드 환경 분리.
합성 원고: 경험 A의 제목만 있다. 실제 역할·수치·성과는 아직 확인하지 않았다.
사용할 수 있는 자료: 이 합성 원고와 앱에 남길 짧은 메모.
사용할 수 없는 자료: 원본 회사 문서, 비공개 저장소, 성과 측정 기록.
기본 제약: 링크를 읽었다고 가정하지 않는다. 없는 역할·성과·수치를 만들지 않는다.
현재 행동과 최종 목표의 완료를 구분한다.
```

이 입력은 실제 원고의 내용이나 경험 A의 역할을 확정하지 않습니다.
공급자에게 이름, 회사명, 연락처, 파일 경로, 저장소 주소와 문서 원문을 보내지 않습니다.

### 다섯 고정 상황

| 상황 | 공통 입력에 추가할 문장 | 기대 방향 |
| --- | --- | --- |
| 진행 가능 | 지금 짧은 메모를 쓸 수 있다. 역할을 설명할 문장은 아직 없다. | 역할 한 문장을 남기는 행동. 모르는 역할은 사용자가 적도록 한다. |
| 분량 부담 | 역할 한 문장을 쓰는 것이 부담된다. 먼저 표시 하나는 할 수 있다. | 역할 선택이나 표시 하나로 줄인다. 이미 안다고 가정하지 않는다. |
| 방법 모름 | 역할 문장을 어떻게 쓰는지 모르겠다. 빈칸 하나는 채울 수 있다. | 역할 표현의 예시 또는 틀을 제시한다. 예시를 실제 경력으로 단정하지 않는다. |
| 근거 부족 | 성과 근거가 없다. 지금 원본 기록에 접근할 수 없다. | 필요한 기록 종류 하나를 적는다. 접근 불가한 기록을 당장 열라고 하지 않는다. |
| 선택 어려움 | 어느 경험을 포함할지 모르겠다. 현재 맥락에 있는 후보는 경험 A 하나이다. | 경험 A의 적합성 또는 역할 하나를 표시한다. 새로운 경험을 만들지 않는다. |

각 상황을 같은 입력으로 세 번 실행합니다. 후보마다 15개 흐름입니다.
각 흐름에서 첫 행동과 ‘더 작게’ 최대 두 번을 검토합니다.
두 번째 ‘더 작게’에서 이미 알려진 막힘을 다시 묻는지도 확인합니다.
고정 입력은 실행 중 임의로 바꾸지 않습니다. 수정하면 새 평가 판으로 기록합니다.

### 경계 입력

1. **정보 부족**: 대상 경험과 역할을 모두 알 수 없습니다. 필요한 확인 하나를 제시해야 합니다.
2. **이미 완료**: 역할 선택 표시와 완료 기록이 있습니다. 같은 역할 선택을 다시 시키면 실패입니다.
3. **작은 행동만 완료**: 역할 선택만 끝났습니다. 역할 문장·PDF·최종 목표는 미완료입니다.

경계 입력은 각 종류를 세 번 실행하는 안을 제안합니다. 후보마다 9요청입니다.
후보별 최대 54요청, 추천 쌍 최대 108요청입니다. 사용자 확인 전에는 실행하지 않습니다.
실험의 입력 8,000토큰·과금 출력 2,000토큰 상한과 첫 비교 API 비용 3 USD를 제안합니다.
이 수치는 평가용 제한입니다. 제품 요청 상한과 타임아웃은 실제 측정 뒤에 정합니다.
보류는 미완료로 유지합니다. 부족한 선행 조건을 해결됐다고 가정하지 않습니다.

### 평가 기록

- 모델의 정확한 ID, 프롬프트·입력 판, 출력 상한과 추론 설정을 기록합니다.
- 익명 입력과 실제 응답은 운영 로그와 분리합니다. 최대 30일 보관 후 삭제합니다.
- 응답별 필수 기준 판정, 구조 오류·거절·잘림, 실제 총 지연, 사용 토큰과 청구 근거를 기록합니다.
- 최초 스키마 준비와 이후 요청의 지연을 구분합니다. 자동 재시도는 0회입니다.
- 실제 API 비용은 월 10 USD의 개인 검증 예산에 포함합니다. 예산을 자동 증액하지 않습니다.

품질은 다섯 필수 기준을 모두 충족해야 통과합니다. 평균으로 실패를 상쇄하지 않습니다.
사용자는 진행 가능·선택 어려움·근거 부족의 세 상황에서 직접 수행합니다.
의미 있는 행동 결과와 시작할 수 있었다는 확인을 함께 남깁니다.
API가 실행되지 않았거나 사용자가 수행하지 않았다면 해당 항목은 미검증입니다.

### 실행 전 확인할 항목

사용자가 평가용 후보, 이 합성 입력, 공급자 측 보관 조건과 평가 비용 범위를 확인해야 합니다.
현재 프로세스에는 공급자 API 키가 없습니다. 계정이나 다른 저장소의 키 보유 여부는 미확인입니다.
키는 이 문서·GitHub 댓글·채팅에 붙여 넣지 않습니다. 실행 환경의 비밀 저장 경로로 연결합니다.
기본 모델과 타임아웃은 실제 평가와 사용자 선택 뒤에 정합니다.
