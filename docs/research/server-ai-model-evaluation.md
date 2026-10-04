# Smallnext 서버 AI 모델 비교와 평가 검토안

확인일: 2026-10-04. 공식 문서와 기존 구독을 사용한 CLI 평가를 확인했다.
일반 개발자 API 키로는 요청하지 않았다. 구독 시험은 아래에서 구분한다.
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

미측정: 일반 서버 API의 지연·실제 토큰·청구액·오류율과 사용자 시작 성공을 측정하지 않았다. 구독 CLI의 반복 평가와 보조 의미 검토는 아래에서 구분한다.
미확인: 계정별 모델 접근·결제 설정·보관 승인·요율 적용과 서버 설정 동작을 확인하지 않았다. 제품 출력 상한과 timeout은 아직 미확정이다.
후속: 고정 평가와 3상황 사용자 시작 평가를 통과한 뒤 제품 기본 모델을 고른다. 자동 재시도 0회와 모델 자동 전환 없음은 유지한다.
후속: 서버 키를 앱에 넣지 않는다. 자체 운영 메타데이터 7일·사용자 확인 익명 평가자료 30일과 공급자 보관을 구분한다.

## 합성 평가 입력 검토안

상태: 2026-10-04 사용자가 비교 진행을 승인했습니다. 예비 시험 뒤 같은 합성 상황으로 구독 CLI 반복 평가를 진행했습니다.
이 문서는 연구와 평가 기록입니다. 제품 기본 모델의 확정 답은 아닙니다.

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

경계 입력은 각 종류를 세 번 실행합니다. 후보마다 9요청입니다.
후보별 54요청, 추천 쌍 108요청입니다. 구독 반복 평가와 일반 서버 API 평가를 구분합니다.
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

사용자는 최신 후보 비교 진행을 승인했습니다. 첫 비교 상한 3 USD와 월 10 USD 범위를 유지합니다.
현재 프로세스에는 공급자 API 키가 없습니다. 계정이나 다른 저장소의 키 보유 여부는 미확인입니다.
키는 이 문서·GitHub 댓글·채팅에 붙여 넣지 않습니다. 실행 환경의 비밀 저장 경로로 연결합니다.
기본 모델과 타임아웃은 실제 평가와 사용자 선택 뒤에 정합니다.

## 기존 구독을 사용한 예비 시험

2026-10-04 사용자가 구독 OAuth로 시험할 수 있는지 물었다. 공식 CLI의 기존 로그인을 확인한 뒤 같은 합성 사례를 각 후보에 1회 전달했다.
Codex는 ChatGPT 로그인, Claude Code는 `claude.ai`의 Max 로그인이었다. API 키를 생성·사용하거나 OAuth 토큰을 추출하지 않았다.

| 요청 후보 | 결과 | 전체 CLI 경과 | 받은 현재 행동 | 최종 목표 완료 |
| --- | --- | ---: | --- | --- |
| `gpt-6-luna` | 종료 0, 한국어 JSON | 7.56초 | 본인이 맡은 일을 한 문장으로 적기 | false |
| `claude-sonnet-5-5` | 종료 0, 한국어 JSON | 5.48초 | 역할 문장 틀의 빈칸 채우기, 불확실한 내용 표시 | false |

Luna는 요청 ID다. Codex 응답 이벤트에 별도의 실제 모델 ID는 없었다. Sonnet은 modelUsage에서 해당 ID와 firstParty를 확인했다.
Codex 입력 20,721·출력 87토큰, Claude 입력 2·캐시 생성 1,531·출력 509토큰이 기록됐다. CLI 시스템 맥락이 서로 다르다.
Codex에는 스킬 설명 예산 초과 경고가 있었다. Claude 구조 출력은 내부 tool_use로 기록됐다. 외부 검색·문서·셸 도구 호출은 관찰되지 않았다.
CLI가 표시한 정가 환산 비용은 구독의 실제 추가 청구 증거가 아니다. 구독 한도 사용과 API 청구를 구분한다.
이번 예비 시험 2건만으로 전체 품질을 통과시키지 않는다. 이후 반복·재분할·경계 평가 결과는 다음 절에 기록한다. 사용자 3상황 수행은 별도다.
위 시간은 CLI 실행 시간이다. 서버 API의 비용·지연·보관 조건을 검증한 값으로 사용하지 않는다.

