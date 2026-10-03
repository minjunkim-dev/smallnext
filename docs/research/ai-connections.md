# AI 연결 경로와 실제 제약

확인일: 2026-10-03. 조사 대상: [이슈 #9](https://github.com/minjunkim-dev/smallnext/issues/9).
이 문서는 첫 버전 개발 사양을 정하기 위한 조사 기록입니다.
공급자, 모델, 앱 형태는 아직 선택하지 않았습니다.

## 조사 범위와 결론

첫 사용자 범위는 본인의 업무, 학습, 개인 프로젝트입니다.
휴대폰 화면을 중심으로 검토합니다. 인터넷 사용은 허용합니다.
기존 AI 에이전트 연결은 선택 사항입니다.
AI는 목표, 완료 조건, 현재 행동, 완료 이력을 받아 행동 하나를 제시합니다.
사용자가 분할을 요청하면 같은 문맥에서 행동을 다시 줄입니다.

공식 문서에서 실행 가능한 연결 계약을 확인했습니다.
실제 연동, 한국어 분할 품질, 지연, 배터리 사용량은 측정하지 않았습니다.
구조화 출력 지원은 행동의 타당성을 증명하지 않습니다.

## 대표 경로 4개

| 경로 | 연결과 지원 환경 | 인증·비용 | 개인정보·연결 유지 | 다음 결정에 주는 함의 |
| --- | --- | --- | --- | --- |
| 1. 서버 API | 휴대폰 → 앱 백엔드 → OpenAI Responses API. 지원 모델은 JSON Schema 출력을 제공한다. [S01](https://developers.openai.com/api/docs/guides/structured-outputs) | API 키를 백엔드에 보관한다. 토큰·도구 사용량을 과금한다. [S02](https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety), [S03](https://developers.openai.com/api/docs/pricing) | 문맥을 공급자 서버로 보낸다. API의 학습 사용과 보관 정책을 따로 확인한다. [S04](https://developers.openai.com/api/docs/guides/your-data) | 설계 판단: 세 앱 형태에서 같은 호출 계약을 쓸 수 있다. 백엔드 운영과 외부 전송 허용 범위를 정해야 한다. |
| 2. Apple 기기 내 모델 | Apple 네이티브 앱 → Foundation Models의 `SystemLanguageModel`. Apple Intelligence 지원 기기가 필요하다. [S05](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel), [S06](https://support.apple.com/en-us/121115) | 기기 내 요청에는 계정·API 키·요청 요금이 없다. [S07](https://developer.apple.com/videos/play/meet-with-apple/205/) | 기기 내 추론은 오프라인으로 작동한다. 실행 전 모델 가용성을 확인한다. [S08](https://developer.apple.com/documentation/foundationmodels/generating-content-and-performing-tasks-with-foundation-models?changes=_1) | 설계 판단: 네이티브 iOS와 지원 기기를 선택하면 검토할 수 있다. 미지원·다운로드 중 상태의 대체 흐름이 필요하다. |
| 3. Android 기기 내 모델 | Android 앱 → ML Kit GenAI Prompt API → AICore/Gemini Nano. API는 beta이며 기기 목록이 제한된다. [S09](https://developers.google.com/ml-kit/genai/prompt/android), [S10](https://developers.google.com/ml-kit/genai) | 기기 내 호출의 추가 서버 요금이 없다. 앱별 추론·배터리 할당량은 있다. [S10](https://developers.google.com/ml-kit/genai) | 입력·추론·출력을 기기에서 처리한다. 최상위 전경 앱에서만 추론할 수 있다. [S10](https://developers.google.com/ml-kit/genai) | 설계 판단: 본인 기기가 Prompt API 지원 목록에 있는지 확인해야 한다. Android 버전만으로 지원을 보장할 수 없다. |
| 4. 기존 에이전트 실행 호스트 | 휴대폰 → 연결 중계 → PC/서버의 Codex SDK·App Server 또는 Claude Agent SDK. SDK는 호스트 런타임에서 실행한다. [S11](https://github.com/openai/codex/blob/main/sdk/typescript/README.md), [S12](https://code.claude.com/docs/en/agent-sdk/quickstart) | 호스트의 공급자 인증과 휴대폰의 호스트 접근 인증은 별개다. 구독 사용·API 과금 조건을 구분한다. [S13](https://developers.openai.com/codex/auth/), [S14](https://code.claude.com/docs/en/agent-sdk/overview) | 호스트에서 파일·도구를 실행할 수 있다. 모델 요청과 세션 기록의 데이터 정책도 적용된다. [S11](https://github.com/openai/codex/blob/main/sdk/typescript/README.md), [S15](https://code.claude.com/docs/en/data-usage) | 설계 판단: PC 전원·프로세스·네트워크·재연결 관리가 추가된다. 첫 버전의 필수 조건으로 채택할지는 사용자 결정이 필요하다. |

표의 서버 경로는 API 키를 사용하는 대표 구현입니다.
인증 계약이 다른 서버 API까지 같은 제약으로 묶지 않습니다.
예를 들어 Claude API는 등록한 iOS/macOS 앱의 App Attest 직접 호출 경로를 문서화합니다.
이 경로의 등록, 앱 증명, 비용 통제는 이번 조사에서 구현하지 않았습니다. [S16](https://platform.claude.com/docs/en/manage-claude/authentication)

## 서버 API: 출력·키·문맥

OpenAI Structured Outputs는 지원하는 JSON Schema 부분집합을 따릅니다.
Responses API는 `text.format`으로 사용자에게 반환할 출력 구조를 지정합니다.
거절과 출력 중단은 별도 처리해야 합니다. [S01](https://developers.openai.com/api/docs/guides/structured-outputs)

OpenAI는 브라우저나 모바일 앱에 API 키를 넣지 말고 백엔드를 거치도록 안내합니다.
키를 저장소에 커밋하지 않습니다. [S02](https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety)
설계 판단: 앱 사용자 인증, 호출 제한, 키 보관, 공급자 호출을 백엔드의 책임으로 둡니다.
기존 ChatGPT 로그인 상태를 이 백엔드의 API 키로 취급하지 않습니다.

OpenAI API 데이터는 명시적 공유 동의가 없으면 모델 학습에 사용하지 않습니다.
기본 악용 감시 로그는 고객 내용을 포함할 수 있고 최대 30일 보관됩니다.
법적 의무나 위해 방지에 필요한 추가 보관 예외가 있습니다.
Responses API의 기본 애플리케이션 상태 보관과 감시 로그는 별개입니다.
`store:false`가 모든 로그의 무보관을 뜻하지 않습니다.
Zero Data Retention은 사전 승인과 조건이 필요합니다. [S04](https://developers.openai.com/api/docs/guides/your-data)

설계 판단: 첫 사용자에게 필요한 최소 문맥을 앱에서 관리합니다.
각 요청에 목표·완료 조건·현재 행동·완료 이력 요약을 보냅니다.
업무 문서 원문과 회사의 비공개 자료를 자동 첨부하는 기능은 별도 결정이 필요합니다.

## 로컬 지원: 조건을 나누어 확인

| 조건 | Apple `SystemLanguageModel` | Android ML Kit Prompt |
| --- | --- | --- |
| OS·SDK | OS 26 계열부터 존재한다. 26.4와 27에서 시스템 모델이 변경된다. OS별 프롬프트 재검증이 필요하다. [S05](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel), [S17](https://developer.apple.com/documentation/updates/foundationmodels) | 라이브러리의 최소 조건은 Android API 26이다. 이 조건은 AICore/Gemini Nano 지원 기기 조건을 대체하지 않는다. [S18](https://developers.google.com/ml-kit/genai/prompt/android/get-started) |
| 기기 | 휴대폰 기준 iPhone 15 Pro/Pro Max, iPhone 16 계열 이후, iPhone Air 등이 공식 목록에 있다. OS 27의 모델 저장 공간은 기기에 따라 최대 8GB 또는 14GB다. [S06](https://support.apple.com/en-us/121115) | Prompt API와 요약 등 기능별 API의 지원 목록이 다르다. Prompt 목록에는 Pixel 9~11 계열, Galaxy S26 계열, 일부 Fold/Flip 등이 있다. 실제 모델 버전도 기기별로 다르다. [S10](https://developers.google.com/ml-kit/genai) |
| 지역 | 중국 본토 구매 기기는 현재 Apple Intelligence를 사용할 수 없다. 본토 밖 구매 기기도 본토 체류와 Apple 계정 지역이 모두 본토이면 제한된다. [S06](https://support.apple.com/en-us/121115) | 검토한 문서는 통합 지역 보장표를 제시하지 않는다. 지역 무제한 지원을 확정하지 않았다. 기기 구성과 다운로드 상태를 확인해야 한다. [S10](https://developers.google.com/ml-kit/genai) |
| 언어 | 현재 Apple Intelligence 지원 언어에 한국어가 있다. 프레임워크에서 `supportedLanguages`와 요청 언어 지원을 확인한다. 한국어 행동 분할 품질은 미검증이다. [S06](https://support.apple.com/en-us/121115), [S19](https://developer.apple.com/documentation/foundationmodels/supporting-languages-and-locales-with-foundation-models?changes=_10_5) | 언어 가용성은 기기 구성과 내려받은 모델에 따라 달라질 수 있다. 본인 기기의 한국어 생성 지원·품질은 미검증이다. [S10](https://developers.google.com/ml-kit/genai) |
| 모델 가용성 | `SystemLanguageModel.default.availability`를 확인한다. 기기 부적격과 모델 준비 중 상태를 처리한다. 초기 모델 다운로드가 필요할 수 있다. [S08](https://developer.apple.com/documentation/foundationmodels/generating-content-and-performing-tasks-with-foundation-models?changes=_1) | `checkStatus()`로 사용 가능·다운로드 가능·다운로드 중·사용 불가를 확인한다. AICore 초기화와 서버 구성 다운로드가 끝나지 않으면 실패할 수 있다. 잠금 해제한 부트로더는 지원하지 않는다. [S18](https://developers.google.com/ml-kit/genai/prompt/android/get-started) |
| 앱 형태 | 네이티브 Swift API다. 모바일 웹에서 직접 호출하는 계약은 확인하지 못했다. 웹 UI와 결합하려면 네이티브 호스트를 별도로 설계해야 한다. [S20](https://developer.apple.com/videos/play/wwdc2025/286/) | Kotlin/Java Android 앱 라이브러리다. 모바일 웹 API가 아니다. [S18](https://developers.google.com/ml-kit/genai/prompt/android/get-started) |

Apple의 guided generation은 `@Generable`로 Swift 데이터 구조를 생성합니다.
기기 내 모델을 쓰면 추론 데이터가 기기에 남고 오프라인 실행이 가능합니다. [S20](https://developer.apple.com/videos/play/wwdc2025/286/)
앱이 추가한 온라인 도구·동기화·분석의 데이터 전송은 별도 설계 항목입니다.

Foundation Models에는 최신 OS의 Private Cloud Compute와 외부 공급자 경로도 있습니다.
이번 로컬 비교는 `SystemLanguageModel`만 다룹니다.
같은 프레임워크 이름을 쓴다는 이유로 모든 모델을 로컬로 분류하지 않습니다. [S21](https://developer.apple.com/documentation/foundationmodels?changes=l_3)

Android Prompt API는 텍스트와 구조화 출력을 제공하지만 beta에는 SLA와 폐기 정책 보장이 없습니다. [S09](https://developers.google.com/ml-kit/genai/prompt/android)
입력은 4,000토큰 미만이어야 합니다. 긴 완료 이력은 요약하거나 잘라야 합니다. [S18](https://developers.google.com/ml-kit/genai/prompt/android/get-started)
전경 서비스도 백그라운드 추론 제한을 우회하지 못합니다. [S10](https://developers.google.com/ml-kit/genai)

Chrome Prompt API의 기반 모델은 현재 Android와 iOS의 Chrome을 지원하지 않습니다.
초기 모델 다운로드에는 네트워크가 필요합니다. [S22](https://developer.chrome.com/docs/ai/prompt-api)
설계 판단: 이 API를 휴대폰 모바일 웹의 기본 로컬 경로로 선택할 근거가 없습니다.
WebGPU와 별도 모델 배포는 다른 경로이며 이번 조사에서 지원·라이선스·메모리를 검증하지 않았습니다.

## 기존 에이전트: 연결 계약과 추가 요소

### Codex

웹 조회 전에 로컬 설치를 좁게 확인했습니다.
`codex-cli 0.159.2`의 `--help`와 `app-server --help`를 읽었습니다.
`app-server`에는 stdio·Unix socket·WebSocket과 WebSocket 인증 옵션이 표시되었습니다.
호스트 인증 파일과 토큰은 읽거나 출력하지 않았습니다.
로컬 도움말만으로 SDK의 자식 프로세스 계약을 확인할 수 없어 공식 문서와 공식 GitHub 소스로 보완했습니다.

TypeScript SDK는 Node.js 18 이상에서 CLI를 자식 프로세스로 실행합니다.
stdin/stdout의 JSONL 이벤트로 통신하고, thread를 계속하거나 다시 열 수 있습니다.
턴별 `outputSchema`도 제공됩니다. [S11](https://github.com/openai/codex/blob/main/sdk/typescript/README.md)

App Server는 JSON-RPC 기반의 양방향 계약입니다.
연결마다 `initialize`와 `initialized`를 교환합니다.
`thread/start` 또는 `thread/resume` 뒤에 `turn/start`를 보냅니다.
완료와 도구 승인 등 이벤트를 계속 처리해야 합니다.
WebSocket은 실험 기능이며 운영 워크로드를 지원하지 않는다고 명시합니다.
원격 노출에는 인증을 설정해야 합니다. 기본 비루프백 연결의 무인증 허용 안내가 있습니다. [S23](https://developers.openai.com/codex/app-server/)

Codex의 ChatGPT 로그인과 API 키 로그인은 과금·워크스페이스·데이터 정책이 다릅니다.
API 키는 OpenAI Platform의 표준 API 요금을 사용합니다. [S13](https://developers.openai.com/codex/auth/)

### Claude

Claude Agent SDK는 Python 또는 TypeScript 런타임에서 에이전트 루프와 도구 실행을 제공합니다.
공식 quickstart의 최소 환경은 Python 3.10 또는 Node.js 18입니다.
API 키는 에이전트 프로세스의 환경에서 읽습니다. [S12](https://code.claude.com/docs/en/agent-sdk/quickstart)

개인 구독의 Agent SDK·`claude -p` 사용 안내와 제3자 제품의 로그인 제공 조건은 범위가 다릅니다.
구독 안내의 2026-06-15 변경은 중단되었고, 현재 기존 SDK 사용은 구독 한도를 사용한다고 적혀 있습니다.
같은 페이지의 이전 월간 SDK 크레딧 계획은 현재 적용되는 가격으로 읽으면 안 됩니다. [S24](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
SDK 문서는 사전 승인 없이 제3자 개발자가 제품에 claude.ai 로그인이나 구독 한도를 제공할 수 없다고 명시합니다.
따라서 개인 계정의 기존 CLI 사용 가능성을 일반 사용자의 Smallnext 구독 연동 권한으로 확대하지 않습니다. [S14](https://code.claude.com/docs/en/agent-sdk/overview)

Claude Code는 계정 종류와 개인정보 설정에 따라 데이터 학습·보관 정책이 달라집니다.
로컬 세션 기록도 저장합니다. PC에서 실행해도 모델 처리가 자동으로 로컬이 되지 않습니다. [S15](https://code.claude.com/docs/en/data-usage)

### 휴대폰과 실행 호스트 사이

설계 판단: 휴대폰 앱이 사용자의 PC CLI 프로세스를 직접 생성할 수 있다고 가정하지 않습니다.
호스트에 중계 프로그램을 두고 모바일 요청을 SDK 또는 App Server로 전달하는 구조를 검토할 수 있습니다.
공식 SDK가 Smallnext의 PC 연결 중계·페어링·모바일 인증을 대신 제공한다는 근거는 확인하지 못했습니다.
PC 전원, 프로세스 재시작, 네트워크 도달성, 토큰 갱신, 실행 취소, 세션 복구를 설계해야 합니다.
백엔드 호스트를 쓰면 개인 PC의 기존 파일·로그인 상태를 자동으로 공유하지 않습니다.

Codex MCP 문서는 Codex가 외부 도구 서버에 연결하는 stdio·Streamable HTTP 계약을 제공합니다. [S25](https://developers.openai.com/codex/mcp/)
설계 판단: Smallnext를 MCP 도구 서버로 노출하는 방향과, Smallnext가 에이전트를 호출하는 방향을 구분합니다.
MCP라는 이름만으로 에이전트 구독 사용권, 기존 대화 접근권, 원격 CLI 실행권이 생기지 않습니다.

## 별도 preview: Sign in with ChatGPT의 구독 추론

현재 공식 문서는 오픈소스·로컬 호스팅 앱에 ChatGPT plan usage 경로를 안내합니다.
사용자의 별도 동의로 적격 Responses API 요청에 구독을 사용할 수 있습니다.
기존 ChatGPT 대화나 계정 문맥 접근권은 제공하지 않습니다.
유료 또는 원격 호스팅 앱은 별도 문의 경로가 있습니다. [S26](https://developers.openai.com/siwc/token-sharing-open-source)

공개 클라이언트 등록, 호스트 ID, PKCE, 사용자 동의와 발급 토큰 검증이 필요합니다.
문서의 직접 등록은 HTTP loopback 콜백을 요구합니다. [S27](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
HTTP 호출은 `store:false`, `stream:true`와 필요한 이력 전체 전송을 요구합니다.
WebSocket의 이어받기는 같은 인증 연결 안에 제한됩니다.
앱이 OAuth 토큰을 갱신해야 하며 일부 도구·필드가 지원되지 않습니다. [S28](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

설계 판단: 이 preview를 일반 API 키 경로 또는 PC 에이전트 연결과 같은 계약으로 취급하지 않습니다.
모바일 OAuth 콜백, 앱 배포 형태, 계정·워크스페이스 허용 범위는 실제 검증하지 않았습니다.
사용자 구독만으로 모바일 앱 연동이 자동 허용된다고 결론 내리지 않습니다.
채택 검토 시 preview 정책과 모바일 등록·배포 조건을 다시 확인합니다.

## 비용 조회와 첫 버전의 미정 항목

조회일: 2026-10-03. 단위: USD / 텍스트 100만 토큰. 아래 값은 선택을 위한 예시입니다.

| 경로·모델 예시 | 입력 | 캐시 입력 | 출력 | 공식 근거 |
| --- | ---: | ---: | ---: | --- |
| OpenAI GPT-5.4 mini | $0.75 | $0.075 | $4.50 | [S29: 현재 모델 단가](https://developers.openai.com/api/docs/models/gpt-5.4-mini) |
| Claude Haiku 4.5의 API 키 호출 | $1.00 | $0.10 | $5.00 | [S30: 현재 API 단가](https://platform.claude.com/docs/en/about-claude/pricing) |
| Apple 기기 내 시스템 모델 | 요청 요금 없음 | 해당 없음 | 요청 요금 없음 | [S07: 기기 내 요청 안내](https://developer.apple.com/videos/play/meet-with-apple/205/) |
| Android ML Kit 기기 내 모델 | 추가 서버 호출 요금 없음 | 해당 없음 | 추가 서버 호출 요금 없음 | [S10: 기기 내 처리 안내](https://developers.google.com/ml-kit/genai) |

캐시 쓰기, 도구, 처리 지역, 과금 모드에 따라 추가 비용이 발생할 수 있습니다.
API 가격을 Codex·Claude의 구독 한도나 SDK 크레딧 가격으로 환산하지 않습니다.
첫 버전의 모델, 호출 횟수, 입력·출력 토큰량은 미정입니다. 실제 월 비용은 아직 계산할 수 없습니다.
반복 분할과 재시도도 호출량에 포함해야 합니다. 백엔드·호스트 운영비와 기기 비용은 별도입니다.

## 사용자 결정 티켓에 넘길 항목

1. 첫 앱 형태와 본인 휴대폰의 모델·OS를 정합니다.
2. 업무·학습·개인 프로젝트 문맥 중 외부 전송을 허용할 범위를 정합니다.
3. 서버 API, 기기 내 모델, 기존 에이전트 중 첫 필수 경로를 정합니다.
4. 공급자와 모델은 별도 사용자 결정 티켓에서 선택합니다.
5. 월 예산, 호출 상한, 실패·미지원 상태의 대체 흐름을 정합니다.

설계 판단: 서버 API는 기기별 로컬 모델 지원 조건의 영향을 줄입니다.
로컬 경로는 대상 기기와 한국어 행동 분할 평가를 통과해야 합니다.
기존 에이전트 경로는 연결 중계의 유지 비용까지 수용할 때 선택할 수 있습니다.
어느 경로든 업무·학습·개인 프로젝트의 실제 문맥으로 행동 타당성을 따로 검증해야 합니다.

## 출처와 확인 한계

위 링크의 확인일은 모두 2026-10-03입니다. 공식 문서·공식 소스만 판단 근거로 사용했습니다.
OpenAI의 기존 Codex 문서 URL은 조회 시 공식 ChatGPT Learn 문서로 이동했습니다.
Apple 문서 일부는 자동 열기에서 JavaScript 안내만 반환했습니다.
해당 내용은 공식 검색 결과, Apple 지원 문서, 공식 세션 전사로 교차 확인했습니다.

| 출처 묶음 | 확인한 범위 | 검증하지 못한 범위 | 재검토 조건 |
| --- | --- | --- | --- |
| S01~S04·S16·S29~S30 | API 출력·인증·보관 정책·현재 단가 | 본인 계정의 모델 권한, 할인, 할당량, 실제 청구 | 공급자·모델·인증 계약을 선택할 때 |
| S05~S08·S17·S19~S21 | Apple 시스템 모델, OS별 변경, 기기·언어·지역 조건 | 본인 기기의 설치 상태, 한국어 품질, 지연·전력 | 대상 기기를 정하거나 OS·모델이 바뀔 때 |
| S09~S10·S18·S22 | Android beta·기기·전경·토큰 제약, Chrome 모바일 제한 | 실제 AICore 구성, 지역별 제공, 한국어 분할 품질 | 대상 기기를 정하거나 지원 목록이 바뀔 때 |
| S11~S15·S23~S25 | SDK·CLI·App Server·MCP 계약, 구독과 제3자 제품의 구분 | 실행 호스트, 모바일 연결 중계, 계정 정책의 실제 적용 | 기존 에이전트 연결을 필수로 정할 때 |
| S26~S28 | SIWC preview의 OSS·로컬·OAuth·이력 제약 | 모바일 등록·콜백·배포 승인, 실사용 비용·한도 | 구독 추론을 채택하거나 preview가 변경될 때 |
