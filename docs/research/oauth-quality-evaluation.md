# 수동 구독 OAuth 품질 평가 #97

[#97](https://github.com/minjunkim-dev/smallnext/issues/97)의 합성 회귀 실행기다.
Python 3 표준 라이브러리와 기존 로그인된 Claude Code를 사용한다.
`claude-haiku-5-5`, `xhigh`, `claude.ai` 구독 OAuth를 유지한다.
API 키를 읽거나 토큰을 추출하지 않는다.
기본 CI는 오프라인 회귀 테스트만 실행한다.
`run` 명령만 실제 구독 모델 호출을 시작한다.

## 재실행

저장소 루트에서 실행한다. 디렉터리 이름은 매번 새로 지정한다.
`work/`는 Git에서 제외한다. 입력은 저장소의 합성 fixture만 사용한다.
다른 checkout에서도 개인 경로를 수정할 필요가 없다.
`claude`가 PATH에 없으면 `run`에 `--claude <실행 파일>`을 지정한다.

1. `python3 -m unittest discover -s scripts -p test_oauth_quality.py`를 실행한다.
2. `python3 scripts/oauth_quality.py freeze work/qa-quality --suite quality`로 호출 조건을 고정한다.
3. `python3 scripts/oauth_quality.py verify work/qa-quality`로 동결 해시를 확인한다.
4. `python3 scripts/oauth_quality.py run work/qa-quality`로 수동 평가를 실행한다.
5. `work/qa-quality/summary.json`과 `results/*.json`에서 전체 결과를 확인한다.

입력·참조·후보·역할 지시·공통 계약·스키마·모델·effort·시간 제한·실행 순서를 호출 전에 고정한다.
`manifest.json`에는 원본 UTF-8 바이트와 SHA-256을 저장한다.
`integrity.json`은 manifest 파일 바이트의 SHA-256이다.
각 역할 결과에는 payload·조립 프롬프트·실제 사용 스키마의 SHA-256이 있다.
검사 프롬프트는 `check.md` 바이트 + LF 하나 + `contract.md` 바이트다.
생성 스키마의 상태는 요청 종류별 기존 허용 상태로 제한한다.
이미 동결한 디렉터리와 이미 실행한 결과는 덮어쓰지 않는다.
실패·취소한 실행도 다시 시작하지 않는다. 새 실행은 별도 디렉터리를 사용한다.
이전 실행도 함께 보고한다. 통과 결과를 고르지 않는다.

## 품질과 참조

품질 suite는 기존 고정 검사 31개와 막힘 해결 대조 2개를 검사한다.
생성·독립 검사 14개도 실행한다. 최대 역할 호출은 61개다.
동시에 실행하는 사례는 2개다. 사례별 생성과 검사는 순차 실행한다.
각 사례의 전체 시간 제한은 120초다. 검사에 새 120초를 부여하지 않는다.
생성의 구조·보존 검사를 통과한 후보만 독립 검사에 보낸다.
독립 검사는 전체 원래 요청과 후보를 다섯 기준으로 검사한다.
수용은 다섯 기준과 비어 있지 않은 근거·이유를 요구한다.
모델 payload에는 `original_request`와 `candidate`만 넣는다.
생성 payload에는 원래 입력만 넣는다.
fixture의 사례 ID·설명·참조·`expected`·`expected_statuses`는 보내지 않는다.

[기존 #96 기록](checker-latency-diagnosis.md)의 Rust 통합 결과는 수용 14/14, 상태 참조 일치 **13/14**다.
원래 fixture, 로컬 결과와 `matched=false`를 유지한다.
[참조 기록](fixtures/oauth-quality-references.json)은 이전 불일치와 원래 summary 해시를 보존한다.
이 실행기의 참조는 이전 결과를 소급 수정하지 않는다.

`useful-minimum-known`의 이전 참조는 `minimum`만 허용했다.
기존 공통 계약 criterion 4는 실제 막힘을 해결하는 `action`도 허용한다.
따라서 이후 실행에서는 `action`과 `minimum`을 허용한다.
둘 다 책 한 권을 두 손으로 들어 아래 칸에 놓는 유용한 결과와 막힘 해결이 필요하다.
두 손 방법의 `action` 수용과 한 손 방법의 `action` 거절을 고정 후보로 따로 검사한다.
허용 상태만으로 성공 처리하지 않는다. 독립 검사 다섯 기준을 모두 적용한다.
새 참조 일치와 기존 상태 참조 일치를 별도 집계한다.
이 참조는 계약을 해석한 합성 회귀다. 제품 결정 변경이나 일반 품질 승인이 아니다.

## 검사 지연 #96

원래 보고서 입력과 이미 생성한 후보 두 개를 그대로 사용한다.
새 후보를 생성하지 않는다. 입력 상태 문장도 바꾸지 않는다.

```sh
python3 scripts/oauth_quality.py freeze work/qa-latency --suite latency --repetitions 4
python3 scripts/oauth_quality.py run work/qa-latency
```

이 명령은 같은 기존 검사를 후보별 4회씩 재현한다.
하네스 구현만으로 지연 개선을 주장하지 않는다.
검사 역할 지시를 비교할 때는 동결 명령에 `--comparison-role <역할 지시 파일>`을 추가한다.
두 변형 모두 동일 공통 계약·입력·후보·스키마·모델·effort를 사용한다.
기존→비교, 비교→기존 순서를 후보와 반복별로 뒤집는다.
반복 2회는 후보 2개 × 변형 2개 × 2회로 총 8호출이다.
모든 표본과 판정을 보고한다. 초기 2표본만으로 개선을 확정하지 않는다.
30초는 #96의 진단 표시다. 제품 SLA와 자동 인수 조건이 아니다.

## 실패와 보안 경계

실제 `modelUsage`가 Haiku 5.5 하나인 구조화된 성공 결과만 사용한다.
도구·MCP·hook·slash command·세션 저장을 비활성화한다.
임시 빈 디렉터리에서 CLI를 실행한다. 서비스 공급자 설정은 바꾸지 않는다.
환경에는 CLI 로그인과 네트워크에 필요한 기존 값만 전달한다.
API 키 환경 변수와 임의 Claude 설정 환경 변수는 전달하지 않는다.
추론 원문, 제공자 오류 원문, 계정 이메일, 자격 증명은 저장하지 않는다.
추론 delta의 문자 수와 시점만 집계한다.
구조화된 제안·검사 결과는 합성 입력의 평가 자료다.
로그인 상태 조회는 인증 방식만 검사한다. 원문을 산출물에 쓰지 않는다.

제공자 메시지·재시도·추가 요청·`max_tokens`를 별도 집계한다.
추가 메시지나 재시도를 관측하면 중단한다. 자동 재생성은 없다.
시간 초과와 SIGINT·SIGTERM 취소는 CLI 프로세스 그룹을 종료하고 자식을 회수한다.
프로세스 회수 여부와 남은 프로세스 그룹을 결과에 기록한다.
SIGKILL·호스트 종료는 이 취소 처리의 검증 범위 밖이다.
메시지 수는 스트림에서 관측한 수다. 응답 전 실패한 네트워크 요청을 모두 증명하지 않는다.

이 실행기는 Claude CLI 생성·검사를 직접 평가한다.
Rust HTTP·DB 연결, iOS 화면, 실기기, 접근성과 운영 배포는 검증하지 않는다.
피처 플래그 기본값은 모두 OFF다.
원래 Rust 통합 증거를 이 실행기의 직접 CLI 결과로 대체하지 않는다.
