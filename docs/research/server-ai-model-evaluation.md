# Smallnext 서버 AI 공급자·모델 조사

확인일: 2026-10-04, Asia/Seoul. 공식 문서만 확인했습니다.
대상 결정: [첫 버전에 사용할 서버 AI 공급자와 모델은 무엇인가?](https://github.com/minjunkim-dev/smallnext/issues/17)
상태: 문서 조사 완료. 제품 기본 공급자·모델은 미확정입니다.

## 추천 후보

**평가용으로 GPT-5.4 mini와 Claude Haiku 4.5를 추천합니다.**
두 후보는 날짜가 있는 API 모델 ID를 고정할 수 있습니다. JSON Schema 출력도 지원합니다.
이 추천은 문서 적합성에 대한 판단입니다. 한국어 행동 분할 품질과 지연을 측정하지 않았습니다.
Gemini 3.1 Flash-Lite는 세 번째 대안입니다. 유료 API도 남용 감시 자료를 55일 보관합니다.
평가용 후보와 제품 기본 모델의 최종 선택을 구분합니다. 사용자 확인 전에는 API를 호출하지 않습니다.

## 현재 모델과 정상 가격: 확인한 사실

가격은 USD/백만 토큰입니다. 일반 온라인 요청 기준입니다. 캐시·Batch·Priority·지역 추가요금을 제외했습니다.

| 공급자 | 평가용 정확한 API ID | 상태와 고정 | 입력 | 과금 출력 | 추론 비용 |
|---|---|---|---:|---:|---|
| OpenAI | `gpt-5.4-mini-2026-03-17` | 비-preview. 날짜 스냅샷. 별칭은 `gpt-5.4-mini` | $0.75 | $4.50 | 추론 토큰도 출력 가격으로 과금 |
| Anthropic | `claude-haiku-4-5-20251001` | Active. 날짜 스냅샷. 별칭은 `claude-haiku-4-5` | $1.00 | $5.00 | 생각을 표시하지 않아도 추론 토큰은 출력 가격으로 과금 |
| Google | `gemini-3.1-flash-lite` | Stable. 특정 stable ID. 날짜 스냅샷 ID는 확인하지 못함 | $0.25 | $1.50 | 출력 가격에 thinking 토큰 포함 |

출처: [OpenAI 모델](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [OpenAI 추론](https://developers.openai.com/api/docs/guides/reasoning), [Haiku 모델](https://platform.claude.com/docs/en/models/haiku-4-5/overview), [Claude 추론](https://platform.claude.com/docs/en/build-with-claude/thinking), [Gemini 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [Gemini 가격](https://ai.google.dev/gemini-api/docs/pricing).

OpenAI 후보는 `reasoning.effort: none`을 지원합니다. 해당 모델의 기본값도 `none`입니다.
Haiku 후보는 thinking을 생략하거나 `disabled`로 설정하면 추론을 끌 수 있습니다.
Gemini 후보는 thinking을 지원합니다. 현재 공통 thinking 표에서 이 ID의 상세 단계는 확인하지 못했습니다.
Gemini Stable 문서는 stable 모델이 보통 변경되지 않는다고 설명합니다. 날짜 스냅샷과 같은 불변 보장은 하지 않습니다. [모델 버전](https://ai.google.dev/gemini-api/docs/models), [thinking](https://ai.google.dev/gemini-api/docs/thinking).
Haiku의 폐기 보장 하한은 2026-10-15입니다. 이 날짜는 실제 종료일이 아닙니다. 현재 표는 Active이며 폐기 통지는 N/A입니다. 공개 모델은 종료 최소 60일 전에 통지합니다. [폐기 정책](https://platform.claude.com/docs/en/about-claude/model-deprecations).
예전 `gpt-5-mini`는 현재 Deprecated입니다. 새 평가 후보로 추천하지 않습니다. [모델 상태](https://developers.openai.com/api/docs/models/gpt-5-mini).

## 구조화 출력: 확인한 사실

| 후보 | 지원 | 실험에서 처리할 제약 |
|---|---|---|
| GPT-5.4 mini | Responses의 `text.format`에 JSON Schema와 `strict: true` 사용 | 루트는 object. 루트 `anyOf` 불가. 모든 속성 required. 선택값은 nullable로 표현. 모든 object의 `additionalProperties: false` 필요 |
| Haiku 4.5 | Messages의 `output_config.format`에 `type: json_schema` 사용. GA 지원 | `additionalProperties: false` 필요. 숫자 min/max와 문자열 길이 제약 등은 지원하지 않음. SDK가 일부 제약을 제거하고 응답을 로컬 검증할 수 있음 |
| Gemini 3.1 Flash-Lite | JSON Schema 출력 지원 | JSON Schema 일부만 지원. 큰 스키마와 깊은 중첩은 거절 가능. 문법상 JSON이어도 의미상 잘못된 값은 앱에서 검증해야 함 |

OpenAI 스키마 한도는 속성 총 5,000개와 중첩 10단계입니다. 속성명·정의명·enum·const 총 문자열은 120,000자 이하입니다.
Haiku는 재귀 스키마와 외부 `$ref`를 지원하지 않습니다. 배열 제약은 `minItems` 0 또는 1을 넘는 경우 제한됩니다.
거절과 출력 토큰 한도 도달은 구조 준수 보장의 예외입니다. 잘못된 응답을 저장 상태로 반영하지 않는 검증이 필요합니다.
출처: [OpenAI 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [Claude 구조화 출력](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [Gemini 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output).

## 학습과 보관: 확인한 사실

**Smallnext 자체 보관과 공급자 보관은 별개입니다.** 자체 운영 메타데이터 7일과 익명 평가자료 30일은 공급자 보관을 줄이지 않습니다.

| 항목 | OpenAI API | Anthropic API | Gemini Developer API |
|---|---|---|---|
| 일반 모델 학습 | 기본 미사용. 명시적 공유를 켜면 달라짐 | 상업 API 기본 미사용. 피드백·사용 허용을 하면 달라짐 | 유료는 제품 개선 미사용. 한국의 무료 API는 제품·모델 개선에 사용 가능 |
| 일반 입력·출력 / 남용 감시 | 기본 남용 감시 로그 최대 30일. 법률·서비스 보호 예외 있음 | 상업 API 기본 입력·출력 30일 이내 삭제. 법률·정책 집행 예외 있음 | 프롬프트·문맥·출력 55일 남용 감시 보관 |
| 응답 저장 | Responses 기본 또는 `store: true`이면 최소 30일. `store: false` 지정 | Messages에 같은 `store` 스위치는 확인하지 못함. 별도 ZDR는 영업팀과 협의 | 개발자 API 로깅은 선택. 끄면 개발자 로그는 줄일 수 있으나 남용 감시 55일은 남음 |
| 프롬프트 캐시 | GPU 로컬 암호화 KV가 남을 수 있음. 현재 데이터 문서상 최대 24시간 | 원문 대신 KV·해시를 메모리에 보관. 최소 수명 5분 또는 1시간 후 삭제 | implicit 캐시는 2.5 이상 기본 사용. TTL 상한은 확인하지 못함. explicit은 기본 1시간과 TTL 지정·삭제 지원 |
| 구조화 스키마 | 시스템 데이터로 분류. 확인 문서에서 별도 보관 TTL을 찾지 못함 | 최종 사용 후 최대 24시간 스키마 캐시 | 확인 문서에서 별도 스키마 보관 TTL을 찾지 못함 |

OpenAI `store: false`는 응답 상태 저장을 제어합니다. 남용 감시 로그와 프롬프트 캐시의 완전 삭제를 뜻하지 않습니다.
OpenAI ZDR와 Modified Abuse Monitoring은 사전 승인이 필요합니다. 현재 계정의 승인 여부는 확인하지 않았습니다. [OpenAI 데이터 정책](https://developers.openai.com/api/docs/guides/your-data).
Claude 구조화 출력 문서는 요청·응답의 ZDR 처리와 스키마 24시간 캐시를 설명합니다. 일반 상업 보관 정책은 30일을 설명합니다.
Claude 전체 계정의 ZDR 보장을 추정하지 않습니다. 실제 계정·계약에서 적용 범위를 확인해야 합니다.
Claude는 안전 시스템이 표시한 입력·출력을 최대 2년 보관할 수 있습니다. 법적 보관 예외도 있습니다. [데이터 조건](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention).
스키마의 속성명·enum·const·설명에는 사용자 개인자료를 넣지 않는 구성이 적합합니다. 이것은 본 조사의 운영 제안입니다.
출처: [Claude 일반 보관](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data), [Claude 학습](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training), [Claude 스키마 보관](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#data-retention), [Claude 캐시](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#data-retention).
Gemini 유료 서비스는 활성 Cloud Billing 프로젝트의 API입니다. API가 무료라는 이유로 유료와 같은 데이터 조건을 적용하면 안 됩니다.
Gemini 남용 감시 데이터는 일반 모델 학습에 사용하지 않습니다. 정책 집행용 모델의 학습·미세조정은 예외입니다.
Gemini 개발자 로그는 별도로 기본 최대 55일이며 7·14·28·55일로 조정할 수 있습니다. Dataset으로 보관하면 정해진 만료가 없습니다.
Gemini Dataset을 Google에 공유하면 무료 서비스의 데이터 사용 조건이 적용됩니다. 평가에서 공유를 켜지 않는 구성이 적합합니다.
출처: [Gemini 약관](https://ai.google.dev/gemini-api/terms), [남용 감시](https://ai.google.dev/gemini-api/docs/usage-policies), [개발자 로그](https://ai.google.dev/gemini-api/docs/logs-policy), [캐시](https://ai.google.dev/gemini-api/docs/caching), [명시 캐시](https://ai.google.dev/gemini-api/docs/generate-content/caching).

## 계정과 결제: 확인한 사실

| 공급자 | 필요한 접근 | 무료와 결제 차이 |
|---|---|---|
| OpenAI | API 조직의 키·결제 권한과 유료 사용 단계 | 이 후보는 Free 단계 미지원. ChatGPT 구독과 별도 과금. 새 API 계정은 선불이며 최소 $5 구매 |
| Anthropic | Claude Console 계정·키. 크레딧 구매는 Admin 또는 Billing 역할 | 일반 API는 선불 크레딧. 현재 공식 문서에서 영구 무료 API 단계·신규 무료 금액·최소 충전액은 확인하지 못함 |
| Gemini | Google AI Studio의 프로젝트·키. 유료는 활성 Cloud Billing 연결 | Free 단계 있음. 유료 전환은 결제수단과 보통 최소 $5 선불. 계정에 따라 Postpay 선택 가능 |

OpenAI 자동 충전은 신규 선불 설정에서 기본 켜짐입니다. 월 $10 제한의 실험에서는 끄는 구성이 적합합니다.
선불 잔액은 즉시 중단 보장이 아닙니다. OpenAI는 반영 지연으로 음수 잔액이 생길 수 있다고 설명합니다.
Gemini 프로젝트 지출 상한도 실험적이며 약 10분 반영 지연이 있습니다. 충전액·월 소비액·실시간 차단은 다른 값입니다.
Anthropic는 연결 중단·timeout이어도 성공 예정 요청이면 과금할 수 있습니다. 실험 중 재전송 여부를 따로 기록해야 합니다.
공식 문서 접근만 확인했습니다. 실제 계정, 키, 잔액, 모델 접근, 결제 화면은 확인하지 않았습니다.
출처: [OpenAI 결제](https://help.openai.com/en/articles/8264644-setting-up-and-managing-prepaid-api-billing), [별도 과금](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform), [Claude 결제](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage), [Claude 시작](https://platform.claude.com/docs/en/get-started), [Gemini 결제](https://ai.google.dev/gemini-api/docs/billing).

## 요청 비용 계산: 측정치 아님

가정: 요청마다 입력 8,000토큰과 과금 출력 2,000토큰입니다. 출력 수는 추론을 포함합니다.
모든 입력에 정상 가격을 적용합니다. 캐시 할인·Batch·세금·환율·기타 도구 요금을 제외했습니다.
계산식: `(입력 토큰 × 입력 단가 + 과금 출력 토큰 × 출력 단가) / 1,000,000`.

| 후보 | 요청 1건 | 첫 행동 + 더 작게 2회: 최대 3건 | 15흐름 × 3건 + 경계 9건: 54건 |
|---|---:|---:|---:|
| GPT-5.4 mini | $0.015 | $0.045 | $0.810 |
| Haiku 4.5 | $0.018 | $0.054 | $0.972 |
| Gemini 3.1 Flash-Lite | $0.005 | $0.015 | $0.270 |

추천 쌍의 108요청 가정 비용은 **$1.782**입니다. 1차 실험 API 한도 $2는 제안값입니다.
실제 토큰 수가 가정보다 늘면 $2를 넘습니다. 월 개인 API 예산 $10과 제품 요청 상한은 별도입니다.
한국어는 공급자별 토크나이저가 다릅니다. 같은 글자 수가 같은 토큰 수라는 가정은 하지 않았습니다.

## 다음 평가와 미확인 범위

1. 추천 쌍과 합성 입력, 공급자 보관 조건, 첫 평가의 비용 범위를 사용자가 확인합니다. 계정의 접근·사용 가능 상태도 확인합니다.
2. 후보마다 고정 5상황 × 3회, 총 15흐름을 평가합니다. 첫 행동 뒤 더 작게는 최대 2회입니다.
3. 경계 3종 × 3회, 총 9요청을 추가하는 안을 검토합니다. 경계 입력과 합격 기준은 사전에 고정합니다.
4. 3상황의 실제 사용자 시작 평가를 합니다. 한국어 분할 품질·지연·실청구를 기록합니다.
5. 결과를 비교한 뒤 제품 기본 후보를 선택합니다. 요청 상한과 timeout은 측정 전 미확정으로 유지합니다.

자동 재시도 0회와 자동 모델 전환 없음은 이미 받은 조건입니다. 실험에서도 유지합니다.
서버 키는 앱에 넣지 않습니다. 텍스트만 요청합니다. 폴더·문서·저장소 자동 수집은 하지 않습니다.
실행 모델 ID, 프롬프트·스키마 버전, 추론 설정, 입력·출력·캐시 토큰, 실패·거절·지연·실청구를 함께 기록하는 안이 적합합니다.
이 기록 제안은 제품의 로그 보관 결정을 대체하지 않습니다. 원문을 운영 메타데이터 로그에 추가하지 않습니다.
유료 API 호출, 한국어 실측, 앱 구현, 키 조회, GitHub 변경은 수행하지 않았습니다.

## 확인값과 공식 출처

추천 2후보: `gpt-5.4-mini-2026-03-17`, `claude-haiku-4-5-20251001`.
정상 입력/출력: $0.75/$4.50, $1.00/$5.00. 비교 대안 Gemini는 $0.25/$1.50입니다.
보관 핵심: OpenAI 남용 감시 최대30일, Claude 일반 API30일과 예외, Gemini 남용 감시55일입니다.
고정5상황 반복과 사용자 시작 평가는 남아 있습니다. 제품 기본 모델 선택은 완료되지 않았습니다.
핵심 공식 URL: [OpenAI 모델](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [OpenAI 데이터](https://developers.openai.com/api/docs/guides/your-data), [Haiku 모델](https://platform.claude.com/docs/en/models/haiku-4-5/overview), [Claude 데이터](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention), [Gemini 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [Gemini 가격](https://ai.google.dev/gemini-api/docs/pricing), [Gemini 보관](https://ai.google.dev/gemini-api/docs/usage-policies).

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
실험의 입력 8,000토큰·과금 출력 2,000토큰 상한과 첫 비교 API 비용 2 USD를 제안합니다.
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
