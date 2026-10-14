# 코딩 규칙

기존 언어·계층·공통 interface를 유지한다. 새 dependency와 formatter는 필요한 경우에만 추가한다.
작은 interface 뒤에서 검증·오류·취소·자원 소유권을 함께 처리한다.
동일한 책임의 helper를 재사용한다. 범위 밖 리팩터와 저장소 전체 포맷은 하지 않는다.

## 동작 검사

호출자가 사용하는 interface의 정상 경로와 실패 경로를 실행한다.
확인한 버그는 수정 전 실패하는 검사로 재현한다. 기존 검사가 재현하면 중복하지 않는다.
상수 재단언, 소스 문자열 순서, 성공만 반환하는 mock을 동작 검증으로 보고하지 않는다.
정적 검사는 action SHA·권한·문서 링크 등 정적 제약에 사용한다.
문서·설정 변경을 복제하는 테스트는 만들지 않는다.

## 신뢰 경계

입력은 env와 안전한 argv로 전달한다. 외부 입력을 shell 코드로 삽입하지 않는다.
인증·권한·입력 검증은 플래그와 관계없이 수행한다.
비밀정보·AI 원문·개인정보를 로그·검토 자료·artifact에 넣지 않는다.
Actions 기본 권한은 읽기다. 쓰기 권한·Secret은 필요한 job·단계로 제한한다.
제품·dependency 빌드는 배포 쓰기 권한과 production Secret을 받지 않는다.
외부 Action은 전체 SHA로 고정한다. 잠금 파일과 [도구 버전](../.ci/toolchains.json)을 유지한다.

도메인은 [CONTEXT](../CONTEXT.md), 보안·서버 제약은 [SERVER_AI](SERVER_AI.md),
작업·플래그·병합은 [WORKFLOW](WORKFLOW.md), 저작권은 [COPYRIGHT](../COPYRIGHT.md)를 따른다.
