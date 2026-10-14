# CI 실패·복구 격리 검증

검증일: 2026-10-14 KST.
이 문서는 병합하지 않는 검증 PR의 기록이다. 제품 변경이나 배포 계획이 아니다.

## 고정한 기준

- 저장소: `minjunkim-dev/smallnext`.
- 기준 main SHA: `3bb26a9a8a658f8bcd71575e2c13ad829fbdb5f2`.
- 결함 주입 범위: `scripts/draft_release.py`의 alpha 버전 형식 검사 한 줄.
- 기준 검사: 기존 Draft 입력 동작 검사 14개 통과.

## 검증 계획

1. 검증 브랜치에서 정상 alpha 버전을 잘못 거부하도록 형식 검사에 결함을 주입한다.
2. 실제 PR CI의 기존 동작 검사가 실패하는지 확인한다. 실패 run·attempt·head와 로그를 기록한다.
3. 실패를 로컬에서 재현한다. 형식 검사만 기준 main의 정상 구현으로 복구한다.
4. 같은 기존 검사와 저장소 검사를 실행한다. 테스트와 workflow는 변경하지 않는다.
5. 복구한 최종 전체 diff를 별도 Standards·Spec 컨텍스트에서 리뷰하고 필수 CI를 확인한다.

## 안전 범위와 현재 상태

현재는 실패 주입 단계다. 복구·최종 독립 리뷰·필수 CI 성공은 아직 검증하지 않았다.
GitHub Release와 Draft Release를 생성하거나 배포하지 않는다.
검증 PR은 Draft 상태로 유지한다. 자동 병합을 예약하거나 PR을 병합하지 않는다.
main과 기존 CI·브랜치 보호·Bugbot 수동·Autofix·On-demand 설정을 변경하지 않는다.
최종 head의 리뷰와 원격 CI 결과는 PR Evidence와 별도 검증 보고서에 기록한다.