사실: 구독으로 공식 Codex·Claude Code를 사용할 수 있다. 평가 키가 모든 예비 시험의 필수 조건은 아니다.
사실: OpenAI는 지원되는 Sign in with ChatGPT 통합에서 구독 OAuth 추론도 제공한다. Smallnext의 통합·계정별 모델 접근은 확인하지 않았다.
사실: Claude 구독의 개인 CLI 사용과 제품의 API 인증은 다르다. 기존 구독 토큰을 Smallnext 서버 인증으로 복사하지 않았다.
출처: [Codex 인증](https://learn.chatgpt.com/docs/auth), [Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode), [Claude Code 비대화형 실행](https://code.claude.com/docs/en/headless), [Claude 구독 인증 범위](https://code.claude.com/docs/en/legal-and-compliance), [OpenAI 구독 OAuth 추론](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).

## 구독 고정 평가: 실행 조건과 판정

사용자 승인 뒤 `subscription-v1`을 실행했다. 다섯 상황은 각 3회 반복했다. 각 흐름은 첫 행동과 재분할 2회로 구성했다. 경계 3종은 각 3회 실행했다. 후보별 54요청이다.
두 후보는 같은 합성 입력과 JSON Schema를 받았다. 예상 답과 채점표는 입력에 넣지 않았다. 재분할에는 이전 제안과 아직 시작하지 않았다는 고정 피드백을 전달했다.
출력 필드는 `status`, `action`, `completion_condition`, `estimated_minutes`, `reason`, `remaining_work`, `goal_completed`, `current_action_completed`, `preserved_completed_ids`다. 분 단위 시간은 모델의 추정이며 사용자 수행 시간이 아니다.
새 제안은 미실행 상태다. 남은 역할 문장·기간·두 PDF·저장소·안내 페이지를 모두 유지해야 한다. 완료 경계에서는 `role-mark` 자기 보고만 보존한다.

Codex CLI 0.160.0과 Claude Code 2.1.289를 사용했다. 두 후보 모두 `low` 추론 설정이다. 요청별 CLI 세션을 새로 만들었다. 공급자별 순차 실행, 공급자 간 병렬 실행이다.
Codex는 사용자 설정을 무시하고 전용 모델 지침 파일과 출력 스키마를 지정했다. 읽기 전용 sandbox를 사용했다. 셸·파일 변경·웹 검색·이미지 도구를 껐다. 스킬 설명 예산은 1토큰으로 지정했다.
Claude는 safe/restricted 모드, 빈 도구 목록, 빈 MCP 설정, 설정 소스 없음, slash command 없음, 세션 저장 없음으로 실행했다. `--bare`는 구독 OAuth를 읽지 않으므로 쓰지 않았다.
하네스 timeout은 120초다. timeout·CLI 오류·관찰된 외부 도구 실행은 해당 후보 실행을 중단한다. 하네스 재시도는 0회, 요청한 모델 전환은 없다. CLI 내부의 전송 재시도 횟수는 확인하지 않았다.
API 키와 별도 공급자 경로 환경 변수는 자식 프로세스에서 제외했다. 저장된 공식 CLI 구독 로그인을 사용했다. OAuth 토큰을 읽거나 서버로 복사하지 않았다.

### v1 결과와 수정

v1의 자동 구조·상태 검사는 108/108건을 통과했다. 두 후보 모두 품질은 미통과다. AI의 보조 의미 검토에서 미실행 역할 작업을 남은 목록에서 삭제한 응답을 확인했다.

| 후보 | 역할 작업 누락 | 재현 ID |
| --- | ---: | --- |
| Luna | 6/54 | `method-1-0`, `method-2-0`, `method-2-1`, `method-3-0`, `evidence-3-0`, `evidence-3-1` |
| Sonnet | 8/54 | `progress-3-0`, `evidence-3-0`, `choice-1-0`, `choice-1-1`, `choice-3-0`, `already_done-1-0`, `already_done-2-0`, `small_done-1-0` |

ID는 상황·반복 번호·단계를 뜻한다. 단계 0은 첫 행동, 1과 2는 재분할이다. 필수 기준 5의 남은 범위 보존 실패다. 목표 완료 false와 JSON 형식이 맞아도 통과가 아니다.
Luna는 제목만 있는 원고에서 기존 메모 내용을 발췌하도록 요구한 사례도 있었다. 없는 자료를 전제로 한 행동은 필수 기준 2와 4를 충족하지 못한다.

입력과 스키마를 유지하고 시스템 지침을 보완했다. 빈 메모·미실행 상태·남은 목록 보존·현재 막힘의 직접 처리·최소 행동의 한계를 명시했다. 같은 전체 세트를 `subscription-v2`로 다시 실행했다.
v2는 남은 목록이 입력과 정확히 일치하는지도 자동 검사한다. 목록에서 역할 작업을 제거한 부정 입력으로 이 검사가 실패하는지 확인했다.
v1 시스템 SHA256: `4629217d5a4b58b89ccdfa187391b95fad6acd63167054a882a46e42b2d18db9`.
v2 시스템 SHA256: `23fa58b4d72e3aee1160708cb8700a6dc26d3916b504ff621242b62878978cd0`.

### 실행 집계

v1과 v2를 모두 마쳤다. 총 216요청이다. 예비 시험 2건은 이 집계에서 제외했다. 각 후보·판에서 다섯 상황은 9건씩, 경계 세 종류는 3건씩 실행했다.
CLI 종료 오류·하네스 timeout은 관찰되지 않았다. v2의 자동 구조·상태 검사 및 남은 목록 일치 검사는 108/108건을 통과했다. 의미 품질 통과를 뜻하지 않는다.

| 판 | 후보 | 요청 | CLI 경과 중앙값 | p90 |
| --- | --- | ---: | ---: | ---: |
| v1 | Luna | 54 | 8.703초 | 11.592초 |
| v1 | Sonnet | 54 | 6.765초 | 7.603초 |
| v2 | Luna | 54 | 8.651초 | 10.865초 |
| v2 | Sonnet | 54 | 5.787초 | 6.370초 |

p90은 정렬한 요청 경과 시간의 90% nearest-rank 값이다. 요청 시작부터 CLI 종료까지 측정했다. 최초 스키마 준비 시간을 별도 서버 계측으로 분리하지 못했다. 공급자별 CLI 시스템 맥락과 캐시가 다르므로 공정한 서버 API 속도 비교로 사용하지 않는다.

| 판·후보 | 입력 | 캐시 읽기 | 캐시 생성·쓰기 | 출력 |
| --- | ---: | ---: | ---: | ---: |
| v1 Luna | 564,381 | 343,296 | 0 | 10,236 |
| v1 Sonnet | 108 | 83,420 | 64,111 | 37,147 |
| v2 Luna | 598,083 | 484,352 | 0 | 9,761 |
| v2 Sonnet | 112 | 132,972 | 58,896 | 30,120 |

CLI가 보고한 usage 필드의 합이다. OpenAI 입력에는 캐시 입력이 포함된다. Claude의 일반 입력·캐시 생성·캐시 읽기는 별도 필드다. 이 값을 같은 입력 비용으로 단순 합산하지 않는다. 출력에는 CLI 내부 처리가 포함될 수 있으며 최종 JSON 길이와 다르다.
Luna는 요청 모델 ID이며 실제 응답 모델 ID가 별도로 반환되지 않았다. Sonnet은 모든 요청의 modelUsage에서 `claude-sonnet-5-5`를 확인했다. 일반 API 청구액을 계산하거나 실측했다고 주장하지 않는다.
두 판의 출력 스키마 SHA256은 `a13bb26ad96634f302301513c40155644603d684b7ce023ba157b015145aa0a9`로 같다. 프롬프트·입력·응답과 원문 파일 SHA256은 로컬 평가 자료에서 추적한다.

### v2의 남은 품질 문제

남은 목록 보존을 개선해도 현재 막힘을 다루는 의미 기준은 별도다. 다음 응답은 AI 보조 검토에서 실패로 분류했다. 사람의 전체 품질 승인으로 확대하지 않는다.

| 후보·ID | 관찰 결과 | 필수 기준 |
| --- | --- | --- |
| Luna `evidence-2-0` | 성과 근거가 없다는 입력에 기간 확인 기록을 적도록 바꿨다. 현재 성과 근거의 막힘을 다루지 않는다. | 4 |
| Sonnet `evidence-2-0` | 성과 근거 대신 역할 문장 작성을 요구했다. 원본 접근 없이 필요한 성과 기록 종류를 정하지 않았다. | 4 |
| Sonnet `evidence-3-2` | 새 메모에 경험 A 제목만 적게 했다. 성과 근거를 확보할 다음 결과가 없다. | 1, 4 |
| Sonnet `choice-2-2` | 포함 판단을 경험 A 제목만 적는 행동으로 줄였다. 결과에서 포함 여부가 사라졌다. | 1, 4 |
| Luna `small_done-3-0` | 이미 ‘직접 수행’ 표시가 완료됐는데 ‘내 역할: 직접 수행’을 다시 적게 했다. 완료한 표시를 반복한다. | 5 |

`minimum` 표시는 더 줄일 수 없다는 응답 상태다. 결과가 목표에 기여하는지, 현재 막힘을 다루는지는 계속 검사한다. 이 표시로 실패를 면제하지 않는다.
현재 두 후보 모두 전체 품질 통과와 제품 기본 모델 선정은 보류한다. 낮은 가격은 Luna를 후속 API 비교의 우선 후보로 삼는 근거다. 이번 결과는 제품 채택의 근거가 아니다.
다음 수정은 성과 근거·역할·기간을 서로 다른 막힘으로 다루고, 재분할에서도 현재 막힘과 행동 결과를 유지해야 한다. 통과 판정에는 수정 뒤 전체 고정 세트 재평가가 필요하다.

### 사용자 수행과 자료 보관

사용자 수행 1/3의 최초 안내에서 사용할 앱과 합성 경험을 명확히 구분하지 못했다. 사용자가 수행 위치를 물었다. 이 질문은 평가 절차의 안내 결함이다. 모델 결함이나 사용자 시작 실패로 계산하지 않는다.
맥 메모 앱의 새 메모에 사용자의 실제 작업 한 문장을 적는 방식으로 안내했다. 합성 경험 A를 사용자의 경력으로 가정하지 않는다. 안내를 바꾼 수행은 고정 합성 사례와 분리한 사용성 예비 확인이다.
사용자 수행·실제 시간·막힘의 답은 아직 받지 않았다. 진행 가능·선택 어려움·근거 부족 세 상황의 실제 시작 증거는 미검증이다. 회사 자료와 메모 원문을 요구하지 않는다.
AI 보조 검토와 자동 검사는 사람의 필수 기준 검토 및 실제 시작 증거를 대체하지 않는다. [#6 확정 기준](https://github.com/minjunkim-dev/smallnext/issues/6#issuecomment-5968651172)을 모두 충족한 뒤 [#17](https://github.com/minjunkim-dev/smallnext/issues/17)에서 모델을 확정한다.

합성 원문 응답·입력·CLI 이벤트는 로컬 평가 자료로 분리했다. 삭제 기한은 2026-11-03이다. 영구 Git 이력에는 원문 JSONL을 넣지 않는다. 이 문서에는 집계와 최소 재현 사례만 기록한다. 자동 삭제는 설정하지 않았다.
일반 개발자 API 키 요청과 키 생성은 0건이다. 구독 사용량은 별도 API 청구액이 아니다. 구독 보관 조건을 상용 API 보관 조건으로 대체하지 않는다.
