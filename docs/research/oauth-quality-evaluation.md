# 수동 구독 OAuth 품질 평가 #97

실제 Rust HTTP/iOS 경로의 어댑터와 검증 경계는
[HTTP/iOS 검사 지연 진단](http-ios-checker-latency.md)을 참조한다.
후속 형식 오류 재현과 공통 출력 지시 회귀는
[단일 JSON 출력 형식 진단](oauth-output-format-diagnosis.md)을 참조한다.
현재 결정 출력 계약과 후속 교차 측정은
[결정 출력 품질·지연 검증](oauth-decision-validation.md)을 참조한다.

[#97](https://github.com/minjunkim-dev/smallnext/issues/97)의 합성 회귀 실행기다.
Python 3 표준 라이브러리와 기존 로그인된 Claude Code를 사용한다.
macOS·Linux의 POSIX 프로세스 그룹을 사용한다. Windows는 지원하지 않는다.
`claude-haiku-5-5`, `xhigh`, `claude.ai` 구독 OAuth를 유지한다.
API 키를 읽거나 토큰을 추출하지 않는다.
기본 CI는 오프라인 회귀 테스트만 실행한다.
`run` 명령만 실제 구독 모델 호출을 시작한다.

## 보충·재요청 혼합 계획의 오프라인 준비 #286

[#286](https://github.com/minjunkim-dev/smallnext/issues/286)은 기존 실행·보고 경계에서
C1(검사 단독)과 G1+C1(생성+검사)을 순차 실행하는 준비 구현이다.
새 계획은 `version: 2`, `plan_kind: supplemental`과
[#111의 확정 계약](https://github.com/minjunkim-dev/smallnext/issues/111#issuecomment-6385071594)으로 구분한다.
기존 축소 계획의 형식과 실행·보고 경로는 유지한다.

오프라인 테스트는 임시 합성 `flows`를 기존 `freeze` 함수에 전달하고 `run`의 모의 호출·시계를 사용한다.
각 합성 단위는 `kind: check` 또는 `generate_check`, 반복 번호(1~3), 입력·기대 의미를 가지며,
검사 단독에는 고정 후보가 있다. 이 단계는 단위당 한 요청만 지원한다.
정식 9후보 참조·8보충 흐름과 전이는 #287에서 준비한다.
계획 허용량은 최대75단위·G48/C75·123역할이다. 실제 시작 수와 공급자 메시지/재시도 관측은 별도 집계하며,
생성 실패 뒤 시작하지 않은 검사는 미실행 사유로 남긴다. 남은 호출 수를 채우지 않는다.
역할 기록을 저장한 뒤 호출 직전에 기한·취소·소유권·호출 여유를 다시 확인한다.
기록만 남기고 호출을 시작하지 못한 역할은 영수증에 구분하고 실제 시작 수에서 제외한다.

G+C는 합계180초, C단독은120초이고 전체 반복은 첫 입장부터 하나의 단조 시계5400초를 공유한다.
기록·전환·정리 시간도 전체 경과에 포함한다. 기한 도달 시 진행 호출을 취소하고 회수를 기다리며,
안전한 정리가 상한을 넘긴 실제 시간도 보존한다. 보고의 `planned`, `units`, `role_counts`,
`provider_observations`, `elapsed_seconds`가 계획·시작·완료·실패·취소·미실행을 연결한다.

`freeze --plan-kind supplemental`과 새 계획의 실제 `run`은 준비 미완료로 차단한다.
#287~#289의 정식 계획·8192 지원 근거·통합 준비가 남아 있으며 모의 검증은 실제 호출 허가가 아니다.
실제 평가용 freeze/run·모델 호출·유료 API·실기기·배포, 기존 결과·직접 판정·삭제 기한은 이 작업 범위에 없다.

## 출시 흐름 준비 #113

`scripts/launch_evaluation.py`는 [#47의 확정 답](https://github.com/minjunkim-dev/smallnext/issues/47#issuecomment-6103771425)에 따른 순차 실행 경로다.
기존 47건 회귀와 출시 흐름을 섞지 않는다. 기존 fixtures·참조·결과를 수정하지 않는다.
동결 디렉터리의 `regression/`에는 기존 47건의 별도 동결 판을 저장한다. 이를 자동 호출하지 않는다.
이 판은 `--sequential`과 같은 순차·첫 실패 중단 조건을 동결한다.
출시 흐름 실행에서는 고정 참조와 다른 자동 판정(예상 밖 품질)이 그 흐름만 종료하고 다음 흐름을 계속한다([#236](https://github.com/minjunkim-dev/smallnext/issues/236#issuecomment-6318856612)).
기존 독립 품질 평가의 기본 병렬 실행은 유지한다. 중단 뒤 미실행 사례를 성공으로 집계하지 않는다.
첫 행동부터 상태가 허용하는 축소만 수행한다. 질문·최소 작업·허용된 대안 없음에서 종료한다.
가짜 답변·완료 기록·행동 결과·별도 smoke·계획 밖 재시도를 추가하지 않는다.
기존 대표 목표 입력은 #3·#6의 합성 검증 맥락이다. 개인의 실제 기여나 수행을 확인한 사실이 아니다.
추가 목표는 #47의 새 시작 시점이다. 과거 `smaller`·`next_action` 상태를 그대로 사용하지 않는다.

1. `python3 -m unittest discover -s scripts -p test_launch_evaluation.py`로 모의 회귀를 실행한다.
2. 새 `work/` 디렉터리, Issue 담당자, 평가 종료 기준 시각과 삭제 방법을 지정한다.
3. `freeze`로 입력·기대 의미·종료·지침·공통 계약·schema·모델·실행기·측정법·상한·보관을 동결한다.
4. #115의 착수 조건을 확인한 뒤 `run`으로 구독 OAuth 평가를 시작한다. 지금 준비 작업에서는 호출하지 않는다.
5. `report`로 부분 결과나 화면 관측을 집계한다. 모델을 호출하거나 중단 판을 재개하지 않는다.

동결 명령 예시는 다음과 같다. 구독 실행에는 µUSD 상한이 없다. 첫 평가 3 USD·월 10 USD 한도는 운영 API 키 경로에만 적용한다([#251](https://github.com/minjunkim-dev/smallnext/issues/251#issuecomment-6330074544)).
종료 시각은 실행 전에 미래의 기준 시각으로 지정한다. 기본 실행 경로는 구독 OAuth다.

```sh
python3 scripts/launch_evaluation.py freeze work/launch-new \
  --owner minjunkim-dev --ends-at '<timezone-qualified future timestamp>' \
  --delete-method '이 private 디렉터리를 삭제한다'
python3 scripts/launch_evaluation.py run work/launch-new
python3 scripts/launch_evaluation.py report work/launch-new --observations work/screen-observations.json
```

한 흐름만 다시 실행하려면 동결에 `--flow <흐름 ID> --max-smaller <회수>`를 더한다.
요청 상한은 회수+1개, 역할 호출 상한은 그 두 배다. 예: `--flow fixed-ready-1 --max-smaller 1`은 요청 2개·호출 4개다([#154](https://github.com/minjunkim-dev/smallnext/issues/154)).
요청당 생성·검사 제한은 기본 120초다. 동결에 `--pipeline-seconds 180`을 더하면 180초로 늘린다. #259의 grounding으로 역할 출력이 길어져 QA 측정에서만 허용한다([#261](https://github.com/minjunkim-dev/smallnext/issues/261)). 서버의 120초 제한은 그대로이므로, 180초 판의 지연은 운영 제한 기준으로 따로 기록한다.
생성 결과에는 검사 전용 `facts`·`reduction` 칸이 있다([#259](https://github.com/minjunkim-dev/smallnext/issues/259)). 다음 smaller 요청의 `previous_proposals`에는 앱처럼 9필드만 넣는다.
기존 회귀 47건의 fixture 파일은 그대로 둔다. 동결할 때 `grounded-checker-candidates.json`이 checker 후보 33건에 두 칸만 더하고 기대 판정은 바꾸지 않는다([#260](https://github.com/minjunkim-dev/smallnext/issues/260)). 이 파일은 checker 사례 id와 정확히 같아야 한다.
이 변경으로 `oauth_quality.py` SHA가 `1e2d25eb…`에서 `375f9752e5512160c1b1e55cb33ade85ebd41cc8a31ad1b00e1ac92e4af89ea1`로 바뀌었다. 취소·종료·회수·오류 판정 코드는 그대로이고 `freeze`의 입력 조립만 바뀌었으므로 재판정 `PROTOCOLS`에 같은 `cancellation-marker-v1`로 등록했다.
생성·검사 역할은 모두 `claude-haiku-5-5`다. #252의 생성 역할 모델 분기는 #251 변경 답에 따라 제거했다. #258에서 `oauth_quality.py`를 이미 등록된 `1e2d25eb…` 바이트로 되돌렸고, #260에서 위와 같이 다시 바뀌었다.
예시의 `work/`는 [보관 규칙](../WORKFLOW.md#검증과-문서-관리)의 위치다. worktree에서는 그 절대 경로를 지정한다.
같은 실행 판의 재실행과 덮어쓰기를 거부한다. 같은 위치의 `launch-model.lock`으로 worktree 사이의 하네스 실행 소유권을 배타적으로 유지한다.
별도 clone과 수동 모델 호출도 겹치지 않게 운영한다. 이 잠금이 외부 호출까지 잠그지는 않는다.
소유권 상실·취소·timeout에서 기존 구독 실행기가 자식 프로세스 그룹을 정리한다.
제안 요청과 역할 호출의 시작 기록을 먼저 저장한다. 잘린 결과와 누락한 결과를 성공으로 처리하지 않는다.
예상 밖 품질 외의 모든 오류(출력·모델·사용량 미확인·timeout 등)·취소·소유권 상실과 상한에서는 전체 실행의 다음 호출을 차단한다. 예상 밖 품질이 있으면 모든 흐름을 실행해도 자동 통과가 아니다.
미실행 검사 역할은 시작 호출에 넣지 않는다.
전송이 비용 추정치를 주면 합계로, 주지 않으면 미확인 역할 수로 기록만 한다. 현재 구독 CLI 전송은 추정치를 주지 않으므로 모든 역할이 미확인이다. 역할별 토큰 사용량은 `role_usage`로 남는다. 비용은 실행을 멈추지 않으며 실제 청구는 미확인이다.
유료 전송 구현은 없다. `paid-preflight`는 별도 서버 직전 단계와 준비 조건을 오프라인으로 확인할 뿐이다.
이 결과로 키 생성·유료 호출·배포를 시작하지 않는다.

화면 관측 파일은 JSON 배열이다. 각 항목은 `run_id`, `request_id`, `observed_upper_seconds`,
`sample_interval_seconds`, `method`, `display_observed: true`, `evidence_path`, `evidence_sha256`을 포함한다.
`evidence_sha256`은 실제 결과 화면 증거 파일의 SHA-256이다. 원문·화면 증거는 private 묶음에 보관한다.
`evidence_path`는 private 묶음 안의 상대 경로다. 보고기는 파일 존재와 실제 SHA-256을 대조한다.
파일 누락·경로 이탈·symlink·정규 파일이 아닌 증거·해시 차이를 거부한다.
private 디렉터리 descriptor를 기준으로 열고 같은 파일 descriptor의 타입과 해시를 검사한다.
보고 시작부터 종료까지 같은 번들 descriptor를 유지한다. 제어·메타데이터·결과·호출 수·증거를 이 descriptor에서 읽는다.
집계 전에 하위 디렉터리·결과·제어·증거 파일을 열어 고정한다. 요청·호출 JSON 이름 목록도 고정한다. 파일을 연 뒤 부모 descriptor를 닫는다.
열거한 결과 파일의 inode·device를 열린 파일과 대조한다. 열거 후 파일 교체를 발견하면 그 기록을 격리한다.
제어 JSON은 object로 읽는다. 화면 관측 JSON은 array로 읽고 method 문자열을 검사한다. 타입 오류는 안전한 CLI 오류로 종료한다.
결과는 동결 생성·검사 계약과 참조를 다시 검사한다. 역할 출력·요약·종료가 다르면 격리한다. 종료 예산은 필수 숫자·기준·청구 미확인을 검사한다.
요청은 실행 ID·흐름·단계·동결 입력 hash에 연결한다. 역할은 시작 marker와 정산 후 `.receipt`의 결과 hash를 대조한다. 이전 유효 제안으로 축소 입력을 재구성한다.
marker와 receipt는 최대 4 KiB의 바이트로 고정한다. 로컬 하네스의 호출 기록이다. 공급자 인증이나 청구 증명은 아니다.
이미 수락한 요청 ID를 가진 중복 결과는 해당 파일만 격리한다. 정상 결과·사용량·시간 집계를 보존하고 자동 통과를 차단한다.
정규 결과 파일명은 요청 시작 순서로 고정하고 요청 기록에 연결한다. 먼저 정렬되는 복사본도 원본을 대체하지 못한다.
결과 저장 후 요청 완료 `.receipt`에 결과 전체의 canonical JSON hash를 원자적으로 기록한다. 정규 경로 교체·완료 기록 누락·hash 불일치는 해당 결과만 격리한다.
같은 계정이 결과와 모든 증거를 일관되게 다시 쓰는 공격은 이 로컬 기록의 인증 범위 밖이다.
결과를 열 때 바이트 hash를 저장한다. 읽은 바이트가 다르면 격리한다. 완료 비용 추정치와 비용 미확인 역할 수는 호출 기록에서 다시 합산한다.
완료 실행의 요청·역할 수는 실행 한도를 넘을 수 없다.
순차 요청 시간 합계가 90분을 넘으면 자동 통과하지 않는다. 요청 사이 대기를 제외한 하한으로 검사한다.
번들 경로도 `/` 또는 현재 디렉터리 descriptor부터 각 요소를 연다. 경로의 symlink와 `..`를 거부한다.
보고에는 symlink가 없는 실제 경로를 지정한다. macOS 임시 경로 `/var`는 `/private/var`를 사용한다.
결과 JSON과 시작·종료 메타데이터도 같은 정규 파일·경로 검사를 사용한다.
동결 manifest·integrity·regression manifest와 관측·준비 조건 JSON도 같은 제한 읽기를 사용한다.
소유권 기록을 안전하게 읽을 수 없으면 다음 역할을 호출하기 전에 취소한다.
보고 JSON은 파일 크기와 제한된 읽기로 16 MiB를 넘기기 전에 차단한다.
손상·초과·깊이 오류가 있는 결과를 격리한다. 시작·종료 메타데이터를 읽을 수 없으면 보고를 중단한다.
종료 기록이 없거나 reason이 completed가 아니면 자동 통과하지 않는다.
파일 내용이 실제 결과 화면인지는 관측 담당자가 확인한다.
상태 변경 콜백이나 서버 응답만으로 `display_observed`를 설정하지 않는다.
기본 보고서에는 실제 표시 증거가 없다. 화면 응답은 미확인이다.
검사·참조를 통과한 표본과 연결한 실제 화면 관측만 정상 화면 집계에 포함한다.
첫 행동·축소·다른 요청과 실패·거부·불확실·취소 시간을 구분한다.
중앙값·nearest-rank p90과 표본 부족 처리는 #47의 기준을 따른다.
구조 검사·모델의 다섯 기준·상태/판정 참조 대조·사람 검토를 구분한다. 자유 문장은 정확한 문자열로 채점하지 않는다.
`automatic_passed`는 하네스의 자동 검사다. `quality_passed`는 사람 검토 전까지 미확인이다.
서버 시간으로 화면 SLA를 통과시키지 않는다. `paid_budget_verified`는 항상 false다.

새 원문 묶음은 Git에 넣지 않는다. 디렉터리는 0700이고 파일은 0600이다.
평가 종료 기록의 `delete_by`는 실제 종료 후 최대 30일이다. 담당자와 삭제 방법은 manifest에 있다.
기존 공개 합성 근거는 삭제하지 않는다. #47·#111은 종료하지 않는다. #61 실기기 보류와 기본 OFF를 유지한다.
구독 개발 검증과 사람 검토·서버 준비 양식은 [#115 보고](subscription-launch-validation.md)를 참조한다.

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
실행기 소스도 동결한다. 실행기 버전이 다르면 실행을 거부한다.
`integrity.json`은 manifest 파일 바이트의 SHA-256이다.
각 역할 결과에는 payload·조립 프롬프트·실제 사용 스키마의 SHA-256이 있다.
기본 검사 역할 지시는 `check.md` 바이트 + LF 하나 + `contract.md` 바이트다.
`text-json` 방식은 같은 지시 뒤에 JSON 출력 형식과 같은 스키마를 붙인다.
역할 결과의 프롬프트 해시는 이 실제 전송 지시의 해시다.
생성 스키마의 상태는 요청 종류별 기존 허용 상태로 제한한다.
이미 동결한 디렉터리와 이미 실행한 결과는 덮어쓰지 않는다.
실패·취소한 실행도 다시 시작하지 않는다. 새 실행은 별도 디렉터리를 사용한다.
이전 실행도 함께 보고한다. 통과 결과를 고르지 않는다.
프로세스가 종료됐는데 summary가 없으면 `python3 scripts/oauth_quality.py summarize <동결 디렉터리>`로 부분 결과를 집계한다.
이 명령은 모델을 호출하지 않는다. 기존 결과를 덮어쓰지 않는다.
누락한 사례가 있으면 `passed=false`다. 실행 중인 프로세스의 집계는 거부한다.
새 실행과 같은 실행기 버전의 복구는 같은 결과 판정을 사용한다.
참조 결과가 맞아도 오류·취소·시간 초과·프로세스 정리 실패가 있으면 `passed=false`다.
빈 `error` 필드도 실패다. CLI PID가 있으면 `process_reaped=true`와 `process_group_alive=false`를 모두 확인한다.
실행 전에 취소한 호출은 취소로 분류한다. 실행 중 받은 취소는 `run-cancelled.json`에 보존하고 복구에서도 통과를 막는다.
순차 조기 중단과 병렬 실행 방식은 유지한다. 이 복구 명령은 과거 기록의 새 규칙 재판정을 수행하지 않는다.
잘린 JSON·잘못된 UTF-8 파일은 `unreadable_records`로 보고한다. 다른 정상 기록은 집계한다.
잘린 파일은 덮어쓰지 않는다. 해당 파일의 호출 수와 비용은 확인할 수 없다.
JSON은 같은 디렉터리의 임시 파일에 완전히 쓴 뒤 hard link로 원자적으로 게시한다.
기존 경로는 교체하지 않는다. 출력 파일시스템은 hard link를 지원해야 한다.

## 과거 기록의 오프라인 재판정 #187

[#187](https://github.com/minjunkim-dev/smallnext/issues/187)의 별도 명령은 version 1의 전체 OAuth 품질 평가 폴더 한 개를 읽는다.
문서용 축약 JSON과 `launch_evaluation` 묶음은 지원하지 않는다.
기존 실행·복구의 현재 실행기 SHA 검사는 유지한다. 동결 원문과 모델을 실행하지 않는다.

```sh
python3 scripts/rejudge_oauth_quality.py --frozen /ABSOLUTE/FROZEN_DIRECTORY \
  --output /ABSOLUTE/NEW_OUTPUT_DIRECTORY
```

출력 디렉터리는 입력 폴더 밖에 둔다. 결과는 `report.json`에 저장한다.
원본과 기존 결과를 덮어쓰지 않는다. 같은 입력·정책·결과의 재요청만 재사용한다.
보고서는 입력 바이트의 SHA, 적용 정책 SHA, 원래 판정·새 판정·차이 이유를 기록한다.
새 SHA는 이번에 읽은 바이트를 식별한다. 과거 결과의 진위나 실제 모델 실행을 증명하지 않는다.
민감한 입력·출력·error 원문은 새 보고서와 진단에 넣지 않는다.

새 판정은 `passed`·`failed`·`indeterminate`다.
명백한 오류·취소·시간 초과·프로세스 정리 실패는 `failed`다. 빈 error도 실패다.
지원한 단일 호출은 subcalls가 없어도 검사한다.
취소 기록 방식이나 호출 종료 근거가 불명하면 `indeterminate`다. 누락 증거를 정상값으로 채우지 않는다.
모든 기록이 통과하면 종료 코드 0이다. 실패·판정 불가가 있으면 1이다. 입력·출력 거부는 2다.

합성 폴더를 통한 명령 실행으로 원본 보존·실행기 버전 차이·실패·누락·재사용을 검증한다.
실제 과거 기록에는 적용하지 않았다. 실제 모델·유료 API·운영 배포·#61 실기기 검증은 별도다.

## 추가 메시지 진단과 출력 방식 #96

기본 출력 방식은 결정 출력 계약의 `structured`다. 과거 45/47와 Rust 13/14 기록을 바꾸지 않는다.
이전 단일 JSON 전송 방식은 `--output-mode text-json`으로 지정한다.
현재 실행기는 어느 전송 방식에서도 결정 출력 계약을 적용한다.
과거 실행 전체를 재현하려면 해당 기록에 고정된 실행기 소스를 사용한다.
`--case <기존 ID>`를 반복 지정하면 원인 점검에 필요한 사례만 호출 전에 고정한다.
예를 들어 `freeze work/qa-probe --suite quality --case replacement-empty-invalid --case generate-next`를 사용한다.
이 부분 평가를 전체 47개 품질 평가로 보고하지 않는다.

`freeze work/qa-text --suite quality --output-mode text-json`은 단일 JSON 응답을 평가한다.
Claude CLI의 `--json-schema` 형식 도구를 사용하지 않는다.
대신 같은 스키마를 출력 지시에 넣고 로컬에서 같은 스키마를 엄격히 검증한다.
중복 키·Markdown·복수 JSON·잘못된 타입·누락·추가 필드를 거부한다.
자동 수정·재생성·자동 수용을 수행하지 않는다.
실제 모델·한 메시지·120초 전체 제한·다섯 기준·범위·완료 ID·미완료 플래그를 계속 확인한다.

같은 후보의 출력 방식 교차 측정은 다음 절차를 사용한다.

1. `python3 scripts/oauth_quality.py freeze work/qa-output-paired --suite latency --output-mode structured --comparison-output text-json --repetitions 3`을 실행한다.
2. `python3 scripts/oauth_quality.py verify work/qa-output-paired`를 실행한다.
3. `python3 scripts/oauth_quality.py run work/qa-output-paired`를 실행한다.
4. 양쪽의 전체 판정과 실패를 확인한 뒤 각 API 중앙값을 비교한다.

`output_modes`도 manifest에 고정한다. 이 대조는 같은 역할 지시·공통 계약·스키마·입력·후보를 사용한다.
같은 기존 후보 두 개를 각 방식으로 3회 실행한다. 순서는 AB/BA로 교차한다.
성능 측정 중 다른 실제 모델 호출을 함께 실행하지 않는다.
출력 방식 변경은 모델·effort 변경이나 검사 기준 생략이 아니다.

`trace`는 이벤트 종류·시간·동일 message ID의 중복 여부·스키마 유효성·오류 필드명·도구 오류 여부만 저장한다.
`block_seconds`는 추론·출력 구간 시간이다. 추론 원문·오류 원문·message ID 원문·잘못된 출력 값은 저장하지 않는다.
구조화 도구의 첫 인수에서 중복 키와 스키마 오류를 검출하면 즉시 중단한다.
`--max-turns 1`과 추가 메시지 차단도 적용한다. 잘못된 출력을 자동 수정하지 않는다.
후속 측정과 검증 경계는 [출력 오류와 검사 지연 재검증](checker-output-diagnosis.md)을 참조한다.
기존 summary가 잘렸으면 원본을 보존하고 `summary-recovered.json`에 집계한다.
두 해시는 실수로 변경한 파일을 검출한다. 로컬 소유자의 의도적 재작성에 대한 서명은 아니다.
manifest는 동결한 소스를 사용한다. 현재 checkout의 다른 fixture로 자동 교체하지 않는다.

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
CLI 자체는 기존 OAuth 로그인을 사용한다. 실행기는 로그인 자격 증명을 직접 읽지 않는다.
추론 원문, 제공자 오류 원문, 계정 이메일, 자격 증명은 저장하지 않는다.
추론 delta의 문자 수와 시점만 집계한다.
구조화된 제안·검사 결과는 합성 입력의 평가 자료다.
로그인 상태 조회는 인증 방식만 검사한다. 원문을 산출물에 쓰지 않는다.

제공자 메시지·재시도·추가 요청·`max_tokens`를 별도 집계한다.
호출 실패·취소·시간 초과와 정상 출력의 참조 불일치를 구분한다.
추가 메시지나 재시도를 관측하면 중단한다. 자동 재생성은 없다.
시간 초과와 SIGINT·SIGTERM 취소는 CLI 프로세스 그룹을 종료하고 자식을 회수한다.
여기서 자식은 실행기가 직접 시작한 CLI다. 별도 세션으로 이탈한 손자 프로세스는 회수 검증 범위 밖이다.
프로세스 회수 여부와 남은 프로세스 그룹을 결과에 기록한다.
SIGKILL·호스트 종료는 이 취소 처리의 검증 범위 밖이다.
메시지 수는 스트림에서 관측한 수다. 응답 전 실패한 네트워크 요청을 모두 증명하지 않는다.

이 실행기는 Claude CLI 생성·검사를 직접 평가한다.
Rust HTTP·DB 연결, iOS 화면, 실기기, 접근성과 운영 배포는 검증하지 않는다.
피처 플래그 기본값은 모두 OFF다.
원래 Rust 통합 증거를 이 실행기의 직접 CLI 결과로 대체하지 않는다.

## #97 실행 결과

[축약 실행 기록](fixtures/oauth-quality-results.json)에 모든 사례의 판정과 역할별 해시·시간을 보존한다.
이 기록에는 구조화 출력의 SHA-256을 저장한다. 출력 원문과 추론 원문은 넣지 않는다.
전체 원문은 작성자의 로컬 동결 디렉터리에 유지한다. 기본 CI 실행 증거는 아니다.
receipt의 `runner_commit`은 실제 평가 실행기 버전이다. 최종 PR head와 구분한다.
최초 품질 실행은 `e7065fd`, 반복 지연 실행은 `789419f`다.
그 뒤 수정은 내부 실패 기록과 부분 집계 복구다. 모델·effort·입력·후보·프롬프트·스키마는 변경하지 않았다.

| 범위 | 결과 |
| --- | --- |
| 기존 #96 Rust 통합 | 수용 14/14. 원래 상태 참조 13/14. 변경 없음 |
| #97 고정 후보 검사 | 참조 일치 32/33. 추가 제공자 메시지로 중단 1개 |
| #97 생성·독립 검사 | 수용 13/14. 새 상태 참조 13/14. 이전 상태 참조 12/14 |
| #97 전체 품질 사례 | 일치 45/47. 추가 제공자 메시지로 중단 2개. 전체 통과 아님 |
| #96 원래 입력·후보 반복 검사 | 수용 8/8. 검사 API 중앙값 36.328초. 지연 개선 미입증 |

중단한 사례는 `replacement-empty-invalid` 검사와 `generate-next` 생성이다.
두 번째 제공자 메시지를 관측해 중단했다. 실패를 보존하고 재생성하지 않았다.
추가 요청의 내부 원인은 이 기록만으로 확정하지 않는다.
품질 역할 호출 60개 중 완료는 58개다. 완료 결과의 실제 모델은 모두 Haiku 5.5 하나다.
중단한 2개에는 최종 modelUsage가 없다. 실제 모델 확인 완료로 계산하지 않는다.
품질 제공자 메시지는 62개다. 추가 메시지는 2개다.
새 상태 참조도 `generate-next` 중단을 성공으로 바꾸지 않는다.
`useful-minimum-known`은 다시 action을 반환했다. 새 참조와 일치했고 이전 참조와 불일치했다.
기존 Rust 13/14를 이 결과로 소급 수정하지 않는다.

원래 보고서 입력의 전체 시간은 112.299초·84.086초다.
생성 API는 73.961초·29.990초다. 검사 API는 36.209초·51.901초다.
두 후보는 need_info로 수용됐다. 긴 응답은 여전히 남았다.

고정한 기존 후보 두 개의 검사 API 시간은 실행 순서대로 다음과 같다.
`29.757, 34.714, 44.630, 36.657, 33.300, 35.998, 51.183, 41.074`초다.
최솟값은 29.757초이고 최댓값은 51.183초다.
후보별 4회이며 모두 다섯 기준을 충족했다. 제공자 메시지는 호출당 하나다.
변경한 검사 지시와의 새 교차 비교는 수행하지 않았다. 기존 검사 재현 결과다.
한 번의 30초 미만 표본을 개선으로 선택하지 않는다. #96은 OPEN이다.

품질·지연 두 실행에서 시간 초과·취소·max_tokens·회수 실패·남은 프로세스 그룹은 모두 0개다.
CLI 구조화 결과의 수용과 실제 사용자 응답 시간·일반 품질 승인은 구분한다.
